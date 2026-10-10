"""Optional compact views of bookmark search pages; the index stays unchanged."""

import json
from copy import deepcopy


_ALIASES = {"source": "source_id", "section": "section_id", "item": "item_id"}
_RAW_FIELDS = {
    "id": "item_id", "parentId": "parent_id", "sectionId": "section_id",
    "type": "item_type", "title": "title", "url": "url",
    "note": "note", "noteColor": "note_color", "tags": "tags",
}
_METADATA_FIELDS = {"syncId": "item_id", "note": "note", "noteColor": "note_color", "tags": "tags"}


def _signature(value):
    # Python equality conflates booleans and numbers, even inside nested values.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _compact_row(row):
    for field in ("source_id", "section_id", "item_id"):
        if field not in row:
            raise ValueError("Cannot compact a row without " + field)
    result = deepcopy(row)
    for alias, standard in _ALIASES.items():
        if alias in row and _signature(row[alias]) == _signature(row[standard]):
            result.pop(alias)
    for field, mapping in (("raw_json", _RAW_FIELDS), ("metadata", _METADATA_FIELDS)):
        if field not in row or not isinstance(row[field], dict):
            continue
        extras = {}
        for key, value in row[field].items():
            standard = mapping.get(key)
            if standard not in row or _signature(value) != _signature(row[standard]):
                extras[key] = deepcopy(value)
        if extras:
            result[field] = extras
        else:
            result.pop(field)
    return result


def compact_search(response):
    """Keep each distinct row once, preserving every target's independent page."""
    if {"_compact", "rows", "result_refs"}.intersection(response):
        raise ValueError("Search response already contains compact view fields")
    output = {key: deepcopy(value) for key, value in response.items() if key not in ("results", "targets")}
    output["_compact"] = {
        "format": "bookmark-search-v1",
        "row_refs": "Each result_refs selects its ordered page from rows. References are response-local.",
        "raw_fields": "Row raw_json/metadata contain extra or conflicting fields; compact=false returns full rows.",
    }
    output["rows"] = {}
    seen = {}

    def reference(row):
        compact = _compact_row(row)
        # Identity and content both matter: equal URLs are not equal instances.
        signature = _signature(compact)
        if signature not in seen:
            key = "r" + str(len(output["rows"]) + 1)
            seen[signature] = key
            output["rows"][key] = compact
        return seen[signature]

    output["result_refs"] = [reference(row) for row in response.get("results", [])]
    output["targets"] = []
    for target in response.get("targets", []):
        if "result_refs" in target:
            raise ValueError("Search target already contains compact view fields")
        page = {key: deepcopy(value) for key, value in target.items() if key != "results"}
        page["result_refs"] = [reference(row) for row in target.get("results", [])]
        output["targets"].append(page)
    return output
