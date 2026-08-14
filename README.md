# blocks-sdk

Custom inference provider MCP servers for the Blocks workspace.

## Servers

### `mcp-servers/digital-ocean`

MCP server wrapping [DigitalOcean Serverless Inference](https://docs.digitalocean.com/products/inference/how-to/si-endpoints/).
Exposes `do_list_models` and `do_chat_completion` tools.

**Required secret:** `DO_MODEL_KEY` — generate from the DigitalOcean control panel under **Inference → Serverless Inference → API Keys**.

## Usage in Blocks

Once registered as an MCP server in the workspace, reference models via the `/do` and `/aurora` skills:

```
@blocks /do /kimi    — DigitalOcean + latest Kimi model
@blocks /do /deepseek — DigitalOcean + latest DeepSeek model
@blocks /aurora /deepseek — Aurora + DeepSeek V4 Flash
```
