"""Call internal implementation names that tools/call no longer exposes.

The replaced historical names (search_bookmarks, get_context, fetch_web, ...)
remain the implementations behind the primitives and the CLI. Tests cover them
directly with the same validation and result envelope a public call gets.
"""

from mcp_server import INTERNAL_SCHEMAS, RpcError, _validate, schema_for


def call_internal(server, name, arguments=None, request_id=1):
    arguments = {} if arguments is None else arguments
    try:
        _validate(schema_for(name), arguments)
    except RpcError as exc:
        return {"jsonrpc": "2.0", "id": request_id,
                "result": server._tool_result({"tool": name, "error": str(exc),
                                               "error_type": "InvalidArguments"}, is_error=True)}
    return {"jsonrpc": "2.0", "id": request_id, "result": server._execute(name, arguments)}


def is_internal(name):
    return name in INTERNAL_SCHEMAS
