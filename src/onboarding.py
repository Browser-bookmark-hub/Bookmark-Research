"""Human CLI setup and the equivalent JSON-driven agent path."""

from contextlib import contextmanager
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from credentials import Credentials
from readiness import Readiness
from settings import Settings
from tui import Option, Prompter


HOSTS = (("codex", "Codex", "Codex"), ("claude", "Claude Code", "Claude Code"), ("pi", "Pi", "Pi"),
         ("dsh", "DSH / DeepSeek Harness", "DSH / DeepSeek Harness"))


def _profile_problem(value):
    if not value or value.startswith(".") or not all(char.isalnum() or char in "._-" for char in value):
        return ("Use letters, numbers, dots, underscores or hyphens; do not start with a dot.",
                "仅可使用字母、数字、点、下划线或连字符，且不能以点开头。")
    return None


def _directory_problem(value):
    if not value or not Path(value).expanduser().is_dir():
        return ("Enter an existing directory.", "请输入已存在的目录。")
    return None


class Console(Prompter):
    @staticmethod
    def resolve_language(language="auto"):
        if language != "auto":
            return language
        locale = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG", "en")
        return "zh" if locale.lower().startswith("zh") else "en"

    def __init__(self, reader, writer, language="en", rich=None):
        super().__init__(reader, writer, language, rich)

    # Backward-compatible helpers built on the Prompter primitives.
    def ask(self, english, chinese, default=""):
        return self.input(english, chinese, "" if default is None else str(default))

    def choice(self, english, chinese, options, default):
        return self.select(english, chinese, [Option(value, en, zh) for value, en, zh in options], default)

    def yes(self, english, chinese, default=False):
        return self.confirm(english, chinese, default)

    def providers(self, english, chinese, default, optional=False):
        return self.multiselect(english, chinese, [Option(name, name) for name in Settings.PROVIDERS],
                                default, required=not optional)

    @classmethod
    @contextmanager
    def open(cls, mode="auto", language="en"):
        if mode == "never" or (mode == "auto" and not sys.stderr.isatty()):
            yield None
            return
        try:
            # curl | bash consumes stdin. Prompts must use the controlling tty,
            # never read shell source bytes or an agent's piped JSON input.
            names = ("CONIN$", "CONOUT$") if os.name == "nt" else ("/dev/tty", "/dev/tty")
            reader = open(names[0], "r", encoding="utf-8")
            try:
                writer = open(names[1], "w", encoding="utf-8", buffering=1)
            except OSError:
                reader.close()
                raise
        except OSError:
            if sys.stdin.isatty():
                yield cls(sys.stdin, sys.stderr, language)
            elif mode == "always":
                raise ValueError("Interactive setup needs a terminal; use --non-interactive with --host and --preferences") from None
            else:
                yield None
        else:
            with reader, writer:
                yield cls(reader, writer, language)

    def install_targets(self, args):
        self.intro("Bookmark Research — guided installation", "Bookmark Research — 引导安装")
        requested = args.host
        if isinstance(requested, str):
            requested = [requested]
        if requested:
            hosts = list(dict.fromkeys(requested))
        else:
            found = {name: bool(shutil.which(getattr(args, name, None) or name)) for name, _, _ in HOSTS}
            if not any(found.values()):
                self.warn("No supported host CLI (codex, claude, pi, dsh) was found on PATH.",
                          "PATH 中未找到任何受支持的宿主 CLI（codex、claude、pi、dsh）。")
                raise ValueError("No host CLI found; install Codex, Claude Code, Pi or DSH, "
                                 "or pass --codex/--claude/--pi/--dsh PATH to point at its executable")
            hints = {name: ("", None) if found[name] else ("CLI not found", "未找到 CLI") for name in found}
            if found["dsh"] and not shutil.which("pnpm"):
                # dsh plugin forwards to pnpm; offering DSH without it only fails later.
                found["dsh"], hints["dsh"] = False, ("needs pnpm: npm install -g pnpm", "需要 pnpm：npm install -g pnpm")
            hosts = self.multiselect("Install into which hosts?", "安装到哪些宿主？", [
                Option(name, en, zh, *hints[name], disabled=not found[name]) for name, en, zh in HOSTS],
                [name for name, _, _ in HOSTS if found[name]])
        targets = []
        for host in hosts:
            label = next((en for name, en, _ in HOSTS if name == host), host)
            target = {"host": host, "scope": None, "project": None, "profile": None}
            if host in ("claude", "pi"):
                scope = args.scope
                if scope is None:
                    options = [Option("user", "This user", "当前用户"), Option("project", "This project", "指定项目")]
                    if host == "claude":
                        options.append(Option("local", "This project, only for me", "指定项目（仅自己）"))
                    scope = self.select(label + ": installation scope", label + "：安装范围", options, "user")
                target["scope"] = scope
                if scope in ("project", "local"):
                    target["project"] = args.project or self.input(
                        label + ": project directory", label + "：项目目录", str(Path.cwd()), _directory_problem)
            elif host == "dsh":
                # Never guess a DSH profile: it selects a distinct composed runtime.
                target["profile"] = args.profile or self.input(
                    "DSH profile name (for example web)", "DSH profile 名称（例如 web）", "", _profile_problem)
            targets.append(target)
        lines = []
        for target in targets:
            label = next((en for name, en, _ in HOSTS if name == target["host"]), target["host"])
            detail = ", ".join(key + "=" + target[key] for key in ("scope", "project", "profile") if target[key])
            lines.append((label + (": " + detail if detail else ""), label + ("：" + detail if detail else "")))
        self.note("Installation plan", "安装计划", lines)
        if not self.confirm("Install now?", "现在安装？", True):
            raise KeyboardInterrupt
        first = targets[0]
        args.host, args.scope, args.project, args.profile = first["host"], first["scope"], first["project"], first["profile"]
        return targets

    def install_target(self, args):
        return self.install_targets(args)[0]


class Onboarding:
    def __init__(self, settings=None, console=None):
        self.settings = settings if settings is not None else Settings()
        self.console = console
        self.credentials = Credentials(self.settings)

    def _preferences(self):
        console, current = self.console, self.settings.load()
        console.step("Research preferences (Enter keeps the highlighted value)", "研究偏好（回车保留当前选项）")
        depth = console.select("Default research depth", "默认研究深度", [
            Option("auto", "Auto", "自动", "choose from the question", "根据问题自动选择"),
            Option("quick", "Quick", "快速", "quick source check", "快速查证"),
            Option("agentic", "Agentic", "多轮", "iterative search and reading", "多轮搜索与阅读"),
            Option("deep", "Deep", "深度", "deep research with retained evidence", "保留证据的深度研究")],
            current["research"]["depth"])
        language = console.select("Answer and report language", "答复和报告语言", [
            Option("auto", "Follow the question", "跟随提问语言"), Option("zh", "Chinese", "中文"),
            Option("en", "English", "英文")], current["research"]["response_language"])
        hints = {"exa": ("Exa search and reading", "Exa 搜索与阅读"), "parallel": ("Parallel search and extract", "Parallel 搜索与提取"),
                 "tavily": ("Tavily search and extract", "Tavily 搜索与提取"),
                 "jina": ("Jina Reader; search needs a key", "Jina Reader；搜索需要密钥")}
        def options(names=Settings.PROVIDERS):
            return [Option(name, name, name, *hints.get(name, ("", None))) for name in names]
        providers = console.multiselect("Primary search providers (run concurrently)", "主要搜索服务（并发查询）",
                                        options(), current["search"]["providers"])
        fallbacks = console.multiselect("Fallback search providers (used when primaries return nothing)",
                                        "备用搜索服务（主要服务无结果时使用）", options(),
                                        current["search"]["fallback_providers"], required=False)
        existing = Settings.fetch_providers(current)
        primary = console.select("Primary page reader", "首选正文读取服务", options(), existing[0] if existing else None)
        rest = [name for name in Settings.PROVIDERS if name != primary]
        extra = console.multiselect("Fallback page readers", "备用正文读取服务", options(rest),
                                    [name for name in existing if name != primary], required=False)
        extra_ordered = [name for name in existing if name in extra] + [name for name in extra if name not in existing]
        readers = [primary] + extra_ordered
        archive = console.confirm("Archive ordinary page reads? Research task evidence is always retained.",
                                  "自动归档普通网页读取？研究任务的证据始终保留。", current["archive"]["enabled"])
        directory = current["archive"]["directory"]
        if archive:
            def check(value):
                try:
                    Settings.external_path(value, "Archive directory")
                except ValueError:
                    return ("Use an absolute directory outside plugins and canvas packages.", "请使用插件与画布包以外的绝对目录。")
                return None
            directory = console.input("Archive directory", "归档目录", directory, check)
        mode = console.select("Check availability before web research", "联网研究前的可用性检查", [
            Option("cached", "Cached", "缓存", "refresh on first use, changes or expiry (15 minutes by default)", "首次、配置变化或过期时检查（默认 15 分钟）"),
            Option("always", "Always", "总是", "check for every new research question", "每次开始研究问题时检查"),
            Option("manual", "Manual", "手动", "only when explicitly requested", "仅手动检查")], current["readiness"]["mode"])
        config = current["professional_research"]
        service = console.select("Optional professional API (host-led research works without it)",
                                 "可选专业研究 API（宿主主导的研究不需要它）", [
            Option("none", "Disabled", "关闭", "keep professional APIs disabled", "关闭专业研究 API"),
            Option("per_task", "Per task", "按任务选择", "enable APIs; choose the provider per task", "启用 API，每次任务再选服务"),
            Option("openai", "OpenAI Deep Research", "OpenAI Deep Research"),
            Option("parallel", "Parallel Task API", "Parallel Task API")],
            (config["provider"] or "per_task") if config["enabled"] else "none")
        services = {"enabled": service != "none", "provider": service if service in ("openai", "parallel") else None}
        if service == "openai":
            model = console.select("OpenAI research model", "OpenAI 研究模型", [
                Option("o4-mini-deep-research", "o4-mini-deep-research"),
                Option("o3-deep-research", "o3-deep-research")], config["openai"]["model"])
            value = console.input("Maximum tool calls per run (not a monetary cap)", "每次任务最多工具调用数（不是金额上限）",
                                  str(config["openai"]["max_tool_calls"]),
                                  lambda value: None if value.isdigit() and 1 <= int(value) <= 1000
                                  else ("Enter a number from 1 to 1000.", "请输入 1 到 1000 的整数。"))
            services["openai"] = {"model": model, "max_tool_calls": int(value)}
        elif service == "parallel":
            console.say("Parallel processor remains " + config["parallel"]["processor"] + "; change it with config set if needed.",
                        "Parallel processor 沿用 " + config["parallel"]["processor"] + "；可通过 config set 修改。")
        return {"research": {"depth": depth, "response_language": language}, "search": {"providers": providers, "fallback_providers": fallbacks},
                "fetch": {"provider": readers[0], "providers": readers},
                "archive": {"enabled": archive, "directory": directory}, "readiness": {"mode": mode}, "professional_research": services}

    def _keys(self, defaults=()):
        console = self.console
        console.note("API keys", "API 密钥", [
            ("Retrieval adapters are included; anonymous search/reading works where the provider permits it.",
             "检索适配器已包含在插件中；服务方允许时可使用匿名搜索和阅读。"),
            ("Host MCP OAuth login stays in the host. An OpenAI API key is separate from a ChatGPT/Codex login.",
             "宿主 MCP 的 OAuth 登录由宿主管理；OpenAI API Key 与 ChatGPT/Codex 登录分开。"),
            ("Keys are hidden and saved in a local, unencrypted file readable only by your user: " + str(self.credentials.path),
             "密钥隐藏输入，并保存为仅当前用户可读的本地明文文件：" + str(self.credentials.path)),
            ("Environment variables override saved keys. Select nothing to configure credentials later.",
             "环境变量优先于保存的密钥；不选择即可稍后配置。"),
            ("Guidance: exa.ai/docs/reference/exa-mcp · docs.parallel.ai · docs.tavily.com · jina.ai/reader · platform.openai.com/api-keys",
             "说明：exa.ai/docs/reference/exa-mcp · docs.parallel.ai · docs.tavily.com · jina.ai/reader · platform.openai.com/api-keys")])
        status = {"environment": ("set in environment (overrides saved key)", "环境变量已设置（优先于保存的密钥）"),
                  "private_file": ("configured, not yet verified", "已配置，尚未验证"), None: ("missing", "未配置")}
        options = [Option(row["name"], row["name"].split("_")[0].lower(), None, *status[row["source"] if row["configured"] else None], hint_always=True)
                   for row in self.credentials.describe()["credentials"]]
        names = console.multiselect("Keys to add or replace", "新增或替换哪些密钥", options, defaults, required=False)
        for name in names:
            while True:
                value = console.password(name + " (hidden; blank skips)", name + "（隐藏输入；留空跳过）")
                if not value:
                    break
                try:
                    result = self.credentials.save(name, value)
                except ValueError as error:
                    console.error(str(error), "密钥或文件不符合要求，请检查输入及文件权限。")
                    continue
                console.success(name + " saved.", name + " 已保存。")
                if result["environment_takes_precedence"]:
                    console.warn("The current environment still overrides this value.", "当前环境变量仍会覆盖此值。")
                break

    def _integrations(self, readiness):
        console = self.console
        integrations = readiness["host_integrations"]
        console.say("\nOptional host research MCPs are separate from the included search/read adapters.",
                    "\n宿主原生研究 MCP 是可选功能，与已包含的搜索／阅读适配器分开。")
        console.say("Their login must be checked in the host session. A missing optional MCP does not prevent ordinary or deep host-led research.",
                    "这些 MCP 的登录状态需在宿主会话中检查；缺少可选 MCP 不影响宿主自己搜索、阅读或深度研究。")
        labels = {"needs_host_session": "待宿主会话检查", "observed": "会话工具可见，授权待验证", "not_observed": "当前会话未发现"}
        for row in integrations["native_research_mcps"]:
            console.say(row["provider"] + ": " + row["status"], row["provider"] + "：" + labels[row["status"]])
        selected = console.select("Show connection and login steps for an optional research MCP?",
                                  "查看哪个可选研究 MCP 的接入与授权步骤？", [
            Option("none", "Continue with the included adapters", "继续使用已包含的适配器"),
            Option("exa", "Exa Agent"), Option("parallel", "Parallel Task MCP"),
            Option("tavily", "Tavily Research")], "none")
        if selected != "none":
            row = next(row for row in integrations["native_research_mcps"] if row["provider"] == selected)
            setup = row["setup"]
            console.say("Inspect existing registrations first. Reuse an existing server name; run the add command only if absent.",
                        "先查看已有登记，复用现有服务名；确认未添加时才执行添加命令。")
            for field in ("inspect_command", "add_command", "login_command"):
                if field in setup:
                    console.say("  " + shlex.join(setup[field]), "  " + shlex.join(setup[field]))
            if "mcp_config" in setup:
                rendered = json.dumps(setup["mcp_config"], ensure_ascii=False)
                console.say(rendered, rendered)
                console.say("Use " + setup["credential_env"] + " through " + setup["credential_header"] + " in the profile's headers.",
                            "在 profile 的 headers 中通过 " + setup["credential_header"] + " 引用环境变量 " + setup["credential_env"] + "。")
            console.say(setup["login_instruction"], {
                "codex": "在支持 OAuth 的服务上运行 login，随后新建会话并用 /mcp 检查。使用已有登记时，将命令中的服务名换成实际名称。",
                "claude_code": "在 Claude Code 中打开 /mcp 并按提示授权；添加命令的 scope 应与目标用户或项目对应。",
                "dsh": "在所选 profile 中配置环境变量引用的认证 header；官方桥接器的 OAuth 支持尚未确认。",
                "pi": "Pi 基础研究使用同包 CLI；原生研究 MCP 需自行选择 MCP 扩展并在扩展中授权。",
                "unknown": "重新运行 setup --host 指定实际宿主，或打开宿主的 MCP 设置。",
            }[integrations["host"]])
            console.say("Provider: " + row["docs"] + "\nHost: " + setup["reference"],
                        "服务说明：" + row["docs"] + "\n宿主说明：" + setup["reference"])
            console.say("These steps were displayed, not executed. Saved plugin API keys do not automatically authenticate a separate host MCP.",
                        "以上步骤仅展示，尚未执行。插件保存的 API Key 不会自动授权另行添加的宿主 MCP。")

    LABELS = {"unchecked": "尚未检查", "catalog_reachable": "工具目录可达，实际调用待验证",
              "http_unchecked": "HTTP 接口待实际调用验证", "retrieval_verified": "实际检索已通过（按操作查看结果）",
              "model_access_verified": "模型查询授权已通过，研究任务未测试",
              "task_mcp_access_verified": "Task MCP 授权已通过，Task API 未测试",
              "disabled": "未启用（可选）", "missing_credentials": "缺少密钥", "failed": "检查失败"}
    FAILED = ("failed", "missing_credentials")
    WARNING = ("unchecked", "disabled", "http_unchecked")

    def _check(self, checks, test_retrieval, host, observed_tools):
        def run():
            return Readiness(settings=self.settings).check(refresh=checks, offline=not checks,
                test_retrieval=test_retrieval, host=host, observed_tools=observed_tools)
        if not self.console:
            return run()
        with self.console.spinner("Checking configuration and selected services…", "正在检查配置与所选服务……"):
            readiness = run()
        for row in readiness["checks"]:
            english = row["id"] + ": " + row["status"]
            chinese = row["id"] + "：" + self.LABELS.get(row["status"], row["status"])
            if row["status"] in self.FAILED:
                self.console.error(english, chinese)
                self.console.say("  " + row["next_step"] + " " + row["docs"],
                                 "  检查密钥、权限和连接后重新运行 setup；服务文档：" + row["docs"])
            elif row["status"] in self.WARNING:
                self.console.warn(english, chinese)
            else:
                self.console.success(english, chinese)
        return readiness

    def run(self, preferences=None, checks=True, test_retrieval=False, host="unknown", observed_tools=None):
        if not checks and test_retrieval:
            raise ValueError("--test-retrieval cannot be used with --skip-checks")
        if preferences is not None:
            self.settings.update(preferences)
        console = self.console
        if console:
            console.intro("Bookmark Research setup", "Bookmark Research 配置")
            self.settings.update(self._preferences())
            self._keys()
            if checks and not test_retrieval:
                test_retrieval = console.confirm(
                    "Also test retrieval? Each provider gets one search and one example.com read; provider quota may be used.",
                    "同时进行实际检索自检？每家服务一次搜索和一次 example.com 阅读，可能使用服务额度。", False)
        readiness = self._check(checks, test_retrieval, host, observed_tools)
        if console and checks:
            failed = [row for row in readiness["checks"] if row["status"] in self.FAILED]
            if failed and console.confirm("Re-enter keys for failed services?", "为失败的服务重新输入密钥？", False):
                names = []
                for row in failed:
                    provider = row["id"].split(":")[-1].upper() + "_API_KEY"
                    if provider in Credentials.NAMES and provider not in names:
                        names.append(provider)
                self._keys(names)
                readiness = self._check(checks, test_retrieval, host, observed_tools)
        result = {"settings": self.settings.describe(), "credentials": self.credentials.describe(), "readiness": readiness,
                  "needs_attention": [row["id"] for row in readiness["checks"] if row["status"] in self.FAILED],
                  "next_step": "Start a new host session and call research_readiness with the actually observed host tools. Rerun setup to change preferences or credentials."}
        if console:
            self._integrations(readiness)
            console.outro("Setup saved. Optional MCP login must be checked in a new host session. No research job was started.",
                          "设置已保存。可选 MCP 的登录状态需在新宿主会话中确认；本次没有启动研究任务。")
        return result
