#!/usr/bin/env python3
"""CLI shared by the Skill, native harness adapters, and stdio MCP."""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
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


def _writable_directory(path):
    """Report whether the nearest existing ancestor of ``path`` accepts a new file."""
    candidate = Path(path).expanduser()
    for parent in (candidate, *candidate.parents):
        try:
            if parent.is_dir():
                with tempfile.TemporaryFile(prefix=".bookmark-research-write-probe-", dir=parent):
                    pass
                return {"path": str(candidate), "checked": str(parent), "writable": True, "error": None}
            if parent.exists() or parent.is_symlink():
                return {"path": str(candidate), "checked": str(parent), "writable": False,
                        "error": "Existing path component is not a directory"}
        except OSError as error:
            return {"path": str(candidate), "checked": str(parent), "writable": False,
                    "error": error.strerror or str(error)}
    return {"path": str(candidate), "checked": None, "writable": False, "error": "no existing parent directory"}


def _storage_report(args, settings):
    """Preflight the two directories a first import needs to write."""
    database = _database(args.db)
    data = _writable_directory(database.parent)
    config = _writable_directory(settings.path.parent)
    existing = database.exists()
    database_writable = (not existing) or os.access(str(database), os.W_OK)
    ready = bool(data["writable"] and config["writable"] and database_writable)
    report = {"ready": ready, "data_directory": data, "config_directory": config,
              "database_exists": existing, "database_writable": database_writable}
    if not ready:
        suggestions = []
        if not data["writable"]:
            suggestions.append("export BOOKMARK_RESEARCH_DATA_DIR=<a writable directory>")
        if not config["writable"]:
            suggestions.append("export BOOKMARK_RESEARCH_CONFIG=<a writable settings.json path>")
        if not database_writable:
            suggestions.append("the existing database is read-only; move it or choose another data directory")
        report["next_step"] = "Cannot write where this command stores data. " + "; ".join(suggestions)
    return report


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
    setup = commands.add_parser("setup", help="Guided preferences, credentials and service checks")
    interaction = setup.add_mutually_exclusive_group()
    interaction.add_argument("--interactive", dest="interaction", action="store_const", const="always")
    interaction.add_argument("--non-interactive", dest="interaction", action="store_const", const="never")
    setup.set_defaults(interaction="auto")
    setup.add_argument("--lang", choices=("auto", "en", "zh"), default="auto")
    setup.add_argument("--input", help="Partial preferences JSON file, or '-' for stdin; never put API keys here")
    setup.add_argument("--skip-checks", action="store_true", help="Only inspect local configuration and existing cache")
    setup.add_argument("--test-retrieval", action="store_true", help="One search and sample page read per provider; uses retrieval quota")
    setup.add_argument("--host", choices=("codex", "claude_code", "dsh", "unknown"), default="unknown")
    setup.add_argument("--tool", action="append", help="Tool actually observed in the current host session; repeatable")
    readiness = commands.add_parser("readiness", help="Diagnose retrieval/auth availability; respects saved cache policy")
    readiness.add_argument("--provider", action="append", choices=Settings.PROVIDERS)
    readiness.add_argument("--service", choices=("openai", "parallel"))
    readiness.add_argument("--refresh", action="store_true")
    readiness.add_argument("--offline", action="store_true")
    readiness.add_argument("--test-retrieval", action="store_true", help="Also spend retrieval quota on a sample search/read")
    readiness.add_argument("--host", choices=("codex", "claude_code", "dsh", "unknown"), default="unknown")
    readiness.add_argument("--tool", action="append", help="Tool actually observed in the current host session; repeatable")
    config = commands.add_parser("config", help="View or update persistent user preferences")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("show")
    configure = config_commands.add_parser("set")
    configure.add_argument("--input", help="Partial settings JSON file, or '-' for stdin")
    configure.add_argument("--archive", choices=("true", "false"))
    configure.add_argument("--archive-dir")
    configure.add_argument("--search-provider", action="append", choices=Settings.PROVIDERS)
    configure.add_argument("--search-fallback-provider", action="append", choices=Settings.PROVIDERS)
    configure.add_argument("--search-strategy", choices=("hedged", "staggered", "sequential", "wait_all"))
    configure.add_argument("--fetch-strategy", choices=("sequential", "staggered", "hedged"))
    configure.add_argument("--fetch-provider", choices=Settings.FETCH_PROVIDERS)
    configure.add_argument("--fetch-fallback-provider", action="append", choices=Settings.FETCH_PROVIDERS)
    configure.add_argument("--depth", choices=("auto", "quick", "agentic", "deep"),
                           help="Default research depth; auto picks one from each request")
    configure.add_argument("--max-characters", type=int)
    configure.add_argument("--search-cache-seconds", type=int,
                           help="Serve repeated identical searches from a short-TTL cache; 0 disables (default)")
    configure.add_argument("--fetch-reuse-seconds", type=int,
                           help="Return saved text for URLs already fetched within this window; 0 disables (default)")
    configure.add_argument("--server-workers", type=int, help="Concurrent network requests (1-16, default 4; restart to apply)")
    configure.add_argument("--server-max-pending", type=int, help="Queued network calls (1-64, default 16; restart to apply)")
    configure.add_argument("--tool-scope-preset", choices=Settings.TOOL_SCOPE_PRESETS,
                           help="all, quick (everyday) or deep (full catalog)")
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
    source = commands.add_parser("source", help="Clean up duplicate or unwanted imported sources")
    source_commands = source.add_subparsers(dest="source_command", required=True)
    remove = source_commands.add_parser("remove", help="Delete a source, its indexed rows and its managed snapshots")
    remove.add_argument("source_id")
    remove.add_argument("--confirm", action="store_true", help="Required: perform the deletion (otherwise only reports it)")
    merge = source_commands.add_parser("merge", help="Drop a duplicate source whose content version matches another")
    merge.add_argument("source_id")
    merge.add_argument("into_source_id")
    merge.add_argument("--confirm", action="store_true", help="Required: perform the merge (otherwise only reports it)")
    watch = commands.add_parser("watch", help="Monitor live sources in this foreground process (MCP starts this automatically)")
    watch.add_argument("--interval", type=float, default=1.0)
    watch.add_argument("--debounce", type=float, default=2.0)
    watch.add_argument("--deletion-grace", type=float, default=5.0)
    watch.add_argument("--verify-hashes", action="store_true",
                       help="Always read and verify full byte hashes instead of pre-screening by mtime and size")
    search = commands.add_parser("search", help="Literal structured bookmark search")
    search.add_argument("source")
    search.add_argument("--compact", action="store_true", help="Return shared rows with ordered page references; preserve extra fields")
    search.add_argument("--target", action="append", default=[])
    search.add_argument("--section")
    search.add_argument("--group")
    search.add_argument("--folder")
    search.add_argument("--tag", action="append", default=[])
    search.add_argument("--tag-color", action="append", default=[], help="Only items carrying a tag of this color")
    search.add_argument("--item-type", action="append", choices=("bookmark", "folder"), default=[],
                        help="Restrict to bookmark and/or folder rows; default bookmark, use folder to enumerate folders")
    search.add_argument("--count-only", action="store_true", help="Return counts without result rows")
    search.add_argument("--score", action="store_true", help="Rank results by weighted score hints (title prefix, title contains, tag, note, path, url + temporal bonus)")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--no-refresh", action="store_true", help="Read the last synchronized index without refreshing")
    lookup_url = commands.add_parser("lookup-url", help="Reverse index: find all instances of a bookmark URL across sections and sources")
    lookup_url.add_argument("url")
    lookup_url.add_argument("--source-id")
    lookup_url.add_argument("--limit", type=int, default=100)
    lookup_url.add_argument("--offset", type=int, default=0)
    locate = commands.add_parser("locate", help="Locate Canvas bookmarks by text/URL or list a folder's direct children")
    locate.add_argument("--text")
    locate.add_argument("--url")
    locate.add_argument("--in", dest="in_sources", action="append", choices=("canvas", "wiki", "archive"),
                        help="Search one saved scope: Canvas bookmarks, Wiki revisions, or archive captures")
    locate.add_argument("--source-id")
    locate.add_argument("--section")
    locate.add_argument("--folder-id", help="Search within a folder, or with no text/URL list its direct children")
    locate.add_argument("--tag", dest="tags", action="append")
    locate.add_argument("--tag-color", dest="tag_colors", action="append")
    note_filter = locate.add_mutually_exclusive_group()
    note_filter.add_argument("--has-note", dest="has_note", action="store_true")
    note_filter.add_argument("--without-note", dest="has_note", action="store_false")
    locate.set_defaults(has_note=None)
    tags_filter = locate.add_mutually_exclusive_group()
    tags_filter.add_argument("--has-tags", dest="has_tags", action="store_true")
    tags_filter.add_argument("--without-tags", dest="has_tags", action="store_false")
    locate.set_defaults(has_tags=None)
    locate.add_argument("--metadata-match", choices=("all", "any"), default="all")
    locate.add_argument("--limit", type=int, default=8)
    locate.add_argument("--offset", type=int, default=0)
    locate.add_argument("--handle", help="Continue a previous locate response")
    refresh = locate.add_mutually_exclusive_group()
    refresh.add_argument("--refresh", dest="refresh", action="store_true")
    refresh.add_argument("--no-refresh", dest="refresh", action="store_false")
    locate.set_defaults(refresh=False)
    context = commands.add_parser("context")
    context.add_argument("source")
    context.add_argument("--section")
    context.add_argument("--group")
    context.add_argument("--item")
    context.add_argument("--no-refresh", action="store_true")
    context.add_argument("--collection", choices=("sections", "items", "nodes", "groups", "edges", "related_nodes", "memberships"))
    context.add_argument("--offset", type=int, default=0)
    context.add_argument("--limit", type=int, default=200, help="Rows per context collection")
    traverse = commands.add_parser("traverse", help="Multi-hop graph traversal along canvas edges and memberships")
    traverse.add_argument("source")
    traverse.add_argument("--section")
    traverse.add_argument("--group")
    traverse.add_argument("--item")
    traverse.add_argument("--node")
    traverse.add_argument("--depth", type=int, default=2)
    traverse.add_argument("--direction", choices=("all", "out", "in"), default="all")
    traverse.add_argument("--limit", type=int, default=100)
    traverse.add_argument("--offset", type=int, default=0)
    traverse.add_argument("--no-refresh", action="store_true")
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
    fetch.add_argument("--provider", choices=Settings.FETCH_PROVIDERS)
    fetch.add_argument("--timeout", type=int, help="Per provider HTTP request timeout; discovery and fallback can take longer overall")
    fetch.add_argument("--max-characters", type=int)
    fetch.add_argument("--max-total-characters", type=int, default=None)
    fetch.add_argument("--capture-id", help="Read a saved capture without a new network request")
    fetch.add_argument("--offset", type=int, default=0)
    fetch.add_argument("--raw", action="store_true", help="Return full provider envelopes instead of one selected text per URL")
    archival = fetch.add_mutually_exclusive_group()
    archival.add_argument("--archive", dest="archive", action="store_true", default=None)
    archival.add_argument("--no-archive", dest="archive", action="store_false")
    raw = commands.add_parser("search-archive", help="Literal full-text search over saved page text (knowledge archive and research evidence)")
    raw.add_argument("query")
    raw.add_argument("--limit", type=int, default=10)
    raw.add_argument("--offset", type=int, default=0)
    raw.add_argument("--url", help="Only bodies saved for a URL containing this substring")
    raw.add_argument("--occurrence-limit", type=int, default=50,
                     help="Occurrences listed per merged body (default 50); results report how to continue")
    raw.add_argument("--occurrence-offset", type=int, default=0, help="Continue a body's occurrence list here")
    merge = commands.add_parser("merge-results", help="Fuse normalized batches from existing MCPs")
    merge.add_argument("input", help="JSON input file, or '-' for stdin")
    merge.add_argument("--archive", action="store_true", help="Save merged extracts to knowledge archive")
    ingest = commands.add_parser("ingest", help="Fuse a search payload from a JSON file (no inline MCP size limit)")
    ingest.add_argument("input_path", nargs="?", help="JSON input file, or '-' for stdin")
    ingest.add_argument("--input", dest="input_option", help="JSON input file, or '-' for stdin")
    ingest.add_argument("--archive", action="store_true", help="Save merged extracts to knowledge archive")
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
    source.add_argument("source_id", nargs="?")
    source.add_argument("--source-id", action="append", dest="source_ids", metavar="SOURCE_ID",
                        help="Repeat to read up to 8 sources in one call")
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
    route.add_argument("--host", choices=("codex", "claude_code", "dsh", "unknown"), default="unknown")
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
        action.add_argument("--input", required=True, help="Request JSON; research_id is optional for standalone API runs")
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
    write.add_argument("--input", required=True, help="JSON {page,sources?,change_note,expected_revision?,reviewed_input_version?}")
    acknowledge = wiki_commands.add_parser("acknowledge",
                                           help="Re-record that a page's sources were reviewed at their current input version")
    acknowledge.add_argument("page_id")
    acknowledge.add_argument("--input", required=True, help="JSON {note,expected_revision?}")
    get = wiki_commands.add_parser("get")
    get.add_argument("page_id")
    get.add_argument("--revision", type=int)
    lint = wiki_commands.add_parser("lint")
    lint.add_argument("--page-id")
    work = wiki_commands.add_parser("work", help="Recover Wiki processing status and committed write receipts offline")
    work.add_argument("--kind", choices=("capture", "research", "page"))
    work.add_argument("--status", choices=("archived", "pending", "compiled", "needs_review"))
    work.add_argument("--research-id")
    work.add_argument("--page-id")
    work.add_argument("--capture-id")
    work.add_argument("--offset", type=int, default=0)
    work.add_argument("--limit", type=int, default=20)
    refresh = wiki_commands.add_parser("refresh", help="Capture cited webpages for review without rewriting the Wiki")
    refresh.add_argument("page_id")
    refresh.add_argument("--expected-revision", type=int)
    refresh.add_argument("--provider", choices=Settings.FETCH_PROVIDERS)
    refresh.add_argument("--max-characters", type=int)
    refresh.add_argument("--offset", type=int, default=0)
    refresh.add_argument("--limit", type=int, default=8)
    for name in ("list", "search"):
        view = wiki_commands.add_parser(name)
        if name == "search":
            view.add_argument("query")
        else:
            view.add_argument("--source-url", help="Filter direct citations and linked dependents")
        view.add_argument("--offset", type=int, default=0)
        view.add_argument("--limit", type=int, default=20)
    dupes = commands.add_parser("dupes", help="Report bookmarks whose URL appears more than once")
    dupes.add_argument("--source-id")
    dupes.add_argument("--min-count", type=int, default=2)
    dupes.add_argument("--limit", type=int, default=50)
    dupes.add_argument("--offset", type=int, default=0)
    dupes.add_argument("--include-search", action="store_true",
                       help="Include search-engine result pages (excluded by default)")
    job = commands.add_parser("job", help="Submit and observe durable local jobs")
    job_commands = job.add_subparsers(dest="job_command", required=True)
    submit = job_commands.add_parser("submit")
    submit.add_argument("--kind", choices=("fetch", "ingest", "research"), required=True)
    submit.add_argument("--input", required=True, help="Payload JSON file, or - for stdin")
    submit.add_argument("--idempotency-key")
    submit.add_argument("--priority", type=int, default=0)
    listing = job_commands.add_parser("list")
    listing.add_argument("--state", choices=("queued", "running", "succeeded", "failed", "cancelled"))
    listing.add_argument("--kind", choices=("fetch", "ingest", "research"))
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--offset", type=int, default=0)
    status = job_commands.add_parser("status")
    status.add_argument("job_id")
    result = job_commands.add_parser("result")
    result.add_argument("job_id")
    cancel = job_commands.add_parser("cancel")
    cancel.add_argument("job_id")
    worker = job_commands.add_parser("worker", help="Run the singleton job worker")
    worker.add_argument("--once", action="store_true", help="Claim and run at most one job")
    worker.add_argument("--max-jobs", type=int, default=None)
    worker.add_argument("--concurrency", type=int, default=2)
    worker.add_argument("--poll-seconds", type=float, default=0.5)
    worker.add_argument("--lease-seconds", type=float, default=120.0)
    commands.add_parser("serve", help="Run the stdio MCP tool server")
    bench = commands.add_parser("bench", help="Prepare reproducible host comparison artifacts")
    bench_commands = bench.add_subparsers(dest="bench_command", required=True)
    ladder = bench_commands.add_parser(
        "ladder", help="Create a 15-question host capture template; host traces are recorded separately")
    ladder.add_argument("--preset", choices=("legacy", "quick"), default="quick",
                        help="Record which advertised tool surface the host run must use")
    ladder.add_argument("--file", default=".bench/ladder.json", help="Template output path")
    ladder.add_argument("--force", action="store_true", help="Replace an existing ladder file")
    def add_output_options(command_parser):
        command_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON (the default format)")
        command_parser.add_argument("--fields", help="Project comma-separated dotted fields from object results")
        command_parser.add_argument("--out", help="Write the complete result to this file")
        command_parser.add_argument("--quiet", action="store_true", help="With --out, print only a compact write receipt")
        for action in command_parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    add_output_options(child)
    for command_parser in commands.choices.values():
        add_output_options(command_parser)
    return parser


def _project_fields(value, fields):
    if not fields:
        return value
    selected = {}
    for path in (part.strip() for part in fields.split(",")):
        if not path:
            continue
        current = value
        found = True
        for segment in path.split("."):
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            else:
                found = False
                break
        if found:
            selected[path] = current
    return selected


def _emit_result(result, args):
    projected = _project_fields(result, args.fields)
    rendered = json.dumps(projected, ensure_ascii=False, indent=None if args.json else 2,
                          separators=(",", ":") if args.json else None) + "\n"
    if args.out:
        destination = Path(args.out).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        if args.quiet:
            print(json.dumps({"written": str(destination), "characters": len(rendered.rstrip("\n"))},
                             ensure_ascii=False, separators=(",", ":") if args.json else None))
            return
    print(rendered, end="")


def main(argv=None):
    from textio import utf8_stdio
    utf8_stdio()
    args = _parser().parse_args(argv)
    try:
        settings = Settings(args.config)
        if args.command == "bench":
            destination = Path(args.file).expanduser()
            if destination.exists() and not args.force:
                raise ValueError("Ladder file already exists; choose --file or pass --force: " + str(destination))
            scripts_directory = Path(__file__).resolve().parent.parent / "scripts"
            sys.path.insert(0, str(scripts_directory))
            from evaluate_ladder import template as ladder_template
            from bench_tools_list import LEGACY_TOOLS
            from mcp_server import _legacy_compatibility_expired, release_version
            if args.preset == "legacy" and _legacy_compatibility_expired(release_version()):
                raise ValueError("The legacy ladder preset ended at 0.8.0")
            surface = "legacy-25" if args.preset == "legacy" else "quick-10"
            artifact = ladder_template()
            artifact["baseline_id"] = "2026-11-" + args.preset
            artifact["tool_surface"] = surface
            artifact["required_tool_scope"] = (list(LEGACY_TOOLS) if args.preset == "legacy"
                                                else list(Settings.QUICK_TOOLS))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = {"template": str(destination), "questions": 15, "tool_surface": surface,
                      "runs_required": 3, "host_traces_recorded": False}
            _emit_result(result, args)
            return 0
        elif args.command == "serve":
            from mcp_server import serve
            # Concurrency is read once at startup; an unreadable settings file
            # falls back to the conservative defaults instead of failing to serve.
            concurrency = {}
            try:
                server_section = settings.load()["server"]
                concurrency = {"workers": server_section["network_workers"],
                               "max_pending": server_section["max_pending_calls"]}
            except (ValueError, OSError) as error:
                sys.stderr.write("bookmark-research: using default server concurrency (%s)\n" % error)
            serve(str(_database(args.db)), settings=settings, **concurrency)
            return 0
        if args.command == "watch":
            from source_watcher import SourceWatcher
            watcher = SourceWatcher(_database(args.db), interval=args.interval, debounce=args.debounce,
                deletion_grace=args.deletion_grace, verify_hashes=args.verify_hashes,
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
        if args.command == "setup":
            from onboarding import Console, Onboarding
            if args.skip_checks and args.test_retrieval:
                raise ValueError("--test-retrieval cannot be used with --skip-checks")
            with Console.open(args.interaction, Console.resolve_language(args.lang)) as console:
                result = Onboarding(settings, console).run(_read_json(args.input) if args.input else None,
                    checks=not args.skip_checks, test_retrieval=args.test_retrieval, host=args.host, observed_tools=args.tool)
        elif args.command == "readiness":
            from readiness import Readiness
            result = Readiness(settings).check(providers=args.provider, service=args.service, refresh=args.refresh,
                offline=args.offline, test_retrieval=args.test_retrieval, host=args.host, observed_tools=args.tool)
        elif args.command == "research":
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
                allowed = {"start": {"brief", "questions", "budget", "providers", "scope", "source_ids", "bookmark_refs", "scope_mode", "inventory_ids", "urls", "output_directory"},
                           "search": {"operation_id", "queries", "providers", "limit_per_target"},
                           "fetch": {"operation_id", "question_id", "urls", "provider", "max_characters", "reuse_seconds"}}
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
                if args.source_ids:
                    result = sessions.source(args.research_id, source_ids=args.source_ids,
                                             offset=args.offset, limit=args.limit)
                elif args.source_id:
                    result = sessions.source(args.research_id, args.source_id, args.offset, args.limit)
                else:
                    raise ValueError("Provide source_id or --source-id")
            else:
                result = sessions.finish(args.research_id, args.summary, args.status, args.limitation)
        elif args.command == "wiki":
            from research import ResearchSessions
            from wiki import WikiStore
            sessions = ResearchSessions(directory=args.research_directory, settings=settings, db_path=_database(args.db))
            store = WikiStore(directory=args.directory, settings=settings, research_sessions=sessions)
            if args.wiki_command == "write":
                result = store.write(**_checked_input(args.input, "wiki_write", {"page_id": args.page_id}))
            elif args.wiki_command == "acknowledge":
                result = store.acknowledge(**_checked_input(args.input, "wiki_acknowledge", {"page_id": args.page_id}))
            elif args.wiki_command == "get":
                result = store.get(args.page_id, args.revision)
            elif args.wiki_command == "list":
                result = store.list(args.offset, args.limit, args.source_url)
            elif args.wiki_command == "work":
                result = store.work(args.kind, args.status, args.research_id, args.page_id,
                                    args.capture_id, args.offset, args.limit)
            elif args.wiki_command == "refresh":
                result = store.refresh(args.page_id, provider=args.provider, max_characters=args.max_characters,
                                       expected_revision=args.expected_revision, offset=args.offset, limit=args.limit)
            elif args.wiki_command == "search":
                result = store.search(args.query, args.offset, args.limit)
            else:
                result = store.lint(args.page_id)
        elif args.command == "job":
            from jobs import JobStore, JobWorker, default_handlers
            store = JobStore()
            try:
                if args.job_command == "submit":
                    raw = sys.stdin.read() if args.input == "-" else Path(args.input).expanduser().read_text(encoding="utf-8")
                    payload = json.loads(raw)
                    job = store.submit(args.kind, payload, idempotency_key=args.idempotency_key,
                                       priority=args.priority)
                    _emit_result({"job": job}, args)
                elif args.job_command == "list":
                    _emit_result({"jobs": store.list(state=args.state, kind=args.kind,
                                                     limit=args.limit, offset=args.offset)}, args)
                elif args.job_command == "status":
                    job = store.get(args.job_id)
                    if job is None:
                        raise ValueError("Unknown job: " + args.job_id)
                    _emit_result({"job": job}, args)
                elif args.job_command == "result":
                    job = store.get(args.job_id)
                    if job is None:
                        raise ValueError("Unknown job: " + args.job_id)
                    if job["result"] is None:
                        _emit_result({"job_id": job["job_id"], "state": job["state"],
                                      "note": "no result yet"}, args)
                    else:
                        _emit_result(job["result"], args)
                elif args.job_command == "cancel":
                    _emit_result({"job": store.cancel(args.job_id)}, args)
                elif args.job_command == "worker":
                    worker = JobWorker(store, handlers=default_handlers(),
                                       concurrency=args.concurrency,
                                       lease_seconds=args.lease_seconds,
                                       poll_seconds=args.poll_seconds)
                    if args.once:
                        _emit_result({"processed": worker.run_once()}, args)
                    else:
                        worker.serve(max_jobs=args.max_jobs)
                        _emit_result({"worker": "stopped"}, args)
            finally:
                store.close()
            return 0
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
                        ("research", "depth", args.depth),
                        ("search", "providers", args.search_provider),
                        ("search", "fallback_providers", args.search_fallback_provider),
                        ("search", "strategy", args.search_strategy),
                        ("fetch", "strategy", args.fetch_strategy),
                        ("fetch", "provider", args.fetch_provider),
                        ("fetch", "providers", args.fetch_fallback_provider),
                        ("fetch", "max_characters", args.max_characters),
                        ("search", "cache_seconds", args.search_cache_seconds),
                        ("fetch", "reuse_seconds", args.fetch_reuse_seconds),
                        ("server", "network_workers", args.server_workers),
                        ("server", "max_pending_calls", args.server_max_pending)):
                    if value is not None:
                        if not isinstance(changes.get(section, {}), dict):
                            raise ValueError("Settings section must be an object: " + section)
                        changes.setdefault(section, {})[field] = value
                if args.tool_scope_preset is not None:
                    changes["tool_scope_preset"] = args.tool_scope_preset
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
            result["storage"] = _storage_report(args, settings)
        elif args.command in ("providers", "search-web", "fetch-web"):
            from web_search import SearchProviders
            engine = SearchProviders(timeout=args.timeout, settings=settings)
            if args.command == "providers":
                result = engine.probe(args.provider) if args.probe else engine.describe(args.provider)
            elif args.command == "fetch-web":
                from archive import SourceArchive
                prefs = settings.load()["fetch"]
                total = prefs["max_total_characters"] if args.max_total_characters is None else args.max_total_characters
                fair = prefs["fair_share_min"]
                if not 100 <= total <= 800000:
                    raise ValueError("max_total_characters must be between 100 and 800000")
                if args.capture_id is not None:
                    if args.raw or args.provider is not None or args.archive is not None or args.timeout is not None:
                        raise ValueError("capture_id reads a saved extract; omit raw, provider, archive and timeout")
                    result = SourceArchive(settings.load()["archive"]["directory"]).read_capture(
                        args.capture_id, args.urls, max_characters=prefs["max_characters"]
                            if args.max_characters is None else args.max_characters,
                        max_total_characters=total, offset=args.offset, fair_share_min=fair)
                else:
                    if args.offset:
                        raise ValueError("offset requires capture_id so continued reads use the same saved evidence")
                    if args.raw:
                        result = engine._fetch(args.urls, args.provider, archive=args.archive,
                                               max_characters=args.max_characters)
                    else:
                        result = engine.fetch(args.urls, args.provider, archive=args.archive,
                                              max_characters=args.max_characters)
                    if not args.raw:
                        result = SourceArchive.compact_fetch(
                            result, max_total_characters=total, fair_share_min=fair)
            else:
                payload = _read_json(args.input) if args.input else {
                    "targets": [{"target": q, "query": q} for q in (args.target or [])],
                    "providers": args.provider, "limit_per_target": args.limit}
                if not isinstance(payload, dict) or set(payload) - {"targets", "providers", "limit_per_target"}:
                    raise ValueError("Search input accepts targets, providers and limit_per_target only")
                result = engine.search(payload.get("targets"), args.provider if args.provider is not None else payload.get("providers"),
                                       args.limit if args.limit is not None else payload.get("limit_per_target"))
        elif args.command == "search-archive":
            from raw_library import RawLibrary
            result = RawLibrary(settings=settings).search(args.query, args.limit, args.offset, args.url,
                                                          args.occurrence_limit, args.occurrence_offset)
        elif args.command == "merge-results":
            result = fuse_results(_read_json(args.input), archive=args.archive, settings=settings)
        elif args.command == "ingest":
            # The MCP primitive deliberately caps inline payloads.  A file
            # keeps larger host search batches out of the model context while
            # preserving the same deterministic fusion implementation.
            if bool(args.input_path) == bool(args.input_option):
                raise ValueError("provide exactly one ingest input path, positionally or with --input")
            result = fuse_results(_read_json(args.input_option or args.input_path),
                                  archive=args.archive, settings=settings)
        else:
            from source_manager import SourceManager
            locate_readonly = not args.refresh if args.command == "locate" else True
            if args.command == "locate" and args.handle:
                from locate import continuation_refresh_requested
                locate_readonly = not continuation_refresh_requested(args.handle, _database(args.db))
            readonly = (args.command in ("status", "history", "lookup-url")
                        or (args.command == "locate" and locate_readonly)
                        or (args.command == "search" and args.no_refresh)
                        or (args.command in ("traverse", "context") and args.no_refresh)
                        or args.command == "dupes")
            with BookmarkIndex(str(_database(args.db)), readonly=readonly) as index:
                sources = SourceManager(index)
                if args.command == "dupes":
                    source_ids = [args.source_id] if args.source_id else sources.live_sources()
                    if len(source_ids) != 1:
                        raise ValueError("source_required: dupes requires --source-id when the index has zero or multiple live sources")
                    result = index.duplicate_urls(source_ids[0], min_count=args.min_count,
                                                  limit=args.limit, offset=args.offset,
                                                  include_search=args.include_search)
                elif args.command == "sync":
                    result = sources.sync(args.package, args.source_id, mode=args.mode, completeness=args.completeness)
                elif args.command == "status":
                    result = sources.status(args.source)
                elif args.command == "history":
                    result = sources.history(args.source, limit=args.limit, offset=args.offset)
                elif args.command == "lookup-url":
                    with index.read_snapshot():
                        result = index.lookup_url(args.url, source_id=args.source_id, limit=args.limit, offset=args.offset)
                elif args.command == "locate":
                    from locate import locate as locate_core
                    from locate import continuation_scope
                    locate_scope = args.in_sources or ["canvas"]
                    if args.handle:
                        locate_scope = continuation_scope(args.handle, _database(args.db))
                    wiki = None
                    raw = None
                    if locate_scope == ["wiki"]:
                        from research import ResearchSessions
                        from wiki import WikiStore
                        sessions = ResearchSessions(settings=settings, db_path=_database(args.db))
                        wiki = WikiStore(directory=WikiStore.selected_directory(settings), settings=settings,
                                         research_sessions=sessions)
                    elif locate_scope == ["archive"]:
                        from raw_library import RawLibrary
                        raw = RawLibrary(settings=settings)
                    elif args.handle:
                        # The continuation handle is opaque; provide both
                        # adapters so the core can restore its original scope.
                        from research import ResearchSessions
                        from raw_library import RawLibrary
                        from wiki import WikiStore
                        sessions = ResearchSessions(settings=settings, db_path=_database(args.db))
                        wiki = WikiStore(directory=WikiStore.selected_directory(settings), settings=settings,
                                         research_sessions=sessions)
                        raw = RawLibrary(settings=settings)
                    result = locate_core(index, sources, {
                        "text": args.text, "url": args.url,
                        "in": locate_scope,
                        "source_id": args.source_id, "section": args.section,
                        "folder_id": args.folder_id, "tags": args.tags,
                        "tag_colors": args.tag_colors, "has_note": args.has_note,
                        "has_tags": args.has_tags, "metadata_match": args.metadata_match,
                        "limit": args.limit, "offset": args.offset,
                        "handle": args.handle, "refresh": args.refresh,
                    }, wiki=wiki, raw=raw)
                elif args.command == "source":
                    if args.source_command == "remove":
                        result = sources.remove(args.source_id, confirm=args.confirm)
                    else:
                        result = sources.merge(args.source_id, args.into_source_id, confirm=args.confirm)
                else:
                    if args.no_refresh:
                        refresh = None
                    elif index.readonly:
                        # The index degraded to read-only (shared file, read-only
                        # mount, sandboxed host): answer from the saved snapshot
                        # instead of failing on the refresh write.
                        refresh = {"state": "skipped", "reason": "read-only index"}
                    else:
                        refresh = sources.refresh(args.source)
                    if refresh and refresh["state"] in ("error", "unavailable"):
                        raise ValueError(refresh["error"] + "; use --no-refresh to read the saved index")
                    with index.read_snapshot():
                        if args.command == "search":
                            result = index.search(args.source, targets=args.target, section=args.section,
                                                  group_id=args.group, folder_id=args.folder, tags=args.tag,
                                                  limit=args.limit, offset=args.offset, tag_colors=args.tag_color,
                                                  item_types=args.item_type or None, count_only=args.count_only,
                                                  compact=args.compact, score=args.score)
                        elif args.command == "traverse":
                            result = index.traverse(args.source, section=args.section, group_id=args.group,
                                                    item_id=args.item, node_id=args.node,
                                                    max_depth=args.depth, direction=args.direction,
                                                    limit=args.limit, offset=args.offset)
                        else:
                            from context_output import page_context
                            result = index.context(args.source, section=args.section, group_id=args.group,
                                                   item_id=args.item)
                            result = page_context(result, args.collection, args.offset, args.limit)
                        result["source"] = sources.source_status(args.source)
                    result["refresh"] = refresh
                    result["stored_snapshot_only"] = args.no_refresh
        _emit_result(result, args)
        if args.command == "providers" and args.probe and result["successful_provider_count"] == 0:
            return 1
        if args.command == "search-web" and result.get("successful_provider_count") == 0:
            return 1
        if args.command == "fetch-web" and result.get("status") == "error":
            return 1
        if args.command == "research" and result.get("status") == "error":
            return 1
        if args.command == "wiki" and args.wiki_command == "refresh" and result.get("status") == "error":
            return 1
        if isinstance(result, dict) and result.get("status") == "partial":
            return 3
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"cancelled": True, "error": "Setup cancelled; previously saved preferences and keys are retained."}))
        return 130
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        message = str(error)
        if isinstance(error, sqlite3.Error) and ("readonly" in message or "unable to open" in message):
            # A raw SQLite error gives no way to recover; name the two paths the
            # user can actually change and how.
            message = ("Cannot write the data directory: %s. Set BOOKMARK_RESEARCH_DATA_DIR to a writable directory "
                       "(and BOOKMARK_RESEARCH_CONFIG for settings), or fix that directory's permissions. "
                       "Run doctor for a storage check." % message)
        print(json.dumps({"error": message, "type": type(error).__name__}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
