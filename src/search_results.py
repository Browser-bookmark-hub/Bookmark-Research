"""Fuse normalized search batches without fetching pages or verifying claims.

RRF contributions are unique per (target, provider, query, canonical URL).
An optional ``targets`` list identifies requested targets with no batch at all.
Only snippets are retained; full source text belongs in a later fetch step.
"""

from collections import OrderedDict
from urllib.parse import urlsplit, urlunsplit
import ipaddress
import re


RRF_K = 60
MAX_SNIPPET_CHARS = 1200
MAX_RANK = 2147483647


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _canonical_url(raw_url):
    """Conservative URL identity, retaining queries and client-side routes."""
    if not _nonempty_string(raw_url):
        raise ValueError("url must be a nonempty string")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw_url):
        raise ValueError("url contains whitespace or control characters")
    if "\\" in raw_url:
        raise ValueError("url contains a backslash")
    try:
        parts = urlsplit(raw_url)
        if parts.scheme.lower() not in ("http", "https"):
            raise ValueError("only http and https URLs are accepted")
        host = parts.hostname
        port = parts.port
        if not host or parts.username is not None or parts.password is not None:
            raise ValueError("url must have a host and no userinfo")
        if parts.netloc.startswith("[") or ":" in host:
            ipaddress.IPv6Address(host)
            host = "[" + host.lower() + "]"
        else:
            ascii_host = host.encode("idna").decode("ascii")
            if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.?", ascii_host):
                raise ValueError("invalid URL host")
            host = host.lower()
    except (UnicodeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    scheme = parts.scheme.lower()
    if port is not None and (scheme, port) not in (("http", 80), ("https", 443)):
        host += ":" + str(port)
    # Ordinary anchors share a page. Hash-router URLs may represent other pages.
    fragment = parts.fragment if parts.fragment.startswith(("/", "!")) else ""
    # HTTP(S) requests use '/' for an empty path (RFC 3986 section 6.2.3).
    canonical = urlunsplit((scheme, host, parts.path or "/", parts.query, fragment))
    if not parts.query and "?" in raw_url.split("#", 1)[0]:
        before_fragment, marker, after_fragment = canonical.partition("#")
        canonical = before_fragment + "?" + (marker + after_fragment if marker else "")
    return canonical


def _bucket():
    return {"submitted": 0, "streams": {}, "error_count": 0, "invalid_count": 0}


def _mode(providers, query_count):
    if not providers:
        return "no_provider"
    if len(providers) > 1:
        return "multi_provider"
    return "single_provider_multi_query" if query_count > 1 else "single_provider_single_query"


def fuse_results(payload):
    """Return independently ranked targets, provenance, failures and coverage.

    Malformed top-level configuration raises ValueError. Invalid batches/results
    are reported and do not discard valid siblings. Provider counts include
    failed providers; successful-provider coverage is reported separately.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("batches"), list):
        raise ValueError("payload must be an object with a batches array")
    limit = payload.get("limit_per_target", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit_per_target must be a positive integer")
    requested = payload.get("targets", [])
    if not isinstance(requested, list) or any(not _nonempty_string(t) for t in requested):
        raise ValueError("targets must be an array of nonempty strings")
    buckets = OrderedDict((target.strip(), _bucket()) for target in requested)
    errors, invalid_results = [], []

    def error(batch_index, message, target=None, provider=None, query=None, kind="invalid_batch"):
        errors.append({"batch_index": batch_index, "target": target,
                       "provider": provider, "query": query, "kind": kind, "error": message})
        if target in buckets:
            buckets[target]["error_count"] += 1

    for batch_index, batch in enumerate(payload["batches"]):
        if not isinstance(batch, dict):
            error(batch_index, "batch must be an object")
            continue
        target = batch.get("target")
        if not _nonempty_string(target):
            error(batch_index, "target must be a nonempty string")
            continue
        target = target.strip()
        bucket = buckets.setdefault(target, _bucket())
        bucket["submitted"] += 1
        provider, query = batch.get("provider"), batch.get("query")
        if not _nonempty_string(provider) or not _nonempty_string(query):
            error(batch_index, "provider and query must be nonempty strings", target)
            continue
        provider, query = provider.strip().lower(), query.strip()
        stream = bucket["streams"].setdefault((provider, query),
                                             {"ok": False, "failed": False, "urls": {}})
        status = batch.get("status")
        if status not in ("ok", "error"):
            stream["failed"] = True
            error(batch_index, "status must be ok or error", target, provider, query)
            continue
        if status == "error":
            stream["failed"] = True
            error(batch_index, batch.get("error") or "provider returned an error",
                  target, provider, query, "provider_error")
            continue
        results = batch.get("results")
        if not isinstance(results, list):
            stream["failed"] = True
            error(batch_index, "an ok batch must have a results array", target, provider, query)
            continue
        stream["ok"] = True
        for position, item in enumerate(results, 1):
            try:
                if not isinstance(item, dict):
                    raise ValueError("result must be an object")
                raw_url = item.get("url")
                canonical = _canonical_url(raw_url)
                rank = item.get("rank", position)
                if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= MAX_RANK:
                    raise ValueError("rank must be an integer between 1 and " + str(MAX_RANK))
                title = item.get("title", "")
                if not isinstance(title, str):
                    raise ValueError("title must be a string")
                snippet = item.get("snippet")
                if snippet is None:
                    snippet = item.get("text", "")
                if not isinstance(snippet, str):
                    raise ValueError("text or snippet must be a string")
            except ValueError as exc:
                invalid_results.append({"batch_index": batch_index, "result_position": position,
                                        "target": target, "provider": provider, "query": query,
                                        "raw_url": item.get("url") if isinstance(item, dict) else None,
                                        "reason": str(exc)})
                bucket["invalid_count"] += 1
                continue
            snippet, truncated = snippet[:MAX_SNIPPET_CHARS], len(snippet) > MAX_SNIPPET_CHARS
            existing = stream["urls"].get(canonical)
            if existing is None:
                stream["urls"][canonical] = {
                    "rank": rank, "raw_urls": {raw_url}, "title": title,
                    "snippet": snippet, "snippet_truncated": truncated,
                }
            else:
                existing["rank"] = min(existing["rank"], rank)
                existing["raw_urls"].add(raw_url)
                if title:
                    existing["title"] = min(t for t in (existing["title"], title) if t)
                old = (len(existing["snippet"]), existing["snippet"], existing["snippet_truncated"])
                new = (len(snippet), snippet, truncated)
                if new > old:
                    existing["snippet"], existing["snippet_truncated"] = snippet, truncated

    targets, all_providers, all_successful_providers = [], set(), set()
    query_count = 0
    for target, bucket in buckets.items():
        streams = bucket["streams"]
        by_url, by_provider = {}, {}
        for (provider, query), stream in sorted(streams.items()):
            coverage = by_provider.setdefault(provider, {"query_count": 0, "successful_queries": 0,
                                                         "failed_queries": 0, "unique_urls": set()})
            coverage["query_count"] += 1
            coverage["successful_queries"] += int(stream["ok"])
            coverage["failed_queries"] += int(stream["failed"])
            coverage["unique_urls"].update(stream["urls"])
            for canonical, hit in stream["urls"].items():
                raw_urls = sorted(hit["raw_urls"])
                by_url.setdefault(canonical, []).append({
                    "provider": provider, "query": query, "rank": hit["rank"],
                    "url": raw_urls[0], "raw_urls": raw_urls, "title": hit["title"],
                    "snippet": hit["snippet"], "snippet_truncated": hit["snippet_truncated"],
                })
        ranked = []
        for canonical, sources in by_url.items():
            sources.sort(key=lambda source: (source["rank"], source["provider"], source["query"]))
            ranked.append({
                "url": sources[0]["url"], "canonical_url": canonical,
                "raw_urls": sorted({url for source in sources for url in source["raw_urls"]}),
                "title": next((source["title"] for source in sources if source["title"]), ""),
                "rrf_score": sum(1.0 / (RRF_K + source["rank"]) for source in sources),
                "provider_count": len({source["provider"] for source in sources}),
                "evidence_count": len(sources), "sources": sources,
            })
        ranked.sort(key=lambda hit: (-hit["rrf_score"], hit["canonical_url"]))
        successful_queries = sum(int(stream["ok"]) for stream in streams.values())
        failed_queries = sum(int(stream["failed"]) for stream in streams.values())
        has_issues = bool(bucket["error_count"] or bucket["invalid_count"])
        if not bucket["submitted"]:
            status = "missing"
        elif not successful_queries:
            status = "error"
        elif has_issues:
            status = "partial"
        else:
            status = "ok" if ranked else "empty"
        successful_providers = sorted(p for p, coverage in by_provider.items() if coverage["successful_queries"])
        for coverage in by_provider.values():
            coverage["unique_urls"] = len(coverage["unique_urls"])
        targets.append({
            "target": target, "status": status, "providers": sorted(by_provider),
            "provider_count": len(by_provider), "query_count": len(streams),
            "mode": _mode(by_provider, len(streams)),
            "coverage": {"submitted_batches": bucket["submitted"], "unique_queries": len(streams),
                         "successful_queries": successful_queries, "failed_queries": failed_queries,
                         "successful_providers": successful_providers,
                         "invalid_results": bucket["invalid_count"], "unique_urls": len(ranked),
                         "returned_urls": min(limit, len(ranked)), "truncated": len(ranked) > limit,
                         "by_provider": by_provider},
            "results": ranked[:limit],
        })
        all_providers.update(by_provider)
        all_successful_providers.update(successful_providers)
        query_count += len(streams)
    return {
        "provider_count": len(all_providers), "providers": sorted(all_providers),
        "successful_provider_count": len(all_successful_providers),
        "target_count": len(targets), "query_count": query_count,
        "mode": _mode(all_providers, query_count), "limit_per_target": limit,
        "ranking": {"method": "rrf", "k": RRF_K,
                    "evidence_unit": "unique provider/query retrieval for this target and URL",
                    "independent_fact_confirmation": False},
        "missing_targets": [item["target"] for item in targets if item["status"] == "missing"],
        "uncovered_targets": [item["target"] for item in targets if not item["results"]],
        "targets": targets, "errors": errors, "invalid_results": invalid_results,
    }
