"""Human CLI setup and the equivalent JSON-driven agent path."""

from contextlib import contextmanager
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from credentials import Credentials
from dsh_client import profiles as dsh_profiles
from dsh_client import resolve as resolve_dsh
from readiness import Readiness
from settings import Settings
from tui import Option, Prompter


HOSTS = (("codex", "Codex", "Codex"), ("claude", "Claude Code", "Claude Code"),
         ("dsh", "DeepSeek Harness (dsh)", "DeepSeek Harness (dsh)"))


def _profile_problem(value):
    if not value or value.startswith(".") or not all(char.isalnum() or char in "._-" for char in value):
        return ("Use letters, numbers, dots, underscores or hyphens; do not start with a dot.",
                "仅可使用字母、数字、点、下划线或连字符，且不能以点开头。")
    return None


def _dsh_hint(client):
    """Why DSH is unavailable, or which carrier the wizard selected for it."""
    if client["usable"]:
        if client["source"] == "desktop":
            return ("DeepSeek Harness Desktop CLI", "DeepSeek Harness 桌面版 CLI")
        return ("", None)
    if client["reason"] == "pnpm":
        return ("needs pnpm: npm install -g pnpm, or corepack enable pnpm; the DeepSeek Harness Desktop CLI carries its own",
                "需要 pnpm：npm install -g pnpm 或 corepack enable pnpm；DeepSeek Harness 桌面版 CLI 自带 pnpm")
    return ("needs the dsh CLI: pass --dsh PATH (DeepSeek Harness Desktop keeps one under its app resources)",
            "需要 dsh CLI：请用 --dsh PATH 指定（DeepSeek Harness 桌面版的 CLI 位于其应用资源目录）")


def _profile_hint(row):
    """What an initialized DSH profile already holds for this plugin."""
    if not row["initialized"]:
        return ("package.json is missing or unreadable", "package.json 缺失或无法读取")
    if row["dependency"]:
        return ("bookmark-research " + row["dependency"] + (" · enabled" if row["enabled"] else " · not enabled"),
                "已装 bookmark-research " + row["dependency"] + (" · 已启用" if row["enabled"] else " · 未启用"))
    return ("no bookmark-research yet", "尚未安装 bookmark-research")


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
        # Resolve the DSH carrier once, so the plan and the installation agree on
        # which `dsh` runs: a generic CLI needs pnpm on PATH, while the DeepSeek
        # Harness Desktop CLI bundles its own.
        client = resolve_dsh(getattr(args, "dsh", None))
        if client["source"] == "desktop":
            args.dsh = client["binary"]
        if requested:
            hosts = list(dict.fromkeys(requested))
        else:
            found = {name: bool(shutil.which(getattr(args, name, None) or name)) for name, _, _ in HOSTS}
            hints = {name: ("", None) if found[name] else ("CLI not found", "未找到 CLI") for name in found}
            found["dsh"], hints["dsh"] = client["usable"], _dsh_hint(client)
            if not any(found.values()):
                self.warn("No supported host CLI (codex, claude, dsh) was found on PATH.",
                          "PATH 中未找到任何受支持的宿主 CLI（codex、claude、dsh）。")
                raise ValueError("No host CLI found; install Codex, Claude Code or DeepSeek Harness (dsh), "
                                 "or pass --codex/--claude/--dsh PATH to point at its executable")
            hosts = self.multiselect("Install into which hosts?", "安装到哪些宿主？", [
                Option(name, en, zh, *hints[name], disabled=not found[name]) for name, en, zh in HOSTS],
                [name for name, _, _ in HOSTS if found[name]])
        # A carrier that ships its own pnpm is the Desktop CLI, however it was found:
        # only that CLI may manage the profile name Desktop reserves for itself.
        desktop = client["bundled_pnpm"] is not None
        targets = []
        for host in hosts:
            label = next((en for name, en, _ in HOSTS if name == host), host)
            target = {"host": host, "scope": None, "project": None, "profile": None}
            if host == "claude":
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
                target["profile"] = args.profile or self.dsh_profile(desktop)
            targets.append(target)
        lines = []
        for target in targets:
            label = next((en for name, en, _ in HOSTS if name == target["host"]), target["host"])
            detail = ", ".join(key + "=" + target[key] for key in ("scope", "project", "profile") if target[key])
            lines.append((label + (": " + detail if detail else ""), label + ("：" + detail if detail else "")))
        self.note("Installation plan", "安装计划", lines)
        if client["source"] == "desktop" and any(target["host"] == "dsh" for target in targets):
            self.note("DeepSeek Harness (dsh) CLI", "DeepSeek Harness (dsh) CLI", [(client["binary"], client["binary"])])
        if not self.confirm("Install now?", "现在安装？", True):
            raise KeyboardInterrupt
        first = targets[0]
        args.host, args.scope, args.project, args.profile = first["host"], first["scope"], first["project"], first["profile"]
        return targets

    def dsh_profile(self, desktop):
        """Choose an initialized DSH profile, or name a new one.

        `dsh plugin` initializes a profile on first use, so the profiles on disk
        are the real targets; each is annotated with this plugin's recorded source
        and whether its bundle list activates it. The reserved `desktop` profile
        is composed only by the Desktop CLI, so another carrier never offers it.
        """
        check = self._profile(desktop)
        question = ("DeepSeek Harness (dsh) profile name (for example web)", "DeepSeek Harness (dsh) profile 名称（例如 web）")
        rows = dsh_profiles()
        if not desktop:
            rows = [row for row in rows if row["name"].casefold() != "desktop"]
        if not rows:
            return self.input(question[0], question[1], "desktop" if desktop else "", check)
        options = [Option(row["name"], row["name"], row["name"], *_profile_hint(row)) for row in rows]
        options.append(Option("", "Another profile name…", "其他 profile 名称…"))
        default = "desktop" if any(row["name"] == "desktop" for row in rows) else None
        chosen = self.select("Install into which DeepSeek Harness (dsh) profile?", "安装到哪个 DeepSeek Harness (dsh) profile？", options, default)
        if chosen:
            return chosen
        return self.input(question[0], question[1], "desktop" if desktop else "", check)

    @staticmethod
    def _profile(desktop):
        """Validate a DSH profile name, rejecting the reserved name for a generic CLI."""
        def check(value):
            problem = _profile_problem(value)
            if problem:
                return problem
            if value.casefold() == "desktop" and not desktop:
                return ("desktop is composed only by the DeepSeek Harness Desktop CLI: choose another profile name, "
                        "or rerun with --dsh",
                        "desktop 只能由 DeepSeek Harness 桌面版 CLI 组装：请换一个 profile 名称，或用 --dsh 重新运行")
            return None
        return check

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
        depth = console.select("Default research depth (optional; Auto is usually right)",
                               "默认研究深度（可选；通常保持「自动」即可）", [
            Option("auto", "Auto", "自动", "follow each request: lookup, investigation or batch", "按每次请求自动选择：查证、调查或整包"),
            Option("quick", "Quick", "快速", "quick source check", "快速查证"),
            Option("agentic", "Agentic", "多轮", "iterative search and reading", "多轮搜索与阅读"),
            Option("deep", "Deep", "深度", "deep research with retained evidence", "保留证据的深度研究")],
            current["research"]["depth"])
        language = console.select("Answer and report language", "答复和报告语言", [
            Option("auto", "Follow the question", "跟随提问语言"), Option("zh", "Chinese", "中文"),
            Option("en", "English", "英文")], current["research"]["response_language"])
        hints = {"exa": ("Exa search and reading", "Exa 搜索与阅读"), "parallel": ("Parallel search and extract", "Parallel 搜索与提取"),
                 "tavily": ("Tavily search and extract", "Tavily 搜索与提取"),
                 "jina": ("Jina Reader; search needs a key", "Jina Reader；搜索需要密钥"),
                 "deepseek": ("DeepSeek Search / Fetch; needs a key", "DeepSeek 搜索／读取；需要密钥")}
        # One ordered list answers the former search, fallback-search and reader
        # questions: selected providers run concurrently and also read pages,
        # unselected providers stay as the fallback search tier.
        options = [Option(name, name, name, *hints.get(name, ("", None))) for name in Settings.PROVIDERS]
        primary = console.multiselect("Search and page-reading services (concurrent, in this order)",
                                      "搜索与正文读取服务（并发执行，按此顺序）", options, current["search"]["providers"])
        providers = list(primary)
        fallbacks = [name for name in Settings.PROVIDERS if name not in providers]
        storage = self._storage(current)
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
        # Only changed values are returned, so an unchanged answer keeps the saved
        # Wiki follow-up, readiness policy and archive toggle exactly as they were.
        result = {"research": {"depth": depth, "response_language": language},
                  "search": {"providers": providers, "fallback_providers": fallbacks},
                  "fetch": {"provider": providers[0], "providers": providers},
                  "professional_research": services}
        result.update(storage)
        return result

    def _storage(self, current):
        """Ask once where archives and research results live, and return only the changed keys."""
        console, defaults = self.console, Settings.defaults()
        archive_dir, output_dir = current["archive"]["directory"], current["output"]["directory"]
        beside = current["output"]["mode"] == "beside_input"
        console.say("Location changes apply to new research tasks only; existing tasks stay where they are.",
                    "位置设置只影响新的研究任务；已有任务保留在原处。")
        choice = console.select("Where should archives and research reports be stored?",
                                "归档和研究报告保存在哪里？", [
            Option("default", "Default data folder", "默认数据目录",
                   archive_dir + " · " + output_dir, archive_dir + " · " + output_dir, hint_always=True),
            Option("custom", "One custom folder for both (knowledge/ and research/)", "自定义统一目录（其下 knowledge/ 与 research/）"),
            Option("beside_input", "Research reports beside the bookmark file or folder", "研究报告放在书签文件或文件夹旁边",
                   "falls back to the central folder when not possible", "无法放置时退回统一目录", hint_always=True)],
            "beside_input" if beside else "default")
        if choice == "custom":
            def check(value):
                try:
                    Settings.external_path(value, "Storage directory")
                except ValueError:
                    return ("Use an absolute directory outside plugins and canvas packages.", "请使用插件与画布包以外的绝对目录。")
                return None
            root = Settings.external_path(console.input("Storage directory", "存放目录",
                                                        str(Path(archive_dir).parent), check), "Storage directory")
            return {"archive": {"directory": str(root / "knowledge")},
                    "output": {"mode": "central", "directory": str(root / "research")}}
        if choice == "beside_input":
            return {"output": {"mode": "beside_input"}} if not beside else {}
        # Default folder: reset only a previously customised location.
        result = {}
        if archive_dir != defaults["archive"]["directory"]:
            result["archive"] = {"directory": defaults["archive"]["directory"]}
        if beside or output_dir != defaults["output"]["directory"]:
            result["output"] = {"mode": "central", "directory": defaults["output"]["directory"]}
        return result

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
