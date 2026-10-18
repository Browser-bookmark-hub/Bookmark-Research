"""Paginate context views without narrowing the frozen research inventory."""

COLLECTIONS = ("sections", "items", "nodes", "groups", "edges", "related_nodes", "memberships")


def page_context(context, collection=None, offset=0, limit=200, scope_notes=None):
    if collection is not None and collection not in COLLECTIONS:
        raise ValueError("Unknown context collection")
    if type(offset) is not int or not 0 <= offset <= 1000000000:
        raise ValueError("offset must be a non-negative integer")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer from 1 to 1000")
    result = {key: value for key, value in context.items() if key not in COLLECTIONS}
    pagination = {}
    for name in COLLECTIONS:
        rows = context.get(name, [])
        selected = collection is None or collection == name
        page = rows[offset:offset + limit] if selected else []
        entry = {"total": len(rows), "returned": len(page), "offset": offset if selected else 0,
                 "next_offset": offset + len(page) if selected and offset + len(page) < len(rows) else None,
                 "included": selected}
        # An empty collection can be a scope that needs another parameter rather
        # than an empty tree. Say which, instead of reporting a bare zero that
        # contradicts the section counts in the same response.
        if selected:
            if not rows and scope_notes and scope_notes.get(name):
                entry["scope_note"] = scope_notes[name]
            result[name] = page
        pagination[name] = entry
    result["pagination"] = pagination
    result["pagination_note"] = "Counts cover the full requested scope. Continue each collection with the same scope and its next_offset."
    return result
