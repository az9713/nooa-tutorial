# Tools, Skills, and MCP

NOOA has no separate "tool" abstraction, a purpose-built `Skill` class for injecting curated context, and an MCP client for external services — all three end up as ordinary attributes an LLM can call the same way it calls a local method. This doc explains each and how they compose. Tracks `src/nooa/skill.py`, `src/nooa/skill_registry.py`, `src/nooa/tools/*`, `src/nooa/mcp/*`, `src/nooa/library_manager.py`.

## There is no "tool" abstraction

In most agent frameworks, giving a model a capability means writing a function, then separately writing (or generating) a JSON schema describing that function, then registering the schema with the model client. NOOA skips the middle two steps: any regular method on `self` — or any object attached as a class/instance attribute that itself has methods — is automatically visible to `doc(self)` (subject to the [visibility rules](visibility-and-context.md)) and automatically callable from CodeAct-generated Python, because generated code executes with `self` in scope and can just call `self.whatever_method(...)` the way any Python code would.

```python
class InventoryAgent(Agent, llm=llm):
    def get_stock(self, item: str) -> int:      # a "tool" — just a method
        """Get current stock for an item."""
        return self.inventory.get(item, {}).get("stock", 0)
```

Adding a tool is writing a method. Deleting a tool is deleting a method. There's no schema file that can drift out of sync with the implementation, because there is no separate schema.

This same mechanism is why external tools "just work" as class attributes:

```python
class AnalysisAgent(Agent, llm=llm):
    shell = ShellTools()   # external tool object, LLM-callable exactly like a method
```

## Built-in tools (`src/nooa/tools/`)

Shipped ready to attach as instance/class attributes:

| Tool | Class | What it does |
|---|---|---|
| Persistent shell + file ops | `ShellTools` (`shell_tools.py`) | `run()`/`read()`/`replace()`/`write_file()` against a working directory. `run()` on a pure search command (bare grep/rg/egrep) also returns a parsed `.matches` list of `Match` objects ready to feed straight into `replace()` — but only when the anchor set can be proven trustworthy; any ambiguity fails closed to `.matches = None` rather than risking a wrong edit. |
| Todo tracking | `TodoManager` (`todo.py`), items are `Todo` | Structured task list an agent can maintain across a long-running session. |
| Publish to the web | `WebPublisher` (`web_publisher.py`) | Publish agent output as a hosted page. |
| Write new skill libraries | `SkillWriting` (`library_writing_lib.py`) | Lets an agent author persistent skill libraries for itself — part of the self-extending-agent pattern. |
| Write new methods | `MethodWriting` (`method_writing_lib.py`) | Lets an agent define new callable methods on itself at runtime. |

All of these are also registered as installable entry points under `[project.entry-points."nooa.skills"]` in the root `pyproject.toml` (`nemo.shell`, `nemo.todo`, `nemo.web`, `nemo.libwriting`, `nemo.methodwriting`, plus the always-present `nemo.context` → `ContextApi` and `nemo.events` → `EventsApi`), which is what `LibraryManager` (`src/nooa/library_manager.py`) and the skill registry (`src/nooa/skill_registry.py`, `skill_from_module()`) resolve against.

Attach any of them like a normal attribute:

```python
class MyAgent(Agent, llm=llm):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.shell = ShellTools(cwd="/path/to/repo")
```

## `nooa.Skill` and `nooa.TextSkill` — injecting curated context

`Skill` (`src/nooa/skill.py`) is the base class for anything meant to attach to an agent and contribute either behavior (methods, like the built-in tools above) or curated context. `TextSkill` is the common case: point it at a directory containing a `SKILL.md` file (YAML frontmatter with `name`/`description`, plus markdown body) and its content becomes part of the agent's visible context, the moment it's attached as an attribute:

```python
from pathlib import Path
from nooa import TextSkill

class FrontendAgent(Agent, llm=llm):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.frontend_design = TextSkill(path=Path("path/to/skills/frontend-design"))
```

Because visibility follows ordinary Python attribute rules, a skill is discoverable the instant it's attached — no separate registration call, no split between "code" and "knowledge" the way a RAG index or a prompt-management system would impose. Load a whole directory of skills at once by iterating subdirectories that contain a `SKILL.md`:

```python
for entry in sorted(ASSETS.iterdir()):
    if entry.is_dir() and (entry / "SKILL.md").exists():
        setattr(self, entry.name.replace("-", "_"), TextSkill(path=entry))
```

### `@slash_command` — user-invocable commands on a skill

A `Skill` subclass can expose methods as slash commands via `@slash_command("name", argument_hint=..., completions=(...), output_to_agent=True)`. The decorated method receives the raw argument string and returns a prompt string that either gets fed to the agent as a turn (`output_to_agent=True`, the default — use for anything that should actually invoke the LLM) or shown to the user directly with no agent turn spent (`output_to_agent=False` — use for read-only status/list commands). `get_slash_commands(skill)` extracts all `(SlashCommandMeta, bound_method)` pairs from a skill instance; this is the mechanism the TUI's `/command` dispatch is built on (`src/nooa/slash_dispatch.py`).

### Don't confuse this with the repo's `skills/*/SKILL.md` bundles

The eleven `SKILL.md` files under `skills/` at the repository root (`skills/nooa-agent-authoring/`, `skills/nooa-codeact-advanced/`, etc.) are **documentation for a coding agent** (Claude Code, Cursor, Codex) about how to *author* NOOA agents — they are not something a running `nooa.Agent` instance loads. The file format happens to be compatible with `TextSkill` (the repo even ships a validation snippet that loads them as `TextSkill` instances to check frontmatter), but their purpose is entirely different: one teaches a human/coding-agent how to write NOOA code, the other injects domain context into a NOOA agent at runtime. See `skills/README.md` for the full index; `skills/nooa-tools-and-skills/SKILL.md` specifically covers methods-as-tools, built-in tools, MCP, and the `Skill`/`TextSkill` runtime API in more depth than this page.

## MCP (Model Context Protocol)

MCP tools let an agent call external services through a standard protocol instead of a bespoke client per service. Install the extra first:

```bash
uv add 'nooa[mcp]'
```

`MCPManager` (`src/nooa/mcp/tool.py`) is a stateless factory — `MCPManager.create_from_server(name, ...)` — that connects to an MCP server and exposes its tools as a regular attribute:

```python
from nooa.mcp import MCPManager

class ConfluenceAgent(Agent, llm=llm):
    confluence_tool = MCPManager.create_from_server("maas-confluence-stg")

    async def respond(self, prompt: str) -> str:
        """Respond to a user message using the Confluence MCP tool."""
        ...
```

Or inline the connection details rather than relying on named-server config resolution:

```python
confluence_tool = MCPManager.create_from_server(
    "maas-confluence-stg",
    url="https://your-mcp-server.example.com/mcp",
    transport="streamable-http",   # or "sse", "stdio"
    headers={},
)
```

Under the hood, three transport clients implement `MCPBaseClient` (`src/nooa/mcp/client.py`): `MCPSSEClient`, `MCPStdioClient`, `MCPStreamableHTTPClient` (dispatched via `create_mcp_client()`), each wrapping a `ClientSession` from the `mcp` SDK. `MCPOAuth`-related helpers (`src/nooa/mcp/oauth.py` — `OAuthConfig`, `OAuthHandler`, `OAuthToken`, `handle_mcp_oauth`) handle the OAuth flow for servers that require it. `tool_call_timeout` defaults to 60 seconds per client; the initial connection has its own shorter budget (`CONNECT_TIMEOUT_SECONDS = 5.0`), matching the MCP SDK's own SSE transport default.

The design payoff, stated in `examples/README.md`: **MCP servers surface as regular `self.<name>` attributes** — the model calls them the same way it calls a local method, so external services never become a second-class citizen relative to code you wrote yourself.

## Multimodal media as a capability

Not a tool in the calling sense, but worth noting alongside: `src/nooa/media.py` defines `Media`/`Image`/`Audio`/`Video`/`File` types that generation methods can accept as parameters or produce as part of their output, letting an agent reason over or emit non-text content within the same method-call model as everything else. See `examples/quickstart/13_multimodal.py`.

## Related

- [`concepts/agents-and-generation-methods.md`](agents-and-generation-methods.md) — how CodeAct's `execute_python()` loop actually calls these methods/attributes.
- [`concepts/execution-and-storage.md`](execution-and-storage.md) — the sandboxing/restrictions layer that generated code calling these tools runs under.
- [`guides/connect-an-mcp-server.md`](../guides/connect-an-mcp-server.md) — step-by-step for wiring up an MCP server.
- `skills/nooa-tools-and-skills/SKILL.md`, `skills/nooa-self-extending/SKILL.md` in the repo — coding-agent-facing references for this material.
