"""Compare cited bookmark metadata and its local canvas context."""
import json


def scoped_input(inventory, references):
    """Exclude index bookkeeping, retaining user-authored raw metadata."""
    def item_key(row):
        return tuple(row[key] for key in ("source_id", "section_id", "item_id"))

    def node_key(row, key="node_id"):
        return row["source_id"], row["canvas_path"], row[key]

    def clean(row, excluded=()):
        # Only generated, top-level keys are removed. A user field named
        # "revision" inside raw_json is still a substantive dependency.
        return {key: value for key, value in row.items() if key not in ("revision", *excluded)}

    def ordered(rows):
        return sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))

    wanted = {item_key(reference) for reference in references}
    items = [item for entry in inventory["entries"] for item in entry["instances"]
             if item_key(item) in wanted]
    sections = {(item["source_id"], appearance["section_id"])
                for item in items for appearance in item.get("appearances", [])}
    sections.update((item["source_id"], item["section_id"]) for item in items)
    ancestors = {(item["source_id"], item["section_id"], ancestor)
                 for item in items for ancestor in item.get("ancestor_ids", [])}
    selected = {node_key(node) for node in inventory["nodes"]
                if (node["source_id"], node.get("section_id")) in sections}
    # Include enclosing groups (also nested groups), their members and explicit
    # edge endpoints. Text, geometry and relation labels remain observable.
    while True:
        parents = {node_key(member, "group_id") for member in inventory["memberships"]
                   if node_key(member) in selected}
        if parents <= selected:
            break
        selected.update(parents)
    memberships = [member for member in inventory["memberships"]
                   if node_key(member) in selected or node_key(member, "group_id") in selected]
    edges = [edge for edge in inventory["edges"]
             if any(node_key(edge, end) in selected for end in ("from_node", "to_node"))]
    related = selected | {node_key(member, end) for member in memberships for end in ("group_id", "node_id")}
    related.update(node_key(edge, end) for edge in edges for end in ("from_node", "to_node"))
    return {
        "missing": sorted(wanted - {item_key(item) for item in items}),
        "items": ordered(clean(item, ("preorder", "appearances")) for item in items),
        "folders": ordered(clean(folder, ("preorder",)) for folder in inventory["folders"]
                           if item_key(folder) in ancestors),
        "sections": ordered(clean(section, ("bookmark_count", "counted_in_total"))
                            for section in inventory["sections"]
                            if (section["source_id"], section["section_id"]) in sections),
        "nodes": ordered(clean(node) for node in inventory["nodes"] if node_key(node) in related),
        "edges": ordered(clean(edge) for edge in edges),
        "memberships": ordered(clean(member) for member in memberships),
    }
