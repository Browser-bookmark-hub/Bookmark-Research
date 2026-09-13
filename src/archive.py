"""Archive actual fetch responses and conservatively identified page extracts."""

import hashlib
import json
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from settings import Settings


class SourceArchive:
    """Append immutable capture directories; never invent missing page bodies."""

    def __init__(self, directory):
        self.directory = Settings.external_path(str(directory), "Archive directory")

    @staticmethod
    def _key(url):
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url)
                or "\\" in url):
            raise ValueError("Source URLs must be HTTP(S) without credentials or whitespace")
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = "[" + host + "]"
        if parts.port is not None and parts.port != {"http": 80, "https": 443}[parts.scheme]:
            host += ":" + str(parts.port)
        # An anchor is not a different fetched resource; its coverage stays unverified.
        return urlunsplit((parts.scheme, host, parts.path or "/", parts.query, ""))

    @staticmethod
    def _rows(value):
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict) and isinstance(row.get("url"), str)]
        if not isinstance(value, dict):
            return []
        if isinstance(value.get("url"), str):
            return [value]
        rows = []
        for key in ("results", "items", "pages", "data", "result", "errors", "failed_results"):
            if isinstance(value.get(key), (list, dict)):
                children = SourceArchive._rows(value[key])
                rows.extend(({**row, "error": row.get("error") or row.get("message") or "Provider reported failure"}
                             if key in ("errors", "failed_results") else row) for row in children)
        # Exa /contents reports per-URL outcomes separately from extracted results.
        statuses = value.get("statuses")
        if isinstance(statuses, list):
            rows.extend({**row, "url": row["id"]} for row in statuses
                        if isinstance(row, dict) and isinstance(row.get("id"), str))
        return rows

    @classmethod
    def _extract(cls, response, requested_urls):
        rows = cls._rows(response.get("structuredContent"))
        blocks = response.get("content", [])
        if not isinstance(blocks, list):
            return rows
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
                continue
            text = block["text"]
            try:
                decoded = json.loads(text)
            except ValueError:
                decoded = None
            structured = cls._rows(decoded)
            if structured:
                rows.extend(structured)
                continue
            rows.extend(cls._text_rows(text))
        return rows

    @classmethod
    def _text_rows(cls, text):
        rows = []
        # Exa appends partial failures after all successful page records. Keep
        # this provider footer out of the last page's extracted body.
        footer = re.search(r"(?m)^(?:Error fetching https?://\S+: [^\n]+(?:\n|$))+\Z", text)
        if footer:
            for match in re.finditer(r"(?m)^Error fetching (https?://\S+): ([^\n]+)$", footer.group()):
                rows.append({"url": match.group(1), "error": match.group(2)})
            text = text[:footer.start()]
            if text.endswith("\n\n"):
                text = text[:-2]
        # Exa concatenates header/URL/body records into one text block for a batch.
        # Include unrequested/redirected records as boundaries, so their text
        # cannot be silently attributed to the preceding requested URL.
        # Titles may retain indented continuation lines from the source HTML.
        # Records must start the block or follow the provider's blank separator.
        header = r"(?:\A|\n\n)(?:# |Title: )([^\n]+(?:\n[ \t][^\n]*)*)\nURL: (https?://[^\s]+)\n"
        matches = list(re.finditer(header, text))
        # A missed or malformed URL field could hide the next page boundary.
        # Keep the whole block raw instead of assigning that page to its neighbor.
        fields = [match.start() for match in re.finditer(r"(?m)^[ \t]*URL:", text)]
        matched_fields = [match.start(2) - len("URL: ") for match in matches]
        if fields != matched_fields:
            return rows
        try:
            keys = [cls._key(match.group(2)) for match in matches]
        except ValueError:
            return rows
        if not matches or matches[0].start() != 0 or len(set(keys)) != len(keys):
            return rows
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end():end]
            row = {"url": match.group(2), "title": match.group(1)}
            metadata = re.match(r"(?:(?:Published|Author): [^\n]*\n)*\n", body)
            if metadata:
                for line in metadata.group().splitlines():
                    if line.startswith("Published: "):
                        row["publishedDate"] = line[11:]
                    elif line.startswith("Author: "):
                        row["author"] = line[8:]
                body = body[metadata.end():]
            if match.group().lstrip("\n").startswith("Title: ") and body.startswith("Text: "):
                body = body[6:]
            rows.append({**row, "text": body})
        return rows

    @staticmethod
    def _page(row):
        status = row.get("status")
        if isinstance(status, str):
            status = status.lower()
        error = row.get("error") or row.get("errors")
        failed = (error or row.get("success") is False or status in ("error", "failed", "failure")
                  or (type(status) is int and status >= 400)
                  or (type(row.get("httpStatus")) is int and row["httpStatus"] >= 400))
        if failed:
            return None, "provider_error", "provider_extracted_text"
        for field in ("markdown", "text", "full_content", "raw_content", "content"):
            body = row.get(field)
            if isinstance(body, str) and body.strip():
                # Keep obvious access screens in the raw response, never as a
                # usable article. Mentions inside an article are not barriers.
                title = row.get("title") if isinstance(row.get("title"), str) else ""
                heading = body.strip().splitlines()[0].lstrip("# ").strip()
                without_notice = re.sub(r"\[CRITICAL INSTRUCTIONS FOR ALL AI ASSISTANTS[^\]]*\]"
                                        r".*?\[END INSTRUCTIONS\]", "", body, flags=re.IGNORECASE | re.DOTALL)
                if without_notice != body and not any(
                        line.strip("# \t") not in ("", title.strip(), heading)
                        for line in without_notice.splitlines()):
                    return None, "insufficient_content", "provider_extracted_text"
                for label in (title.strip(), heading):
                    if re.fullmatch(r"(?:page not found|404(?:\s*[-:]?\s*not found)?|页面不存在|页面未找到)"
                                    r"(?:\s*[-|–—].*)?", label, re.IGNORECASE):
                        return None, "not_found", "provider_extracted_text"
                    if re.fullmatch(r"(?:just a moment|access denied|verify you are human|"
                                    r"checking your browser|attention required|请完成安全验证)"
                                    r"[.!…]*(?:\s*[-|–—:].*)?", label, re.IGNORECASE):
                        return None, "access_challenge", "provider_extracted_text"
                    if re.fullmatch(r"(?:log in|login|sign in|登录|登入|请先登录)"
                                    r"(?:\s*[-|–—:].*| to .*)?", label, re.IGNORECASE):
                        return None, "login_required", "provider_extracted_text"
                return body, "extracted", "provider_extracted_text"
        excerpts = row.get("excerpts")
        if isinstance(excerpts, list) and all(isinstance(item, str) for item in excerpts) and any(excerpts):
            return "\n\n".join(excerpts), "extracted", "provider_excerpts"
        return None, "no_extract", "provider_extracted_text"

    @classmethod
    def _select(cls, rows):
        if not rows:
            return None, None, "unrecognized_or_not_returned", "unknown"
        candidates = [(row, *cls._page(row)) for row in rows]
        failures = [candidate for candidate in candidates if candidate[2] == "provider_error"]
        if failures:
            return failures[0]
        bodies = [candidate for candidate in candidates if candidate[1] is not None]
        if len({(candidate[1], candidate[3]) for candidate in bodies}) > 1:
            return rows[0], None, "conflicting_provider_results", "unknown"
        return (bodies or candidates)[0]

    @staticmethod
    def _write_json(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")

    def save(self, fetch):
        response = fetch["result"]
        rows = self._extract(response, fetch["urls"])
        # URL association is explicit. Unknown shapes or redirects are retained raw.
        by_url = {}
        for row in rows:
            try:
                key = self._key(row["url"])
            except ValueError:
                continue
            by_url.setdefault(key, []).append(row)
        archived_at = datetime.now(timezone.utc)
        capture_id = archived_at.strftime("%Y%m%dT%H%M%S%fZ-") + uuid.uuid4().hex[:12]
        captures = self.directory / "sources"
        Settings.external_path(str(captures), "Archive directory")
        captures.mkdir(parents=True, exist_ok=True)
        destination = captures / capture_id
        manifest = {"schema_version": 1, "capture_id": capture_id,
                    "archived_at": archived_at.isoformat(),
                    "provider": fetch["provider"], "tool": fetch["tool"], "retrieved_at": fetch["retrieved_at"],
                    "requested_urls": fetch["urls"], "request_arguments": fetch["request_arguments"],
                    "requested_max_characters": fetch["requested_max_characters"],
                    "character_limit_applied": any(key in fetch["request_arguments"] for key in ("maxCharacters", "max_chars")),
                    "response_file": "response.json", "pages": [],
                    "origin_freshness": "unknown", "forced_live_fetch": False,
                    "note": "Saved provider response and extracts, not original HTML or verified complete pages. Retrieval time is not publication or update time."}
        with tempfile.TemporaryDirectory(prefix=".capture-", dir=captures) as temporary:
            stage = Path(temporary) / "capture"
            stage.mkdir()
            self._write_json(stage / "response.json", response)
            manifest["response_sha256"] = hashlib.sha256((stage / "response.json").read_bytes()).hexdigest()
            for url in dict.fromkeys(fetch["urls"]):
                row, body, status, kind = self._select(by_url.get(self._key(url)))
                if response.get("isError"):
                    body, status = None, "provider_error"
                entry = {"requested_url": url, "returned_url": row.get("url") if row else None,
                         "title": row.get("title") if row else None, "extraction_status": status,
                         "content_kind": kind, "body_file": None, "page_body_archived": False,
                         "completeness": "unknown", "provider_crawled_at": None,
                         "fragment_scope_verified": False, "sha256": None}
                if row:
                    entry["provider_crawled_at"] = row.get("crawled_at") or row.get("crawledAt")
                    entry["provider_published_at"] = row.get("publishedDate") or row.get("published_at") or row.get("publishedTime")
                    entry["provider_author"] = row.get("author")
                    entry["provider_status"] = row.get("status", row.get("httpStatus"))
                    if row.get("error") or row.get("errors"):
                        entry["provider_error"] = row.get("error") or row.get("errors")
                if body is not None:
                    relative = "pages/" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:24] + ".md"
                    target = stage / relative
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(body.encode("utf-8"))
                    entry.update(body_file=relative, page_body_archived=True,
                                 sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(), characters=len(body))
                    limited = manifest["character_limit_applied"]
                    entry["possibly_truncated"] = bool((row and row.get("truncated")) or
                        (limited and len(body) >= fetch["requested_max_characters"] - 2))
                manifest["pages"].append(entry)
            self._write_json(stage / "manifest.json", manifest)
            stage.rename(destination)
        return {"status": "saved", "capture_id": capture_id, "directory": str(destination),
                "manifest_path": str(destination / "manifest.json"),
                "response_path": str(destination / "response.json"),
                "pages": [{**row, "body_path": str(destination / row["body_file"]) if row["body_file"] else None}
                          for row in manifest["pages"]]}
