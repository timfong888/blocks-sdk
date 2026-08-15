#!/usr/bin/env node
/**
 * DigitalOcean Serverless Inference MCP Server
 *
 * Exposes DigitalOcean's OpenAI-compatible inference API as MCP tools.
 * Requires: Node.js 18+ (built-in fetch). No npm dependencies.
 *
 * Environment variables:
 *   DO_MODEL_KEY   - required; your DigitalOcean Model Access Key
 *   DO_BASE_URL    - optional; defaults to https://inference.do-ai.run/v1
 */

const DO_BASE_URL = (process.env.DO_BASE_URL || "https://inference.do-ai.run/v1").replace(/\/$/, "");
const DO_MODEL_KEY = process.env.DO_MODEL_KEY;

if (!DO_MODEL_KEY) {
  process.stderr.write("Error: DO_MODEL_KEY environment variable is required\n");
  process.exit(1);
}

const authHeaders = {
  Authorization: `Bearer ${DO_MODEL_KEY}`,
  "Content-Type": "application/json",
};

// ── Tool definitions ──────────────────────────────────────────────────────────

const TOOLS = [
  {
    name: "do_list_models",
    description: "List all models available on the DigitalOcean Serverless Inference endpoint.",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "do_chat_completion",
    description:
      "Send a chat completion request to DigitalOcean Serverless Inference. Returns the assistant reply text.",
    inputSchema: {
      type: "object",
      required: ["model", "messages"],
      properties: {
        model: {
          type: "string",
          description: "DigitalOcean model ID (e.g. from do_list_models) or alias. Aliases: kimi, kimi3/kimi-latest, deepseek, deepseek-pro, glm, claude, claude-opus, claude-haiku, gpt4o, gpt5, o3, llama, qwen, qwen-coder, router, router-code, router-write",
        },
        messages: {
          type: "array",
          description: "Conversation messages",
          items: {
            type: "object",
            required: ["role", "content"],
            properties: {
              role: { type: "string", enum: ["system", "user", "assistant"] },
              content: { type: "string" },
            },
          },
        },
        temperature: {
          type: "number",
          description: "Sampling temperature 0–2 (default 1)",
        },
        max_tokens: {
          type: "integer",
          description: "Maximum tokens to generate",
        },
      },
    },
  },
];

// ── Model alias resolution ────────────────────────────────────────────────────

// Short aliases → full DO model IDs.
// Run do_list_models to see the authoritative list once DO_MODEL_KEY is set.
// Last verified against live endpoint: 2026-08-15 (76 models)
const MODEL_ALIASES = {
  // Kimi (reasoning — require temperature=1)
  kimi:          "kimi-k3",
  "kimi-latest": "kimi-k3",
  kimi3:         "kimi-k3",
  "kimi-stable": "kimi-k2.5",

  // DeepSeek
  deepseek:      "deepseek-4-flash",
  "deepseek-pro": "deepseek-v4-pro-0813",

  // GLM
  glm:           "glm-5.2",

  // Anthropic / Claude
  claude:        "anthropic-claude-5-sonnet",
  "claude-opus": "anthropic-claude-opus-5",
  "claude-haiku": "anthropic-claude-haiku-4.5",

  // OpenAI
  gpt4o:         "openai-gpt-4o",
  gpt5:          "openai-gpt-5",
  o3:            "openai-o3",

  // Meta Llama
  llama:         "llama-4-maverick",

  // Qwen
  qwen:          "qwen3.8-max",
  "qwen-coder":  "qwen3-coder-flash",

  // Routers (auto-select best model for task)
  router:        "router:general",
  "router-code": "router:software-engineering",
  "router-write": "router:writing",
};

function resolveModel(id) {
  if (!id || typeof id !== "string") return id;
  return MODEL_ALIASES[id.toLowerCase()] ?? id;
}

// ── Tool handlers ─────────────────────────────────────────────────────────────

async function handleListModels() {
  const res = await fetch(`${DO_BASE_URL}/models`, { headers: authHeaders });
  if (!res.ok) {
    throw new Error(`DO API error ${res.status}: ${await res.text()}`);
  }
  const data = await res.json();
  return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
}

async function handleChatCompletion({ model, messages, temperature, max_tokens }) {
  const resolvedModel = resolveModel(model);
  const body = { model: resolvedModel, messages };
  if (temperature !== undefined) body.temperature = temperature;
  if (max_tokens !== undefined) body.max_tokens = max_tokens;

  const res = await fetch(`${DO_BASE_URL}/chat/completions`, {
    method: "POST",
    headers: authHeaders,
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    throw new Error(`DO API error ${res.status}: ${await res.text()}`);
  }
  const data = await res.json();
  const text = data.choices?.[0]?.message?.content ?? JSON.stringify(data);
  return { content: [{ type: "text", text }] };
}

// ── MCP JSON-RPC protocol over stdio ─────────────────────────────────────────

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function success(id, result) {
  send({ jsonrpc: "2.0", id, result });
}

function error(id, code, message) {
  send({ jsonrpc: "2.0", id, error: { code, message } });
}

async function dispatch(msg) {
  const { id, method, params } = msg;

  if (method === "initialize") {
    return success(id, {
      protocolVersion: "2024-11-05",
      capabilities: { tools: {} },
      serverInfo: { name: "do-inference", version: "1.0.0" },
    });
  }

  if (method === "notifications/initialized") return;

  if (method === "tools/list") {
    return success(id, { tools: TOOLS });
  }

  if (method === "tools/call") {
    const { name, arguments: args = {} } = params ?? {};
    try {
      let result;
      if (name === "do_list_models") result = await handleListModels();
      else if (name === "do_chat_completion") result = await handleChatCompletion(args);
      else return error(id, -32601, `Unknown tool: ${name}`);
      return success(id, result);
    } catch (err) {
      return success(id, {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      });
    }
  }

  if (id !== undefined) {
    error(id, -32601, `Method not found: ${method}`);
  }
}

// Read newline-delimited JSON from stdin
let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", async (chunk) => {
  buffer += chunk;
  const lines = buffer.split("\n");
  buffer = lines.pop();
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const msg = JSON.parse(trimmed);
      await dispatch(msg);
    } catch {
      // ignore malformed input
    }
  }
});

process.stdin.on("end", () => process.exit(0));
process.stderr.write(`DigitalOcean Inference MCP server started (${DO_BASE_URL})\n`);
