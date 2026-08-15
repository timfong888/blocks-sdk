#!/usr/bin/env python3
import asyncio
import json
import os

import httpx
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

DO_API_BASE = "https://inference.do-ai.run/v1"

server = Server("digital-ocean-inference")


def _headers() -> dict:
    key = os.environ.get("DO_MODEL_KEY", "")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


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
                                "role": {"type": "string"},
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
    async with httpx.AsyncClient(timeout=120.0) as client:
        if name == "do_list_models":
            resp = await client.get(f"{DO_API_BASE}/models", headers=_headers())
            resp.raise_for_status()
            return [types.TextContent(type="text", text=json.dumps(resp.json(), indent=2))]

        if name == "do_chat_completion":
            payload: dict = {
                "model": arguments["model"],
                "messages": arguments["messages"],
                "max_tokens": arguments.get("max_tokens", 1024),
                "temperature": arguments.get("temperature", 0.7),
            }
            resp = await client.post(
                f"{DO_API_BASE}/chat/completions",
                headers=_headers(),
                json=payload,
            )
            resp.raise_for_status()
            return [types.TextContent(type="text", text=json.dumps(resp.json(), indent=2))]

        raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
