#!/usr/bin/env python3
"""Call one shared research MCP tool using JSON stdin and the bundled server."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def call_tool(request, db=None, config=None, timeout=600):
    if not isinstance(request, dict) or set(request) != {"name", "arguments"}:
        raise ValueError("Request must contain exactly name and arguments")
    if not isinstance(request["name"], str) or not request["name"].startswith("research_"):
        raise ValueError("This bridge calls research_* tools only")
    if not isinstance(request["arguments"], dict):
        raise ValueError("arguments must be a JSON object")
    command = [sys.executable, "-B", str(Path(__file__).resolve().parents[2] / "src/cli.py")]
    if db:
        command.extend(["--db", str(db)])
    if config:
        command.extend(["--config", str(config)])
    command.append("serve")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "bookmark-research-host-bridge", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": request},
    ]
    result = subprocess.run(command, input="\n".join(json.dumps(row) for row in messages) + "\n",
                            text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Shared MCP process failed: " + result.stderr.strip()[:2000])
    responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    response = next((row for row in responses if row.get("id") == 2), None)
    if response is None:
        raise RuntimeError("Shared MCP process returned no tool response")
    if "error" in response:
        return {"isError": True, "result": response["error"]}
    tool_result = response["result"]
    if "structuredContent" in tool_result:
        value = tool_result["structuredContent"]
    else:
        text = "\n".join(item["text"] for item in tool_result.get("content", []) if item.get("type") == "text")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = {"text": text}
    return {"isError": bool(tool_result.get("isError")), "result": value}


def main():
    for stream in (sys.stdout, sys.stderr):  # Windows pipes default to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db")
    parser.add_argument("--config")
    parser.add_argument("--timeout", type=float, default=600)
    options = parser.parse_args()
    try:
        if options.timeout <= 0:
            raise ValueError("timeout must be positive")
        result = call_tool(json.load(sys.stdin), options.db, options.config, options.timeout)
    except subprocess.TimeoutExpired:
        result = {"isError": True, "unknown_outcome": True,
                  "result": {"error": "MCP call timed out. Inspect research_status before retrying; an operation may have reserved budget or saved a result."}}
    except (OSError, ValueError, RuntimeError) as error:
        result = {"isError": True, "result": {"error": str(error)}}
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["isError"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
