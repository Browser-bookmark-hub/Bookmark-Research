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
    configure.add_argument("--search-provider", action="append", choices=("exa", "parallel"))
    configure.add_argument("--fetch-provider", choices=("exa", "parallel"))
    configure.add_argument("--max-characters", type=int)
    sync = commands.add_parser("sync", help="Register/import a JSON/.canvas package")
    sync.add_argument("package")
    sync.add_argument("--source-id")
    status = commands.add_parser("status")
    status.add_argument("source", nargs="?")
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
    fetch.add_argument("--provider", choices=("exa", "parallel"))
    fetch.add_argument("--timeout", type=int)
    fetch.add_argument("--max-characters", type=int)
    archival = fetch.add_mutually_exclusive_group()
    archival.add_argument("--archive", dest="archive", action="store_true", default=None)
    archival.add_argument("--no-archive", dest="archive", action="store_false")
    merge = commands.add_parser("merge-results", help="Fuse normalized batches from existing MCPs")
    merge.add_argument("input", help="JSON input file, or '-' for stdin")
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
        if args.command == "config":
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
                        ("fetch", "provider", args.fetch_provider),
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
            with BookmarkIndex(str(_database(args.db))) as index:
                if args.command == "sync":
                    result = index.sync(args.package, args.source_id)
                elif args.command == "status":
                    result = index.status(args.source)
                else:
                    refresh = None if args.no_refresh else index.refresh(args.source)
                    if args.command == "search":
                        result = index.search(args.source, targets=args.target, section=args.section,
                                              group_id=args.group, folder_id=args.folder, tags=args.tag,
                                              limit=args.limit, offset=args.offset)
                    else:
                        result = index.context(args.source, section=args.section, group_id=args.group,
                                               item_id=args.item)
                    result["refresh"] = refresh
                    result["stored_snapshot_only"] = args.no_refresh
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "providers" and args.probe and result["successful_provider_count"] == 0:
            return 1
        if args.command == "search-web" and result.get("successful_provider_count") == 0:
            return 1
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
