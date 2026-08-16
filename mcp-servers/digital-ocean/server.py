#!/usr/bin/env python3
import asyncio
import json
import os

import httpx
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

DO_API_BASE = "https://inference.do-ai.run/v1"

_VALID_ROLES = {"system", "user", "assistant", "tool", "function"}

server = Server("digital-ocean-inference")


def _headers() -> dict:
    key = os.environ.get("DO_MODEL_KEY")
    if not key:
        raise RuntimeError(
            "DO_MODEL_KEY environment variable is not set; "
            "cannot authenticate to DigitalOcean inference API."
        )
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _validate_messages(messages: list) -> str | None:
    """Return an error string if messages are malformed, else None."""
    if not isinstance(messages, list) or len(messages) == 0:
        return "messages must be a non-empty array"
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            return f"messages[{i}] must be an object"
        role = msg.get("role")
        content = msg.get("content")
        if not isinstance(role, str) or role not in _VALID_ROLES:
            return (
                f"messages[{i}].role must be one of "
                f"{sorted(_VALID_ROLES)}, got {role!r}"
            )
        if not isinstance(content, str):
            return f"messages[{i}].content must be a string, got {type(content).__name__}"
    return None


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="do_list_models",
            description="List available DigitalOcean Serverless Inference models.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="do_chat_completion",
            description="Run a chat completion against a DigitalOcean Serverless Inference model.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Model ID (e.g. kimi-1.5, deepseek-chat)",
                    },
                    "messages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {
                                    "type": "string",
                                    "enum": list(_VALID_ROLES),
                                },
                                "content": {"type": "string"},
                            },
                            "required": ["role", "content"],
                        },
                    },
                    "max_tokens": {"type": "integer", "default": 1024},
                    "temperature": {"type": "number", "default": 0.7},
                },
                "required": ["model", "messages"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    def error(msg: str) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=f"Error: {msg}")]

    try:
        headers = _headers()
    except RuntimeError as exc:
        return error(str(exc))

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            if name == "do_list_models":
                resp = await client.get(f"{DO_API_BASE}/models", headers=headers)
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    return error(
                        f"DO API error {exc.response.status_code}: {exc.response.text}"
                    )
                return [types.TextContent(type="text", text=json.dumps(resp.json(), indent=2))]

            if name == "do_chat_completion":
                model = arguments.get("model")
                if not model or not isinstance(model, str):
                    return error("model must be a non-empty string")

                messages = arguments.get("messages")
                validation_error = _validate_messages(messages)
                if validation_error:
                    return error(validation_error)

                payload: dict = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": arguments.get("max_tokens", 1024),
                    "temperature": arguments.get("temperature", 0.7),
                }
                resp = await client.post(
                    f"{DO_API_BASE}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    return error(
                        f"DO API error {exc.response.status_code}: {exc.response.text}"
                    )
                return [types.TextContent(type="text", text=json.dumps(resp.json(), indent=2))]

            return error(f"Unknown tool: {name}")

    except httpx.TimeoutException:
        return error("Request timed out after 120 s")
    except httpx.RequestError as exc:
        return error(f"Network error: {exc}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
