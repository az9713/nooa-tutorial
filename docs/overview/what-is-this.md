# What Is NOOA?

NOOA (NVIDIA-labs OO Agents) is a Python framework where an AI agent is a Python object: its fields are its state, its methods are its capabilities, its docstrings are its prompts, and its type annotations are the contract the LLM's output must satisfy.

## The one-sentence answer

An agent is a `class` that subclasses `nooa.Agent`; any method whose body is just `...` is executed by an LLM at call time instead of by the Python interpreter, and everything else about the class — fields, helper methods, type hints, docstrings — is the same Python you already know.

```python
from nooa import Agent

class SupportAgent(Agent):
    """You are a support agent."""

    order_db: OrderDB                                          # state — a typed field

    def is_refund_eligible(self, order: Order) -> bool:        # capability — ordinary Python
        return order.delivered and order.days_since_delivery <= 30

    async def triage(self, message: str, order: Order) -> Ticket:  # capability — LLM-driven
        """Create a typed support ticket."""
        ...
```

`triage` has an ellipsis body, so the framework's runtime intercepts the call, builds a prompt from the docstring plus the agent's visible state and methods, sends it to an LLM, and returns a value that is guaranteed to satisfy the `Ticket` type annotation. `is_refund_eligible` has a real body, so it just runs as Python — and because it's a regular method on `self`, the LLM can call it too, without any separate tool-registration step.

## Why this exists

Most agent frameworks split an agent's behavior into several separate abstractions that have to be kept in sync by hand: a prompt template lives in one file, a tool schema lives in another, the orchestration logic that wires them together lives in a third. NOOA's premise is that Python's own class system already has the vocabulary needed to describe an agent — state, methods, types, docstrings — and that re-deriving a parallel vocabulary (prompt managers, tool registries, schema definitions) is unnecessary indirection. The [paper](https://arxiv.org/abs/2607.20709) behind the project ("NVIDIA OO Agents: Native Python Object-Oriented Agents") frames this as bringing agent development back into the reach of ordinary software engineering practice — testing, refactoring, version control, and code review all work the way they do for any other Python code, because an agent *is* Python code.

The project's own `pyproject.toml` describes it more mechanically as a "code-generating agent orchestration system with event sourcing and serialized execution" — which is the implementation-level view of the same idea: agents act primarily by writing and executing Python (the CodeAct pattern), every state change is recorded as an event so the full history of a run can be replayed and inspected, and generation calls are serialized per agent so that concurrent LLM calls can't interleave and corrupt shared state.

## The mental model

Four ideas cover almost everything else in this documentation set:

1. **`...` bodies are LLM-driven; real bodies are deterministic.** A method with an ellipsis body becomes a *generation method* — the metaclass detects the `...` at class-definition time (via `nooa.ellipsis_detection.has_ellipsis_body`) and wraps it so that calling it triggers a *strategy* (see below) instead of running a function body. A method with a real body just runs, like any other Python method.

2. **The signature and docstring are the prompt.** The method name, parameter names and types, and the docstring together are what the LLM sees as its task. There is no separate prompt-template file to keep in sync — renaming `analyze_feedback` to `analyze_feedback_briefly` changes the model's behavior with no other code change, because the method's identity *is* part of its instruction.

3. **The return type annotation is the contract.** Whatever type a generation method is annotated to return — a `str`, a Pydantic model, a `dataclass`, a `TypedDict`, a `list[...]` — the framework validates the LLM's output against it and retries with the validation error fed back to the model until it satisfies the type, or until retries are exhausted. Callers of a generation method never see "the model produced text that might not parse"; they see a value of the declared type or an exception.

4. **A *strategy* decides how the LLM solves the task, not what the task is.** Whether the LLM answers in one shot (`PredictStrategy`) or writes and executes Python in an iterative REPL loop to get there (`CodeActStrategy`, the default) is an execution detail attached via `@strategy(...)`. Swapping strategies never changes a method's signature or its callers — it only changes how expensive/capable/deterministic solving it is. See [`concepts/strategies.md`](../concepts/strategies.md).

## Architecture overview

At a high level, calling a generation method flows through four layers:

```
 caller: await agent.analyze(text)
        │
        ▼
 ┌─────────────────────────────────────────────────────────┐
 │ AgentMeta (metaclass)                                    │  detects `...` at class definition,
 │  src/nooa/metaclass.py                                   │  wraps the method
 └─────────────────────────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────────────────────────┐
 │ ActorRuntime (per agent instance)                        │  serializes generation calls
 │  src/nooa/runtime/actor.py                                │  (event-sourced, one LLM turn
 │                                                            │  at a time per agent), builds
 │                                                            │  the prompt from context blocks
 │                                                            │  + event history
 └─────────────────────────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────────────────────────┐
 │ GenerationStrategy (PredictStrategy / CodeActStrategy /  │  owns the actual "how": one-shot
 │  ReflexionStrategy / ...)                                │  structured call, or an iterative
 │  src/nooa/strategies/*                                    │  Python REPL loop with tool calls
 └─────────────────────────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────────────────────────┐
 │ UnifiedLLM (LiteLLM-backed client)                        │  talks to Anthropic / OpenAI /
 │  src/nooa/unifiedllm/*                                     │  Ollama / vLLM / any LiteLLM
 │                                                            │  provider
 └─────────────────────────────────────────────────────────┘
```

Two more subsystems sit alongside this call path rather than inside it:

- **Context blocks** (`src/nooa/context_blocks/`, via `self.context`) let you (and the LLM) pin labelled information into every future prompt — either as a static value or a Python expression re-evaluated each turn — without threading it through every method call.
- **Tracing** (`src/nooa/tracing/`) instruments every method call — generation and deterministic, public and private — as a nested OpenTelemetry span, exported to a local trace viewer (`nooa start-dev`, port 5001 by default) or to OTLP/Langfuse/Phoenix/JSONL. It is entirely additive: if nothing is listening, tracing silently no-ops.

For code execution specifically (the default `CodeActStrategy`), a fifth layer applies: generated Python is run through an AST validator and a module deny-list (`src/nooa/runtime/code_validator.py`, `src/nooa/runtime/restrictions.py`) before execution, either in-process or in an isolated sandboxed worker (`src/nooa/runtime/sandbox/`). See [`concepts/execution-and-storage.md`](../concepts/execution-and-storage.md) for why this validation is explicitly **not** a security boundary by itself.

## How it all fits together

Put the four ideas and the five layers together and a call like `await agent.triage(message, order)` reads as: the metaclass already knows, from class-definition time, that `triage` needs generation; the actor runtime takes an exclusive lock on the agent (so two concurrent calls to the same agent can't interleave LLM turns), assembles a prompt out of the agent's context blocks (state, docstring-derived system prompt, any pinned context) and its event history, and hands that to whatever strategy is attached to `triage` (default `CodeActStrategy` unless overridden with `@strategy(...)`); the strategy calls the LLM through `UnifiedLLM`, and if it's CodeAct, loops — letting the model write Python that calls other methods on `self` (which are themselves ordinary tools, needing no schema) — until the model calls `return_result(...)` with a value the framework validates against `Ticket`; every one of those steps is recorded as an event and, if tracing is active, as a span you can inspect afterward in the trace viewer.

This is also why the framework bills itself as research software with a strong warning attached: because the default execution mode lets the model write and run arbitrary Python, and the in-process guardrails (AST checks, deny-lists) are defense-in-depth rather than a containment boundary, NOOA agents that execute generated code should run inside OS-level isolation (a container, VM, or [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)) — see [`concepts/execution-and-storage.md`](../concepts/execution-and-storage.md) for the specifics.

Continue to [`overview/key-concepts.md`](key-concepts.md) for a glossary of every term used elsewhere in these docs, or jump straight to [`getting-started/quickstart.md`](../getting-started/quickstart.md) to run something.
