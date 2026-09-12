"""Explicit mappings for observed Exa, Parallel and Tavily MCP schemas.

Only search and extraction are routed. Catalog annotations never authorize an
unknown tool, and unsupported required fields fail before a billable call.
"""

import math
import re

from remote_mcp import McpError


class ProviderAdapter:
    def __init__(self, provider, info):
        self.provider, self.info = provider, info

    @staticmethod
    def _schema_error(message):
        return McpError("Provider tool schema changed; " + message, "schema_mismatch")

    def select(self, purpose, tools):
        for name in self.info[purpose + "_tools"]:
            for tool in tools:
                if isinstance(tool, dict) and tool.get("name") == name:
                    return tool
        raise McpError("Provider does not expose its expected %s tool" % purpose,
                       "capability_unavailable")

    @classmethod
    def _validate(cls, schema, value, path="arguments", depth=0):
        """Check the emitted JSON-schema subset, rejecting unknown constraints."""
        if not isinstance(schema, dict) or depth > 12:
            raise cls._schema_error("invalid or overly nested input schema")
        unsupported = {"$ref", "$dynamicRef", "not", "if", "then", "else", "dependentSchemas",
                       "dependentRequired", "pattern", "patternProperties", "unevaluatedProperties",
                       "contains", "prefixItems", "propertyNames"} & set(schema)
        if unsupported:
            raise cls._schema_error("unsupported input constraint")
        for combinator in ("anyOf", "oneOf", "allOf"):
            if combinator in schema:
                branches = schema[combinator]
                if not isinstance(branches, list) or not branches or len(branches) > 16:
                    raise cls._schema_error("invalid union schema")
                matches = 0
                for branch in branches:
                    try:
                        cls._validate(branch, value, path, depth + 1)
                        matches += 1
                    except McpError:
                        pass
                expected = len(branches) if combinator == "allOf" else 1
                if matches < expected or (combinator == "oneOf" and matches != 1):
                    raise cls._schema_error(path + " does not match its input schema")
        kinds = schema.get("type")
        if kinds is not None:
            kinds = kinds if isinstance(kinds, list) else [kinds]
            tests = {"string": isinstance(value, str), "array": isinstance(value, list),
                     "object": isinstance(value, dict), "boolean": type(value) is bool,
                     "integer": type(value) is int, "number": type(value) in (int, float),
                     "null": value is None}
            if not kinds or any(not isinstance(kind, str) or kind not in tests for kind in kinds):
                raise cls._schema_error("invalid field type")
            if not any(tests[kind] for kind in kinds):
                raise cls._schema_error(path + " has an unsupported type")
        if "enum" in schema:
            choices = schema["enum"]
            if not isinstance(choices, list) or value not in choices:
                raise cls._schema_error(path + " is outside the supported enum")
        if "const" in schema and value != schema["const"]:
            raise cls._schema_error(path + " does not match the required constant")
        if isinstance(value, dict):
            properties, required = schema.get("properties", {}), schema.get("required", [])
            if not isinstance(properties, dict) or not isinstance(required, list) or any(not isinstance(k, str) for k in required):
                raise cls._schema_error("invalid properties or required-fields schema")
            missing = set(required) - set(value)
            if missing:
                # Report ordinary field names, never arbitrary upstream text.
                labels = [k if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", k) else "<unknown>" for k in sorted(missing)]
                raise cls._schema_error("unsupported required fields: " + ", ".join(labels[:12]))
            if schema.get("additionalProperties") is False and set(value) - set(properties):
                raise cls._schema_error("unsupported extra arguments")
            for key, item in value.items():
                if key in properties:
                    cls._validate(properties[key], item, key, depth + 1)
        if isinstance(value, list):
            for bound, valid in (("minItems", lambda n: len(value) >= n), ("maxItems", lambda n: len(value) <= n)):
                if bound in schema and (type(schema[bound]) is not int or not valid(schema[bound])):
                    raise cls._schema_error(path + " violates array limits")
            if schema.get("uniqueItems") is True and any(value[i] in value[:i] for i in range(len(value))):
                raise cls._schema_error(path + " requires unique items")
            if "items" in schema:
                for item in value:
                    cls._validate(schema["items"], item, path + "[]", depth + 1)
        if isinstance(value, str):
            for bound, valid in (("minLength", lambda n: len(value) >= n), ("maxLength", lambda n: len(value) <= n)):
                if bound in schema and (type(schema[bound]) is not int or not valid(schema[bound])):
                    raise cls._schema_error(path + " violates string limits")
        if type(value) in (int, float):
            if not math.isfinite(value):
                raise cls._schema_error(path + " must be finite")
            for bound, valid in (("minimum", lambda n: value >= n), ("maximum", lambda n: value <= n),
                                 ("exclusiveMinimum", lambda n: value > n), ("exclusiveMaximum", lambda n: value < n)):
                if bound in schema and (type(schema[bound]) not in (int, float) or not valid(schema[bound])):
                    raise cls._schema_error(path + " violates numeric limits")
            if "multipleOf" in schema:
                unit = schema["multipleOf"]
                if type(unit) not in (int, float) or unit <= 0 or not math.isfinite(unit) or value % unit:
                    raise cls._schema_error(path + " violates numeric step")

    def arguments(self, tool, purpose, query=None, urls=None, limit=5,
                  max_characters=12000, session_id=None):
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
            raise self._schema_error("invalid input schema")
        properties = schema["properties"]
        if purpose == "search":
            candidates = {
                "exa": {"query": query, "objective": query, "numResults": limit},
                "parallel": {"objective": query, "search_queries": [query], "session_id": session_id},
                "tavily": {"query": query, "max_results": limit, "search_depth": "basic", "include_raw_content": False},
            }[self.provider]
            core_fields = {"objective", "search_queries"} if self.provider == "parallel" else {"query"}
        elif purpose == "fetch":
            candidates = {
                "exa": {"urls": urls, "maxCharacters": max_characters},
                "parallel": {"urls": urls, "full_content": False, "session_id": session_id},
                "tavily": {"urls": urls, "extract_depth": "basic", "format": "markdown"},
            }[self.provider]
            core_fields = {"urls"}
            if "urls" not in properties and "url" in properties and urls and len(urls) == 1:
                candidates = {**candidates, "url": urls[0]}
                core_fields = {"url"}
        else:
            raise ValueError("Unknown provider operation")
        arguments = {key: value for key, value in candidates.items() if key in properties and value is not None}
        # Check required fields first to make new required arguments actionable.
        self._validate(schema, arguments)
        if not core_fields <= set(arguments):
            raise self._schema_error("no supported %s fields" % purpose)
        return arguments

    def capabilities(self, tools, session_id=None):
        result = {}
        for purpose in ("search", "fetch"):
            try:
                tool = self.select(purpose, tools)
                self.arguments(tool, purpose, query="provider capability probe",
                               urls=["https://example.com/"], session_id=session_id)
                result[purpose] = {"status": "supported", "tool": tool["name"], "execution_verified": False}
            except McpError as error:
                result[purpose] = {"status": "unsupported", **error.details(), "execution_verified": False}
        return result
