#!/usr/bin/env python3
"""CLI shared by the Skill, native harness adapters, and stdio MCP."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from bookmark_index import BookmarkIndex
from search_results import fuse_results
from settings import Settings


def _database(value):
    if value:
        path = Path(value).expanduser().resolve()
    else:
        path = Settings.data_directory() / "index.sqlite3"
    plugin_root = Path(__file__).resolve().parent.parent
    if path == plugin_root or plugin_root in path.parents:
        raise ValueError("Keep the database outside the plugin directory; pass --db or BOOKMARK_RESEARCH_DATA_DIR")
    return path


def _read_json(path):
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def _checked_input(path, tool, extra=None):
    from mcp_server import TOOL_SCHEMAS, RpcError, _validate
    value = _read_json(path)
    if not isinstance(value, dict):
        raise ValueError("Input must be a JSON object")
    extra = extra or {}
    if set(extra) & set(value):
        raise ValueError("Positional identifiers must not be repeated in the input file")
    value = {**value, **extra}
    try:
        _validate(TOOL_SCHEMAS[tool], value)
    except RpcError as error:
        raise ValueError(str(error)) from None
    return value


def _parser():
    parser = argparse.ArgumentParser(description="Bookmark Canvas queries and aggregated web research")
    parser.add_argument("--db", help="Persistent SQLite file outside the original package and plugin")
    parser.add_argument("--config", help="User settings JSON file; otherwise BOOKMARK_RESEARCH_CONFIG or XDG_CONFIG_HOME")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check local runtime; does not access the network")
    config = commands.add_parser("config", help="View or update persistent user preferences")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("show")
    configure = config_commands.add_parser("set")
    configure.add_argument("--input", help="Partial settings JSON file, or '-' for stdin")
    configure.add_argument("--archive", choices=("true", "false"))
    configure.add_argument("--archive-dir")
    configure.add_argument("--search-provider", action="append", choices=Settings.PROVIDERS)
    configure.add_argument("--search-fallback-provider", action="append", choices=Settings.PROVIDERS)
    configure.add_argument("--fetch-provider", choices=Settings.PROVIDERS)
    configure.add_argument("--fetch-fallback-provider", action="append", choices=Settings.PROVIDERS)
    configure.add_argument("--max-characters", type=int)
    sync = commands.add_parser("sync", help="Import a directory, ZIP, or single card; keep a reusable snapshot")
    sync.add_argument("package")
    sync.add_argument("--source-id")
    sync.add_argument("--mode", choices=("snapshot", "live"), help="New exports default to snapshot; Git directories to live; existing sources retain their mode")
    sync.add_argument("--completeness", choices=("partial", "complete"), help="partial retains absent cards; complete reconciles a full directory")
    status = commands.add_parser("status")
    status.add_argument("source", nargs="?")
    history = commands.add_parser("history", help="List reusable source snapshot versions")
    history.add_argument("source")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--offset", type=int, default=0)
    watch = commands.add_parser("watch", help="Monitor live sources in this foreground process (MCP starts this automatically)")
    watch.add_argument("--interval", type=float, default=1.0)
    watch.add_argument("--debounce", type=float, default=2.0)
    watch.add_argument("--deletion-grace", type=float, default=5.0)
    search = commands.add_parser("search", help="Literal structured bookmark search")
    search.add_argument("source")
    search.add_argument("--target", action="append", default=[])
    search.add_argument("--section")
    search.add_argument("--group")
    search.add_argument("--folder")
    search.add_argument("--tag", action="append", default=[])
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--no-refresh", action="store_true", help="Read the last synchronized index without refreshing")
    context = commands.add_parser("context")
    context.add_argument("source")
    context.add_argument("--section")
    context.add_argument("--group")
    context.add_argument("--item")
    context.add_argument("--no-refresh", action="store_true")
    providers = commands.add_parser("providers")
    providers.add_argument("--probe", action="store_true", help="Connect to selected official MCP endpoints")
    providers.add_argument("--provider", action="append")
    providers.add_argument("--timeout", type=int)
    web = commands.add_parser("search-web")
    web.add_argument("--input", help="JSON {targets:[{target,query}],providers?,limit_per_target?}; '-' for stdin")
    web.add_argument("--target", action="append", help="Use a string as both target label and query")
    web.add_argument("--provider", action="append")
    web.add_argument("--limit", type=int)
    web.add_argument("--timeout", type=int)
    fetch = commands.add_parser("fetch-web")
    fetch.add_argument("urls", nargs="+")
    fetch.add_argument("--provider", choices=Settings.PROVIDERS)
    fetch.add_argument("--timeout", type=int, help="Per provider HTTP request timeout; discovery and fallback can take longer overall")
    fetch.add_argument("--max-characters", type=int)
    fetch.add_argument("--raw", action="store_true", help="Return full provider envelopes instead of one selected text per URL")
    archival = fetch.add_mutually_exclusive_group()
    archival.add_argument("--archive", dest="archive", action="store_true", default=None)
    archival.add_argument("--no-archive", dest="archive", action="store_false")
    merge = commands.add_parser("merge-results", help="Fuse normalized batches from existing MCPs")
    merge.add_argument("input", help="JSON input file, or '-' for stdin")
    research = commands.add_parser("research", help="Durable host-led deep research, evidence and reports")
    research.add_argument("--directory", help="Research root outside source packages and plugin; default in the data directory")
    research_commands = research.add_subparsers(dest="research_command", required=True)
    begin = research_commands.add_parser("start", help="Save a brief, questions and budgets without contacting providers")
    begin.add_argument("--input", required=True, help="JSON {brief,questions:[{id,question}],urls? or source_ids?,budget?,providers?,scope?}")
    inspect = research_commands.add_parser("status", help="List sessions or inspect progress without network calls")
    inspect.add_argument("research_id", nargs="?")
    inspect.add_argument("--section", choices=("questions", "claims", "sources", "operations", "conflicts", "bookmark_context", "events", "inventory", "inventory_reviews", "external_runs"))
    inspect.add_argument("--offset", type=int, default=0)
    inspect.add_argument("--limit", type=int, default=20)
    for name in ("search", "fetch", "record", "import-evidence"):
        step = research_commands.add_parser(name)
        step.add_argument("research_id")
        step.add_argument("--input", required=True, help="Action JSON or '-' for stdin; research_id comes from the positional argument")
    source = research_commands.add_parser("source", help="Read and verify saved source text")
    source.add_argument("research_id")
    source.add_argument("source_id")
    source.add_argument("--offset", type=int, default=0)
    source.add_argument("--limit", type=int, default=12000)
    finish = research_commands.add_parser("finish", help="Validate evidence and write report.md plus sources.json")
    finish.add_argument("research_id")
    finish.add_argument("--summary", required=True)
    finish.add_argument("--status", choices=("completed", "incomplete", "cancelled"), default="completed")
    finish.add_argument("--limitation", action="append")
    for name in ("inventory", "coverage"):
        view = research_commands.add_parser(name, help="Read the frozen source scope or remaining evidence gaps")
        view.add_argument("research_id")
        view.add_argument("--offset", type=int, default=0)
        view.add_argument("--limit", type=int, default=100)
        if name == "inventory":
            view.add_argument("--inventory-id", action="append")
        else:
            view.add_argument("--filter", choices=("all", "missing", "unread", "unreviewed", "blocked", "excluded", "reviewed"))
    route = research_commands.add_parser("route", help="Select from observed host research capabilities; does not execute")
    route.add_argument("--input", help="JSON current host/tools/commands, or '-' for stdin")
    route.add_argument("--host", choices=("codex", "claude_code", "pi", "dsh", "unknown"), default="unknown")
    route.add_argument("--depth", choices=("auto", "quick", "agentic", "deep"))
    route.add_argument("--task-shape", choices=("lookup", "investigation", "batch_research"), default="investigation")
    route.add_argument("--tool", action="append")
    route.add_argument("--available-command", action="append")
    route.add_argument("--extension", action="append")
    route.add_argument("--failed-route", action="append")
    route.add_argument("--provider", choices=("openai", "parallel"))
    service = research_commands.add_parser("service", help="Prepare/start/observe existing professional research runs")
    service_commands = service.add_subparsers(dest="service_command", required=True)
    describe = service_commands.add_parser("describe")
    describe.add_argument("--provider", choices=("openai", "parallel"))
    for name in ("prepare", "start", "attach"):
        action = service_commands.add_parser(name)
        action.add_argument("--input", required=True, help="Explicit request JSON, including research_id")
    for name in ("status", "result", "cancel", "import"):
        action = service_commands.add_parser(name)
        action.add_argument("external_id")
        if name in ("status", "result"):
            action.add_argument("--refresh", action="store_true", help="Observe the same provider run once")
        if name == "result":
            action.add_argument("--offset", type=int, default=0)
            action.add_argument("--limit", type=int, default=12000)
        if name == "import":
            action.add_argument("--operation-id", required=True)
            action.add_argument("--question-id")
    wiki = commands.add_parser("wiki", help="Author and search evidence-linked knowledge outside source packages")
    wiki.add_argument("--directory")
    wiki.add_argument("--research-directory")
    wiki_commands = wiki.add_subparsers(dest="wiki_command", required=True)
    write = wiki_commands.add_parser("write")
    write.add_argument("page_id")
    write.add_argument("--input", required=True, help="JSON {page,change_note,expected_revision?}")
    get = wiki_commands.add_parser("get")
    get.add_argument("page_id")
    get.add_argument("--revision", type=int)
    lint = wiki_commands.add_parser("lint")
    lint.add_argument("--page-id")
    for name in ("list", "search"):
        view = wiki_commands.add_parser(name)
        if name == "search":
            view.add_argument("query")
        view.add_argument("--offset", type=int, default=0)
        view.add_argument("--limit", type=int, default=20)
    evaluation = commands.add_parser("evaluate", help="Compute research metrics from explicit benchmark outputs and judgments")
    evaluation.add_argument("--input", required=True, help="JSON {suite,runs,judgments?}; '-' for stdin")
    commands.add_parser("serve", help="Run the stdio MCP tool server")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        settings = Settings(args.config)
        if args.command == "serve":
            from mcp_server import serve
            serve(str(_database(args.db)), settings=settings)
            return 0
        if args.command == "watch":
            from source_watcher import SourceWatcher
            watcher = SourceWatcher(_database(args.db), interval=args.interval, debounce=args.debounce,
                deletion_grace=args.deletion_grace,
                on_change=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
            try:
                watcher.run()
            except KeyboardInterrupt:
                pass
            finally:
                watcher.close()
            if watcher.last_error:
                raise RuntimeError(watcher.last_error)
            return 0
        if args.command == "research":
            from research import ResearchSessions
            sessions = ResearchSessions(directory=args.directory, settings=settings, db_path=_database(args.db))
            action = args.research_command
            if action == "route":
                from routing import ResearchRouting
                payload = _checked_input(args.input, "research_route") if args.input else {
                    "host": args.host, "depth": args.depth, "task_shape": args.task_shape,
                    "observed_tools": args.tool, "available_commands": args.available_command,
                    "installed_extensions": args.extension, "provider": args.provider, "failed_routes": args.failed_route}
                result = ResearchRouting(settings).route(**payload)
            elif action == "service":
                from research_services import ResearchServices
                services = ResearchServices(settings=settings, research_sessions=sessions)
                service_action = args.service_command
                if service_action in ("prepare", "start", "attach"):
                    payload = _checked_input(args.input, "research_service_" + service_action)
                    result = getattr(services, service_action)(**payload)
                elif service_action == "describe":
                    result = services.describe(args.provider)
                elif service_action == "status":
                    result = services.status(args.external_id, args.refresh)
                elif service_action == "result":
                    result = services.result(args.external_id, args.refresh, args.offset, args.limit)
                elif service_action == "cancel":
                    result = services.cancel(args.external_id)
                else:
                    result = services.import_result(args.external_id, args.operation_id, args.question_id)
            elif action == "inventory":
                result = sessions.inventory(args.research_id, args.inventory_id, args.offset, args.limit)
            elif action == "coverage":
                result = sessions.coverage(args.research_id, args.filter, args.offset, args.limit)
            elif action == "import-evidence":
                result = sessions.import_evidence(**_checked_input(args.input, "research_import_evidence", {"research_id": args.research_id}))
            elif action in ("start", "search", "fetch", "record"):
                payload = _read_json(args.input)
                if not isinstance(payload, dict):
                    raise ValueError("Research input must be an object")
                allowed = {"start": {"brief", "questions", "budget", "providers", "scope", "source_ids", "bookmark_refs", "scope_mode", "inventory_ids", "urls"},
                           "search": {"operation_id", "queries", "providers", "limit_per_target"},
                           "fetch": {"operation_id", "question_id", "urls", "provider", "max_characters"}}
                required = {"start": {"brief", "questions"}, "search": {"operation_id", "queries"},
                            "fetch": {"operation_id", "question_id", "urls"}}
                if action != "record" and (set(payload) - allowed[action] or required[action] - set(payload)):
                    raise ValueError("Research input has missing or unknown fields for " + action)
                if action == "start":
                    result = sessions.start(**payload)
                elif action == "search":
                    result = sessions.search(args.research_id, **payload)
                elif action == "fetch":
                    result = sessions.fetch(args.research_id, **payload)
                elif "kind" in payload:
                    result = sessions.record(args.research_id, payload)
                else:
                    if set(payload) - {"entry", "entries", "batch_id"}:
                        raise ValueError("Research record input has unknown fields")
                    result = sessions.record(args.research_id, **payload)
            elif action == "status":
                result = sessions.status(args.research_id, args.section, args.offset, args.limit)
            elif action == "source":
                result = sessions.source(args.research_id, args.source_id, args.offset, args.limit)
            else:
                result = sessions.finish(args.research_id, args.summary, args.status, args.limitation)
        elif args.command == "wiki":
            from research import ResearchSessions
            from wiki import WikiStore
            sessions = ResearchSessions(directory=args.research_directory, settings=settings, db_path=_database(args.db))
            store = WikiStore(directory=args.directory, settings=settings, research_sessions=sessions)
            if args.wiki_command == "write":
                result = store.write(**_checked_input(args.input, "wiki_write", {"page_id": args.page_id}))
            elif args.wiki_command == "get":
                result = store.get(args.page_id, args.revision)
            elif args.wiki_command == "list":
                result = store.list(args.offset, args.limit)
            elif args.wiki_command == "search":
                result = store.search(args.query, args.offset, args.limit)
            else:
                result = store.lint(args.page_id)
        elif args.command == "evaluate":
            from evaluation import evaluate
            result = evaluate(**_checked_input(args.input, "evaluate_research"))
        elif args.command == "config":
            if args.config_command == "show":
                result = settings.describe()
            else:
                changes = _read_json(args.input) if args.input else {}
                if not isinstance(changes, dict):
                    raise ValueError("Settings input must be an object")
                for section, field, value in (
                        ("archive", "enabled", None if args.archive is None else args.archive == "true"),
                        ("archive", "directory", args.archive_dir),
                        ("search", "providers", args.search_provider),
                        ("search", "fallback_providers", args.search_fallback_provider),
                        ("fetch", "provider", args.fetch_provider),
                        ("fetch", "providers", args.fetch_fallback_provider),
                        ("fetch", "max_characters", args.max_characters)):
                    if value is not None:
                        if not isinstance(changes.get(section, {}), dict):
                            raise ValueError("Settings section must be an object: " + section)
                        changes.setdefault(section, {})[field] = value
                result = settings.update(changes)
        elif args.command == "doctor":
            connection = sqlite3.connect(":memory:")
            try:
                connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
                fts5 = True
            except sqlite3.OperationalError:
                fts5 = False
            finally:
                connection.close()
            result = {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
                      "fts5": fts5, "database": str(_database(args.db)),
                      "config_path": str(settings.path),
                      "database_created": False, "network_checked": False,
                      "dependencies": "Python standard library"}
        elif args.command in ("providers", "search-web", "fetch-web"):
            from web_search import SearchProviders
            engine = SearchProviders(timeout=args.timeout, settings=settings)
            if args.command == "providers":
                result = engine.probe(args.provider) if args.probe else engine.describe(args.provider)
            elif args.command == "fetch-web":
                result = engine.fetch(args.urls, args.provider, archive=args.archive, max_characters=args.max_characters)
                if not args.raw:
                    from archive import SourceArchive
                    result = SourceArchive.compact_fetch(result)
            else:
                payload = _read_json(args.input) if args.input else {
                    "targets": [{"target": q, "query": q} for q in (args.target or [])],
                    "providers": args.provider, "limit_per_target": args.limit}
                if not isinstance(payload, dict) or set(payload) - {"targets", "providers", "limit_per_target"}:
                    raise ValueError("Search input accepts targets, providers and limit_per_target only")
                result = engine.search(payload.get("targets"), args.provider if args.provider is not None else payload.get("providers"),
                                       args.limit if args.limit is not None else payload.get("limit_per_target"))
        elif args.command == "merge-results":
            result = fuse_results(_read_json(args.input))
        else:
            from source_manager import SourceManager
            with BookmarkIndex(str(_database(args.db))) as index:
                sources = SourceManager(index)
                if args.command == "sync":
                    result = sources.sync(args.package, args.source_id, mode=args.mode, completeness=args.completeness)
                elif args.command == "status":
                    result = sources.status(args.source)
                elif args.command == "history":
                    result = sources.history(args.source, limit=args.limit, offset=args.offset)
                else:
                    refresh = None if args.no_refresh else sources.refresh(args.source)
                    if refresh and refresh["state"] in ("error", "unavailable"):
                        raise ValueError(refresh["error"] + "; use --no-refresh to read the saved index")
                    with index.read_snapshot():
                        if args.command == "search":
                            result = index.search(args.source, targets=args.target, section=args.section,
                                                  group_id=args.group, folder_id=args.folder, tags=args.tag,
                                                  limit=args.limit, offset=args.offset)
                        else:
                            result = index.context(args.source, section=args.section, group_id=args.group,
                                                   item_id=args.item)
                        result["source"] = sources.status(args.source)["source"]
                    result["refresh"] = refresh
                    result["stored_snapshot_only"] = args.no_refresh
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "providers" and args.probe and result["successful_provider_count"] == 0:
            return 1
        if args.command == "search-web" and result.get("successful_provider_count") == 0:
            return 1
        if args.command == "fetch-web" and result.get("status") == "error":
            return 1
        if args.command == "research" and result.get("status") == "error":
            return 1
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
