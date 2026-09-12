"""Thin provider-run references and evidence import; providers own execution.

No polling loop, worker pool or host-agent scheduler lives here. Each call either
prepares a concrete request, starts it once, observes its existing provider ID,
or imports a saved report. Lost create responses never trigger resubmission.
"""

import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from research import ResearchSessions
from service_http import ResearchHttp, ServiceError
from settings import Settings


class ResearchServices:
    DOCS = {
        "openai": "https://developers.openai.com/api/docs/guides/deep-research",
        "parallel": "https://docs.parallel.ai/task-api/guides/execute-task-run",
    }
    ACTIVE = ("pending", "queued", "in_progress", "unknown_outcome")

    def __init__(self, directory=None, settings=None, research_sessions=None, transport=None):
        self.settings = settings if settings is not None else Settings()
        self.directory = Settings.external_path(
            str(directory or (Settings.data_directory() / "service-runs")), "Research service directory")
        self.sessions = research_sessions if research_sessions is not None else ResearchSessions(settings=self.settings)
        self.transport = transport

    @staticmethod
    def _now():
        return ResearchSessions._now()

    @staticmethod
    def _text(value, label, maximum=12000):
        return ResearchSessions._text(value, label, maximum)

    @staticmethod
    def _identifier(value, label):
        return ResearchSessions._identifier(value, label)

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))

    def _provider(self, value):
        provider = self.settings.load()["professional_research"]["provider"] if value is None else value
        if not isinstance(provider, str) or provider not in self.DOCS:
            raise ValueError("Select openai or parallel for professional research")
        return provider

    def _path(self, external_id):
        if not isinstance(external_id, str) or not re.fullmatch(r"er-[a-f0-9]{24}", external_id):
            raise ValueError("Invalid external_id")
        path = self.directory / external_id
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise ValueError("Research service record must stay in its data directory")
        return Settings.external_path(str(path), "Research service record")

    @staticmethod
    def _remote_id(provider, run_id):
        pattern = r"resp_[A-Za-z0-9_-]{1,192}" if provider == "openai" else r"trun_[A-Za-z0-9_-]{1,192}"
        if not isinstance(run_id, str) or not re.fullmatch(pattern, run_id):
            raise ValueError("Invalid provider run ID")
        return run_id

    @staticmethod
    def _external_id(research_id, operation_id):
        return "er-" + hashlib.sha256((research_id + "\0" + operation_id).encode()).hexdigest()[:24]

    @staticmethod
    def _save(path, state):
        state["updated_at"] = ResearchServices._now()
        ResearchSessions._write(path / "state.json", state)

    @staticmethod
    def _write_bytes(path, value):
        """Keep report line endings and UTF-8 bytes unchanged on every OS."""
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".service-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _local_error(kind, message):
        return {"error_kind": kind, "error": message}

    def _run_data(self, provider, response):
        if not isinstance(response, dict):
            raise ValueError("Invalid research API response")
        data = response.get("run", response) if provider == "parallel" else response
        if not isinstance(data, dict):
            raise ValueError("Invalid research API run response")
        return data

    def _capture_create_id(self, state, response):
        """A valid create ID remains useful even if its report cannot be parsed."""
        if state.get("provider_run_id"):
            return
        try:
            data = self._run_data(state["provider"], response)
            state["provider_run_id"] = self._remote_id(state["provider"], data.get("id" if state["provider"] == "openai" else "run_id"))
        except ValueError:
            pass

    def _receipt(self, path, relative):
        target = ResearchSessions._artifact(path, relative)
        if target.stat().st_size > 2 * ResearchHttp.MAX_RESPONSE_BYTES:
            raise ValueError("Saved research response exceeds the local size limit")
        return json.loads(target.read_bytes(), object_pairs_hook=ResearchHttp._unique_object,
                          parse_constant=ResearchHttp._invalid_constant, parse_float=ResearchHttp._finite_float)

    def _load(self, external_id):
        path = self._path(external_id)
        state_path = path / "state.json"
        if state_path.is_symlink():
            raise ValueError("Research service state must not be a symlink")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("schema_version") != 1 or state.get("external_id") != external_id:
            raise ValueError("Inconsistent research service record")
        receipt = path / "create-receipt.json"
        if (state["status"] in ("pending", "unknown_outcome") and not state.get("attached_at")
                and not state.get("create_response_applied", bool(state.get("provider_run_id")))):
            if receipt.is_file():
                matched = False
                try:
                    value = self._receipt(path, "create-receipt.json")
                    if not isinstance(value, dict) or value.get("external_id") != external_id or value.get("digest") != state["digest"]:
                        raise ValueError("Create receipt does not match research request")
                    response = value["response"]
                    matched = True
                    self._apply_response(path, state, response, "create-receipt.json", value.get("received_at"))
                except (ValueError, OSError, KeyError, TypeError):
                    if matched:
                        self._capture_create_id(state, response)
                    state["status"] = "unknown_outcome"
                    state["observation_error"] = self._local_error("create_receipt_error", "Saved create receipt could not be verified or interpreted; no request was repeated")
            elif state["status"] == "pending":
                state["status"] = "unknown_outcome"
                state["observation_error"] = self._local_error("create_interrupted", "Create outcome is unknown; no provider request was repeated")
        pending = state.get("pending_observation")
        if pending:
            try:
                value = self._receipt(path, pending["response_file"])
                if (not isinstance(value, dict) or value.get("external_id") != external_id
                        or value.get("provider_run_id") != state.get("provider_run_id") or value.get("action") != pending["action"]):
                    raise ValueError("Observation receipt does not match the existing run")
                self._apply_response(path, state, value["response"], pending["response_file"], value.get("received_at"))
                state.pop("pending_observation", None)
            except (ValueError, OSError, KeyError, TypeError):
                state["observation_error"] = self._local_error("observation_receipt_error", "An interrupted observation could not be recovered; the last provider state is retained")
        return path, state

    def _request(self, provider, method, endpoint, payload=None):
        client = self.transport or ResearchHttp(self.settings.load()["timeout_seconds"])
        return client.request(provider, method, endpoint, payload)

    def describe(self, provider=None):
        config = self.settings.load()["professional_research"]
        providers = [self._provider(provider)] if provider is not None else list(self.DOCS)
        return {"enabled": config["enabled"], "default_provider": config["provider"], "network_checked": False,
                "providers": [{"provider": name, "docs": self.DOCS[name],
                    "credential_env": ResearchHttp.PROVIDERS[name]["key_env"],
                    "credential_configured": bool(os.environ.get(ResearchHttp.PROVIDERS[name]["key_env"])),
                    "authentication_verified": False, "defaults": config[name],
                    "cancel_supported": name == "openai",
                    "budget_controls": ["max_tool_calls"] if name == "openai" else ["processor"]}
                    for name in providers],
                "execution": "Provider-managed runs; observe explicitly by run ID. No local worker or automatic retry.",
                "cost_note": "Tool-count/processor controls are not a monetary cap. Host-native research tools remain usable independently."}

    def prepare(self, research_id, input, provider=None, question_id=None, inventory_ids=None, options=None):
        provider = self._provider(provider)
        input = self._text(input, "Research service input", 50000)
        _, state = self.sessions._load(research_id)
        ResearchSessions._active(state)
        if question_id is not None:
            ResearchSessions._find(state["questions"], question_id, "question")
        options = {} if options is None else copy.deepcopy(options)
        if not isinstance(options, dict):
            raise ValueError("Research service options must be an object")
        allowed = {"model", "max_tool_calls", "store", "vector_store_ids"} if provider == "openai" else {"processor", "output_schema"}
        if set(options) - allowed:
            raise ValueError("Unsupported " + provider + " research options")
        source_scope = copy.deepcopy(state.get("source_scope", {}))
        selected = source_scope.get("selected_inventory_ids", [])
        if inventory_ids is not None:
            if (not isinstance(inventory_ids, list) or any(not isinstance(x, str) for x in inventory_ids)
                    or len(set(inventory_ids)) != len(inventory_ids) or set(inventory_ids) - set(selected)):
                raise ValueError("inventory_ids must select distinct sources within the frozen research scope")
            selected = inventory_ids[:]
        sources, local_only = [], []
        selected_set = set(selected)
        # _load verified the frozen inventory. Read its complete entries here:
        # the public inventory API intentionally limits ID filters and may
        # replace oversized context with an artifact pointer in a single page.
        for item in state.get("inventory", []):
            if item["id"] not in selected_set:
                continue
            url = item.get("retrieval_url")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                sources.append({"source_id": item["id"], "url": url})
            else:
                local_only.append(item["id"])
        shared = {"research_question": input, "sources": sources,
                  "local_only_source_ids": local_only,
                  "requirements": "Investigate the question using the supplied source scope. Identify unread or inaccessible sources and contradictions. Return a cited report; do not claim coverage for sources not actually reviewed."}
        input_text = self._json(shared)
        if len(input_text) > 1_000_000:
            raise ValueError("Research input exceeds the API adapter size limit; explicitly split the investigation without shrinking its recorded scope")
        defaults = self.settings.load()["professional_research"][provider]
        if provider == "openai":
            model = options.get("model", defaults["model"])
            maximum = options.get("max_tool_calls", defaults["max_tool_calls"])
            if model not in ("o3-deep-research", "o4-mini-deep-research"):
                raise ValueError("Use a documented OpenAI deep research model")
            if type(maximum) is not int or not 1 <= maximum <= 1000:
                raise ValueError("max_tool_calls must be between 1 and 1000")
            store = options.get("store", False)
            if type(store) is not bool:
                raise ValueError("store must be boolean")
            tools = [{"type": "web_search_preview"}]
            if "vector_store_ids" in options:
                stores = options["vector_store_ids"]
                if (not isinstance(stores, list) or not 1 <= len(stores) <= 2
                        or any(not isinstance(x, str) or not re.fullmatch(r"vs_[A-Za-z0-9_-]+", x) for x in stores)):
                    raise ValueError("vector_store_ids must contain one or two remote OpenAI vector store IDs")
                tools.append({"type": "file_search", "vector_store_ids": stores})
            payload = {"model": model, "input": input_text, "background": True, "store": store,
                       "tools": tools, "max_tool_calls": maximum}
            endpoint = "/v1/responses"
        else:
            processor = options.get("processor", defaults["processor"])
            if not isinstance(processor, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", processor):
                raise ValueError("Invalid Parallel processor")
            schema = options.get("output_schema", "A Markdown research report with citations, contradictions, and an explicit source coverage/gap section.")
            schema = self._text(schema, "Parallel output schema", 12000)
            payload = {"processor": processor, "input": input_text, "task_spec": {"output_schema": schema}}
            endpoint = "/v1/tasks/runs"
        return {"research_id": research_id, "provider": provider, "question_id": question_id,
                "endpoint": endpoint, "payload": payload,
                "source_scope": {"input_version": source_scope.get("input_version"),
                    "inventory_ids": selected, "shared_url_count": len(sources),
                    "local_only_inventory_ids": local_only,
                    "remaining_inventory_ids": [x for x in source_scope.get("selected_inventory_ids", []) if x not in selected_set]},
                "network_performed": False,
                "data_note": "Only the explicit input and source URLs are sent. Local paths, bookmark labels, notes and files are not uploaded. Imported reports do not count as reading their cited pages."}

    def _publish(self, path, state, strict=False):
        entry = {"kind": "external_run", "id": state["external_id"], "provider": state["provider"],
                 "run_id": state.get("provider_run_id") or state["external_id"],
                 "status": state["status"],
                 "text": "Provider-run observation; " + ("provider ID verified from a response or explicitly attached." if state.get("provider_run_id") else "create outcome has no known provider ID; no local worker is implied."),
                 "result": {"provider_status": state.get("provider_status"), "observed_at": state.get("observed_at"),
                            "source_scope": state.get("source_scope"), "report_path": state.get("report_path"),
                            "usage": state.get("usage"), "observation_error": state.get("observation_error")}}
        if state.get("response_file"):
            entry["artifact_path"] = str(path / state["response_file"])
        try:
            self.sessions.record(state["research_id"], entry)
            state.pop("research_record_error", None)
        except (ValueError, OSError, RuntimeError) as error:
            if strict:
                raise
            state["research_record_error"] = "Provider observation saved, but research record could not be updated: " + type(error).__name__

    @staticmethod
    def _summary(path, state):
        fields = ("external_id", "research_id", "operation_id", "provider", "provider_run_id", "status",
                  "provider_status", "created_at", "updated_at", "observed_at", "source_scope", "report_path",
                  "report_sha256", "response_sha256", "request_sha256", "citations_file", "citations_sha256", "citation_count",
                  "usage", "observation_error", "research_record_error", "imported_evidence")
        return {**{key: copy.deepcopy(state.get(key)) for key in fields}, "directory": str(path),
                "request_path": str(path / "request.json") if (path / "request.json").is_file() else None,
                "observations": len(state.get("observations", [])),
                "local_worker_running": False,
                "note": "Status is the last observation. Refresh observes the same provider run; a timeout never recreates it."}

    def _intent(self, input, provider, question_id, inventory_ids, options):
        value = {"input": self._text(input, "Research service input", 50000), "provider": provider,
                 "question_id": question_id, "inventory_ids": inventory_ids, "options": {} if options is None else options}
        if provider is not None and (not isinstance(provider, str) or provider not in self.DOCS):
            raise ValueError("Select openai or parallel for professional research")
        if not isinstance(value["options"], dict):
            raise ValueError("Research service options must be an object")
        if question_id is not None:
            self._identifier(question_id, "question_id")
        if inventory_ids is not None and (not isinstance(inventory_ids, list)
                or any(not isinstance(item, str) for item in inventory_ids) or len(set(inventory_ids)) != len(inventory_ids)):
            raise ValueError("inventory_ids must contain distinct source IDs")
        try:
            return json.loads(self._json(value))
        except (ValueError, TypeError):
            raise ValueError("Research service arguments must contain valid JSON") from None

    def _replay_matches(self, path, state, intent, intent_digest):
        if state.get("intent_digest") is not None:
            return state["intent_digest"] == intent_digest
        # Read old records against their frozen request, never today's defaults.
        if not state.get("digest") or not (path / "request.json").is_file():
            return False
        request = self._receipt(path, "request.json")
        if hashlib.sha256(self._json(request).encode()).hexdigest() != state["digest"]:
            raise ValueError("Saved research request hash does not match")
        if intent["provider"] not in (None, state["provider"]) or intent["question_id"] != request.get("question_id"):
            return False
        if intent["input"] != json.loads(request["payload"]["input"])["research_question"]:
            return False
        if intent["inventory_ids"] is not None and intent["inventory_ids"] != request["source_scope"]["inventory_ids"]:
            return False
        for key, value in intent["options"].items():
            payload = request["payload"]
            old = payload.get("task_spec", {}).get("output_schema") if key == "output_schema" else payload.get(key)
            if key == "vector_store_ids":
                old = next((tool.get(key) for tool in payload.get("tools", []) if tool.get("type") == "file_search"), None)
            if old != value:
                return False
        return True

    def start(self, research_id, operation_id, input, provider=None, question_id=None, inventory_ids=None, options=None):
        operation_id = self._identifier(operation_id, "operation_id")
        self.sessions._path(research_id)
        intent = self._intent(input, provider, question_id, inventory_ids, options)
        intent_digest = hashlib.sha256(self._json(intent).encode()).hexdigest()
        external_id = self._external_id(research_id, operation_id)
        path = self._path(external_id)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        with Settings._update_lock(path / "state.json"):
            if (path / "state.json").exists():
                _, state = self._load(external_id)
                if not self._replay_matches(path, state, intent, intent_digest):
                    raise ValueError("operation_id already refers to a different research service request")
                self._publish(path, state)
                self._save(path, state)
                return {**self._summary(path, state), "replayed": True}
            request = self.prepare(research_id, input, provider, question_id, inventory_ids, options)
            provider = request["provider"]
            digest = hashlib.sha256(self._json(request).encode()).hexdigest()
            if not self.settings.load()["professional_research"]["enabled"]:
                raise ValueError("Professional research is disabled; enable professional_research.enabled to start API runs")
            if not os.environ.get(ResearchHttp.PROVIDERS[provider]["key_env"]):
                raise ServiceError("authentication_required", "Set " + ResearchHttp.PROVIDERS[provider]["key_env"] + " in the host environment")
            state = {"schema_version": 1, "external_id": external_id, "research_id": research_id,
                     "operation_id": operation_id, "provider": provider, "provider_run_id": None,
                     "question_id": question_id, "digest": digest, "intent_digest": intent_digest, "status": "pending",
                     "create_response_applied": False,
                     "source_scope": request["source_scope"], "created_at": self._now(), "observations": []}
            ResearchSessions._write(path / "request.json", request)
            state["request_sha256"] = hashlib.sha256((path / "request.json").read_bytes()).hexdigest()
            self._save(path, state)
            try:
                self._publish(path, state, strict=True)
            except (ValueError, OSError, RuntimeError):
                state["status"] = "error"
                state["observation_error"] = {"error_kind": "local_record_failed", "error": "Research record rejected before the API call"}
                self._save(path, state)
                raise
            result = None
            try:
                result = self._request(provider, "POST", request["endpoint"], request["payload"])
                ResearchSessions._write(path / "create-receipt.json",
                                        {"external_id": external_id, "digest": digest, "received_at": self._now(), "response": result})
                self._apply_response(path, state, result, "create-receipt.json")
            except ServiceError as error:
                state["status"] = "unknown_outcome" if error.uncertain else "error"
                state["observation_error"] = error.details()
            except (OSError, ValueError, TypeError):
                # The provider may already have accepted this request.
                state["status"] = "unknown_outcome"
                if result is not None:
                    self._capture_create_id(state, result)
                state["observation_error"] = {"error_kind": "local_result_error",
                                             "error": "Create result could not be saved or interpreted"}
            self._publish(path, state)
            self._save(path, state)
            return {**self._summary(path, state), "replayed": False}

    def _apply_response(self, path, state, response, response_file, observed_at=None):
        data = self._run_data(state["provider"], response)
        run_id = data.get("run_id" if state["provider"] == "parallel" else "id")
        run_id = self._remote_id(state["provider"], run_id)
        if state.get("provider_run_id") not in (None, run_id):
            raise ValueError("Response belongs to a different provider run")
        remote_status = data.get("status")
        if not isinstance(remote_status, str) or not remote_status or len(remote_status) > 100:
            raise ValueError("Invalid research API run status")
        states = {"queued": "queued", "running": "in_progress", "in_progress": "in_progress",
                  "action_required": "in_progress", "cancelling": "in_progress", "completed": "completed",
                  "failed": "error", "incomplete": "error", "cancelled": "cancelled"}
        candidate = copy.deepcopy(state)
        candidate["provider_run_id"] = run_id
        candidate["create_response_applied"] = True
        candidate["status"] = states.get(remote_status, "unknown_outcome")
        candidate["provider_status"] = remote_status
        candidate["observed_at"] = observed_at or self._now()
        candidate["response_file"] = response_file
        candidate["response_sha256"] = hashlib.sha256(ResearchSessions._artifact(path, response_file).read_bytes()).hexdigest()
        candidate.pop("observation_error", None)
        candidate["usage"] = copy.deepcopy(response.get("usage", data.get("usage")))
        if candidate["usage"] is not None and not isinstance(candidate["usage"], dict):
            raise ValueError("Invalid provider usage metadata")
        self._json(candidate["usage"])
        report, citations = self._report(state["provider"], response)
        if report:
            raw = report.encode("utf-8")
            report_file = "reports/" + hashlib.sha256(raw).hexdigest() + ".md"
            self._write_bytes(ResearchSessions._artifact(path, report_file), raw)
            citation_bytes = (self._json(citations) + "\n").encode("utf-8")
            citation_file = "reports/" + hashlib.sha256(citation_bytes).hexdigest() + "-citations.json"
            self._write_bytes(ResearchSessions._artifact(path, citation_file), citation_bytes)
            candidate["report_path"] = str(path / report_file)
            candidate["report_sha256"] = hashlib.sha256(raw).hexdigest()
            candidate["citations_file"] = str(path / citation_file)
            candidate["citations_sha256"] = hashlib.sha256(citation_bytes).hexdigest()
            candidate["citation_count"] = len(citations)
            candidate.pop("citations", None)
        candidate.setdefault("observations", []).append(
            {"observed_at": candidate["observed_at"], "provider_status": remote_status, "response_file": response_file,
             "response_sha256": candidate["response_sha256"]})
        # A parser/storage failure must never leave a half-applied terminal
        # state, a replacement run ID or mismatched report metadata behind.
        state.clear()
        state.update(candidate)

    @staticmethod
    def _report(provider, response):
        texts, citations = [], []
        def rows(value, label):
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ValueError("Invalid " + label + " in research API response")
            return value
        if provider == "openai":
            for item in rows(response.get("output", []), "output"):
                if item.get("type") != "message":
                    continue
                for content in rows(item.get("content", []), "message content"):
                    if content.get("type") != "output_text":
                        continue
                    if not isinstance(content.get("text"), str):
                        raise ValueError("Invalid output text in research API response")
                    texts.append(content["text"])
                    for annotation in rows(content.get("annotations", []), "annotations"):
                        if annotation.get("type") == "url_citation":
                            citations.append(copy.deepcopy(annotation))
        else:
            output = response.get("output")
            if "run" in response and not isinstance(output, dict):
                raise ValueError("Parallel result must contain its run and output objects")
            if output is not None:
                if not isinstance(output, dict):
                    raise ValueError("Invalid Parallel result output")
                content = output.get("content")
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, dict):
                    texts.append(json.dumps(content, ensure_ascii=False, allow_nan=False, indent=2))
                else:
                    raise ValueError("Invalid Parallel result content")
                for basis in rows(output.get("basis", []), "research basis"):
                    for citation in rows(basis.get("citations", []), "basis citations"):
                        citations.append(copy.deepcopy(citation))
        return "\n\n".join(texts), citations

    @staticmethod
    def _read_saved(path, file, expected_hash):
        target = Path(file)
        if target.is_symlink() or path not in target.resolve().parents:
            raise ValueError("Research artifact must stay within its run directory")
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ValueError("Saved research artifact hash does not match")
        return raw

    def _read_report(self, path, state):
        if not state.get("report_path"):
            return ""
        return self._read_saved(path, state["report_path"], state["report_sha256"]).decode("utf-8")

    def _citations(self, path, state):
        if state.get("citations_file"):
            citations = json.loads(self._read_saved(path, state["citations_file"], state["citations_sha256"]))
        else:
            citations = state.get("citations", [])
        if not isinstance(citations, list):
            raise ValueError("Invalid saved provider citations")
        return citations

    def _citation_preview(self, citations, byte_limit=100000):
        selected, consumed = [], 0
        for citation in citations[:100]:
            size = len(self._json(citation).encode("utf-8"))
            if consumed + size > byte_limit:
                break
            selected.append(citation)
            consumed += size
        return selected

    def status(self, external_id, refresh=False):
        path = self._path(external_id)
        with Settings._update_lock(path / "state.json"):
            _, state = self._load(external_id)
            if refresh:
                self._observe(path, state, "status")
            self._publish(path, state)
            self._save(path, state)
            return self._summary(path, state)

    def _observe(self, path, state, action):
        run_id = state.get("provider_run_id")
        if not run_id:
            raise ValueError("No provider run ID is known; attach an independently verified ID instead of restarting")
        run_id = self._remote_id(state["provider"], run_id)
        prefix = "/v1/responses/" if state["provider"] == "openai" else "/v1/tasks/runs/"
        endpoint, method, payload = prefix + run_id, "GET", None
        if action == "cancel":
            if state["provider"] != "openai":
                raise ValueError("Parallel Task cancellation is not established by this adapter; remote state is unchanged")
            endpoint, method, payload = endpoint + "/cancel", "POST", {}
        elif action == "result" and state["provider"] == "parallel":
            endpoint += "/result?timeout=1"
        response_file = "observations/" + uuid.uuid4().hex + ".json"
        state["pending_observation"] = {"action": action, "response_file": response_file, "started_at": self._now()}
        self._save(path, state)
        try:
            result = self._request(state["provider"], method, endpoint, payload)
            ResearchSessions._write(ResearchSessions._artifact(path, response_file), {
                "external_id": state["external_id"], "provider_run_id": run_id, "action": action,
                "received_at": self._now(), "response": result})
            self._apply_response(path, state, result, response_file)
            state.pop("pending_observation", None)
        except ServiceError as error:
            # This is an observation failure, not a provider terminal status.
            state["observation_error"] = error.details()
            state.setdefault("observations", []).append({"observed_at": self._now(), "action": action,
                                                        "observation_error": error.details()})
            state.pop("pending_observation", None)
        except (ValueError, OSError, TypeError):
            state["observation_error"] = {"error_kind": "local_result_error",
                                         "error": "Provider observation could not be saved or interpreted"}

    def result(self, external_id, refresh=False, offset=0, limit=12000):
        ResearchSessions._integer(offset, "offset", 0, 10000000)
        ResearchSessions._integer(limit, "limit", 1, 50000)
        path = self._path(external_id)
        with Settings._update_lock(path / "state.json"):
            _, state = self._load(external_id)
            if refresh:
                self._observe(path, state, "result")
            self._publish(path, state)
            self._save(path, state)
            text = self._read_report(path, state)
            citations = self._citations(path, state)
            preview = self._citation_preview(citations)
            return {**self._summary(path, state), "text": text[offset:offset + limit], "offset": offset,
                    "total_characters": len(text), "next_offset": offset + limit if offset + limit < len(text) else None,
                    "citations": preview, "citation_count": len(citations), "citations_truncated": len(preview) < len(citations),
                    "citations_verified": False}

    def cancel(self, external_id):
        path = self._path(external_id)
        with Settings._update_lock(path / "state.json"):
            _, state = self._load(external_id)
            if state["status"] in self.ACTIVE:
                self._observe(path, state, "cancel")
            self._publish(path, state)
            self._save(path, state)
            return self._summary(path, state)

    def attach(self, research_id, operation_id, provider, run_id, question_id=None):
        provider = self._provider(provider)
        operation_id = self._identifier(operation_id, "operation_id")
        run_id = self._remote_id(provider, run_id)
        self.sessions._path(research_id)
        external_id = self._external_id(research_id, operation_id)
        path = self._path(external_id)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        with Settings._update_lock(path / "state.json"):
            existed = (path / "state.json").exists()
            if existed:
                _, state = self._load(external_id)
                if state["provider"] != provider or state.get("provider_run_id") not in (None, run_id):
                    raise ValueError("Existing operation refers to a different provider run")
                if question_id is not None and state.get("question_id") not in (None, question_id):
                    raise ValueError("Existing operation belongs to another research question")
                if question_id is not None and state.get("question_id") is None:
                    _, research = self.sessions._load(research_id)
                    ResearchSessions._find(research["questions"], question_id, "question")
                    state["question_id"] = question_id
                state["provider_run_id"] = run_id
            else:
                _, research = self.sessions._load(research_id)
                ResearchSessions._active(research)
                if question_id is not None:
                    ResearchSessions._find(research["questions"], question_id, "question")
                state = {"schema_version": 1, "external_id": external_id, "research_id": research_id,
                         "operation_id": operation_id, "provider": provider, "provider_run_id": run_id,
                         "question_id": question_id, "digest": None, "status": "unknown_outcome",
                         "created_at": self._now(), "source_scope": None, "observations": []}
            state["attached_at"] = self._now()
            self._publish(path, state, strict=not existed)
            self._save(path, state)
            return self._summary(path, state)

    def import_result(self, external_id, operation_id, question_id=None):
        operation_id = self._identifier(operation_id, "operation_id")
        path = self._path(external_id)
        with Settings._update_lock(path / "state.json"):
            _, state = self._load(external_id)
            if state["status"] != "completed" or not state.get("report_path"):
                raise ValueError("A completed, saved provider report is required for import")
            question_id = question_id if question_id is not None else state.get("question_id")
            if question_id is None:
                raise ValueError("question_id is required to import a report")
            text = self._read_report(path, state)
            citations = self._citations(path, state)
            endpoint = "/v1/responses/" if state["provider"] == "openai" else "/v1/tasks/runs/"
            url = ResearchHttp.PROVIDERS[state["provider"]]["origin"] + endpoint + self._remote_id(state["provider"], state["provider_run_id"])
            provenance = {"kind": "external_report", "provider": state["provider"], "run_id": state["provider_run_id"],
                          "external_id": external_id, "artifact_hash": state["report_sha256"], "text_sha256": state["report_sha256"],
                          "citations_verified": False, "provider_citations": self._citation_preview(citations, byte_limit=16000),
                          "provider_citation_count": len(citations)}
            if state.get("citations_file"):
                provenance.update(provider_citations_file=state["citations_file"], provider_citations_sha256=state["citations_sha256"])
            self._publish(path, state)
            evidence = self.sessions.import_evidence(state["research_id"], operation_id, question_id, url, text, provenance,
                inventory_ids=(state.get("source_scope") or {}).get("inventory_ids", []),
                title=state["provider"] + " research report")
            state["imported_evidence"] = evidence
            self._save(path, state)
        return {"external_id": external_id, "research_id": state["research_id"], "evidence": evidence,
                "coverage_note": "Imported as an external report. Referenced original pages remain unreviewed until read and assessed independently."}
