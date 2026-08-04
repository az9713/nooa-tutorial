# Guide: Connect an MCP Server to an Agent

**Goal:** give an agent tool access to an external MCP (Model Context Protocol) server, exposed the same way a local method would be.

## Prerequisites

- Read [`concepts/tools-skills-and-mcp.md`](../concepts/tools-skills-and-mcp.md) for what `MCPManager` does under the hood.
- The `mcp` extra installed:

```bash
uv add 'nooa[mcp]'
```

- An MCP server to connect to — either a named/registered one your organization already runs, or connection details (URL + transport) for one you're standing up yourself.

## Steps

### 1. Attach the MCP tool as a class attribute

```python
from nooa import Agent
from nooa.mcp import MCPManager
from nooa.unifiedllm import get_llm_client

llm = get_llm_client("claude-haiku-4-5")

class ConfluenceAgent(Agent, llm=llm):
    """Agent with MCP tool access."""

    confluence_tool = MCPManager.create_from_server("maas-confluence-stg")

    async def respond(self, prompt: str) -> str:
        """Respond to a user message using the Confluence MCP tool."""
        ...
```

`MCPManager.create_from_server(name)` with just a name resolves connection details from your MCP server registry/config. If you're not using named-server resolution, inline the connection details instead:

```python
confluence_tool = MCPManager.create_from_server(
    "maas-confluence-stg",
    url="https://your-mcp-server.example.com/mcp",
    transport="streamable-http",   # or "sse", "stdio"
    headers={},                     # add auth headers here if the server needs them
)
```

### 2. Tell the model to use it in the docstring

The attribute being visible doesn't tell the model *when* to use it — say so explicitly in the task docstring, the same way you would for any other tool method:

```python
    async def respond(self, prompt: str) -> str:
        """Respond to a user message. Use self.confluence_tool to look up
        relevant Confluence pages before answering if the question references
        internal documentation.
        """
        ...
```

### 3. If the server requires OAuth

`src/nooa/mcp/oauth.py` handles the OAuth flow (`OAuthConfig`, `OAuthHandler`, `handle_mcp_oauth`) — consult the MCP server's own docs for what config it expects, and pass the resulting token/handler through however `MCPManager.create_from_server` accepts it for your transport. This is server-specific enough that there's no one-size snippet; the transport (`stdio`/`sse`/`streamable-http`) and auth requirements come from whoever operates the server you're connecting to.

### 4. Run and confirm the tool is actually visible

```bash
uv run python your_agent_script.py
```

Add a quick manual check before trusting the model to find it on its own:

```python
from nooa.agentdoc import doc
agent = ConfluenceAgent()
print(doc(agent))   # confluence_tool should appear in the rendered API
```

### 5. Trace the run to confirm the model actually called it

```bash
uv run nooa start-dev   # in a separate terminal, before running your script
```

Re-run your script, then check `http://localhost:5001` — a successful MCP call shows up as a nested span the same way a local method call would (see [`guides/trace-and-debug-a-run.md`](trace-and-debug-a-run.md)).

## Verification

- `doc(agent)` output includes `confluence_tool` (or whatever attribute name you chose) with its exposed methods.
- The trace for a run that should have used the MCP tool shows a corresponding call span; if it doesn't, the model chose not to call it (see Troubleshooting) rather than the connection failing silently.
- Calling a method on the attribute directly from a plain Python script (outside the agent) succeeds, confirming the connection/auth itself works independent of the agent/model layer:

```python
import asyncio
from nooa.mcp import MCPManager

async def check():
    tool = MCPManager.create_from_server("maas-confluence-stg")
    # exact verification call depends on what the server exposes — check its tool list
    print(tool)

asyncio.run(check())
```

## Troubleshooting

- **Connection/auth error before any tool call happens** — this is failing at the MCP session layer (`connect_to_server()`), not the agent layer. Check the transport/URL/headers, and check `CONNECT_TIMEOUT_SECONDS` (5.0s default) isn't too tight for a slow server.
- **The attribute never shows up in `doc(agent)`** — confirm it isn't accidentally marked `@hidden` or a private (`_`-prefixed) name, and that `MCPManager.create_from_server(...)` didn't raise at class-definition time (class-body exceptions during attribute assignment can be easy to miss if not surfaced clearly — wrap in a try/except while debugging if needed).
- **Model never calls the tool even though it's visible** — same root cause as any unused tool: `doc()` shows the model *that* something exists, but the task docstring is what tells it *when* to use it. Add explicit guidance, as in Step 2.
- **Tool call times out** — default `tool_call_timeout` is 60 seconds per `MCPBaseClient`; pass a longer `timedelta` if the server's operations are legitimately slow.
- General issues: [`troubleshooting/common-issues.md`](../troubleshooting/common-issues.md).
