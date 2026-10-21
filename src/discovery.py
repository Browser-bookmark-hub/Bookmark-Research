"""Assemble a route ② evidence bundle from what the host actually collected.

Route ② is planned by the host; this module is the plugin's side of that deal:
the budget decision, and a citation-ready bundle that degrades from excerpts to a
digest to a plain list instead of returning nothing. Nothing here fetches,
searches or reasons, and nothing here states a fact the sources do not.
"""

import json

EXCERPT_CHARACTERS = 1200
DIGEST_CHARACTERS = 320
DEFAULT_MAX_CHARACTERS = 50000
MAX_MAX_CHARACTERS = 50000
DEFAULT_LIMITS = {"max_steps": 6, "max_fetches": 8, "max_variants": 3, "max_seconds": 90}
LIMIT_BOUNDS = {"max_steps": (1, 40), "max_fetches": (1, 80), "max_variants": (1, 20), "max_seconds": (5, 600)}
LEVELS = ("excerpts", "digest", "list")
FIELDS = {"steps": "max_steps", "fetches": "max_fetches", "variants": "max_variants", "seconds": "max_seconds"}


def _count(value, label, minimum=0, maximum=10 ** 6):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("%s must be an integer from %d to %d" % (label, minimum, maximum))
    return value


def budget_check(steps=0, fetches=0, variants=0, elapsed_seconds=0, limits=None):
    """Continue or stop, with the reason and what is left.

    The plugin owns this decision, so a host cannot silently overrun the budget
    the plan fixed (steps ≤ 6, fetches ≤ 8, query variants ≤ 3, 90 seconds).
    """
    used = {"steps": _count(steps, "steps"), "fetches": _count(fetches, "fetches"),
            "variants": _count(variants, "variants")}
    if type(elapsed_seconds) not in (int, float) or isinstance(elapsed_seconds, bool) or elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be a non-negative number")
    used["seconds"] = elapsed_seconds
    chosen = dict(DEFAULT_LIMITS)
    for name in (limits or {}):
        if name not in chosen:
            raise ValueError("Unknown discovery limit: " + str(name))
    for name, value in (limits or {}).items():
        minimum, maximum = LIMIT_BOUNDS[name]
        chosen[name] = _count(value, "limits." + name, minimum, maximum)
    reached = [field for field, limit in FIELDS.items() if used[field] >= chosen[limit]]
    return {"continue": not reached, "reason": None if not reached else reached[0] + "_reached",
            "used": used, "limits": chosen,
            "remaining": {field: max(0, chosen[limit] - used[field]) for field, limit in FIELDS.items()},
            "note": "The plugin owns this decision: stop when continue is false."}


def evidence_bundle(sources, max_characters=DEFAULT_MAX_CHARACTERS, excerpt_characters=EXCERPT_CHARACTERS):
    """A citation-ready bundle over the sources the host collected.

    Only pages whose content state is usable become evidence; everything else is
    listed with the reason it cannot be cited. The bundle is assembled at the
    richest level that fits max_characters and always carries the URL list, so
    the ladder degrades instead of returning nothing.
    """
    if not isinstance(sources, list) or len(sources) > 64:
        raise ValueError("sources must be a list of at most 64 source records")
    max_characters = _count(max_characters, "max_characters", 1000, MAX_MAX_CHARACTERS)
    excerpt_characters = _count(excerpt_characters, "excerpt_characters", 80, 8000)
    usable, unavailable = [], []
    for row in sources:
        if not isinstance(row, dict):
            raise ValueError("Each source must be an object")
        url = row.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("Each source needs a url")
        state = row.get("content_state") or ("usable" if row.get("text") else "unavailable")
        if state == "usable" and isinstance(row.get("text"), str) and row["text"].strip():
            usable.append(row)
        else:
            if state == "usable":
                reason = "no_text"
            else:
                reason = row.get("error") or row.get("extraction_status") or state or "unavailable"
            unavailable.append({"url": url, "reason": str(reason), "title": row.get("title") or ""})
    bundle, level = None, LEVELS[-1]
    for level in LEVELS:
        bundle = _bundle_at(level, usable, unavailable, excerpt_characters)
        if _characters(bundle) <= max_characters:
            break
    bundle["degradation"] = level
    bundle["characters"] = _characters(bundle)
    bundle["max_characters"] = max_characters
    bundle["truncated"] = bundle["characters"] > max_characters
    bundle["gaps"] = [] if usable else ["No usable page text was collected for this question"]
    bundle["citation_rule"] = "Cite evidence[].id; never cite a URL that has no evidence entry."
    bundle["next_action"] = ("Report the evidence and the gaps." if usable else
                             "Report the collected URLs and why each has no usable text; "
                             "do not answer from snippets.")
    return bundle


def _bundle_at(level, usable, unavailable, excerpt_characters):
    limit = excerpt_characters if level == "excerpts" else DIGEST_CHARACTERS
    evidence = []
    for index, row in enumerate(usable, start=1):
        entry = {"id": "e%d" % index, "url": row["url"], "title": row.get("title") or "",
                 "published_at": row.get("published_at") or row.get("provider_published_at"),
                 "characters": len(row["text"])}
        if row.get("capture_id") or row.get("text_origin"):
            entry["source_characters"] = len(row["text"])
        for name in ("capture_id", "text_sha256", "text_origin", "quote_verified"):
            if row.get(name) is not None:
                entry[name] = row[name]
        if level != "list":
            entry["excerpt"] = row["text"][:limit]
            entry["excerpt_truncated"] = len(row["text"]) > limit
        evidence.append(entry)
    return {"evidence": evidence, "unavailable_sources": unavailable,
            "evidence_count": len(evidence), "unavailable_count": len(unavailable)}


def _characters(bundle):
    return len(json.dumps(bundle, ensure_ascii=False))
