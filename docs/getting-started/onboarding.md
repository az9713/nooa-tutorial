# Onboarding: Zero to Productive with NOOA

This is written for someone who has never touched NOOA and wants the full mental model before writing anything serious — not just the fastest path to a working script (that's the [Quickstart](quickstart.md)). Budget 45–60 minutes, including running the commands.

## Start with an analogy

Think about how you'd normally build a customer-support triage bot without any agent framework. You'd probably end up with, at minimum: a prompt template file (string with placeholders), a tool-schema file (JSON describing what functions the model can call, kept in sync with the actual function code by hand), a Python module with the actual functions, and some orchestration code gluing all three together and parsing the model's output back into something your code can use. Four things, four places they can drift out of sync.

NOOA's bet is that this is one thing wearing four hats, and Python already has a name for "state plus behavior plus a documented interface": a class. So in NOOA, the prompt template *is* the docstring on a method. The tool schema *is* the method signature. The functions *are* regular methods on the same class. The parsing/validation *is* the return type annotation. One file, one class, one thing to keep in sync with itself — because it can't drift out of sync with itself.

That's the whole idea. Everything else in the framework — strategies, context blocks, tracing, visibility rules — exists to make that idea work well at scale (long conversations, many tools, multiple cooperating agents, production observability) rather than to add new concepts on top of it.

## Build the mental model before touching code

**An agent is an object, not a chatbot.** `FeedbackAgent()` creates an instance the same way any Python class does. It has an identity, it has state (instance attributes), and you call methods on it. There's no hidden global "conversation" — the conversation state lives in *that instance's* event history.

**A method's body tells you what kind of method it is.** Write a real body (`return order.delivered and ...`) and it's just Python — runs instantly, deterministically, no network call. Write `...` and it's a generation method — the framework hands it to an LLM. You can mix both freely on the same class, and that mixing is the whole point: put anything you *can* compute deterministically in a real method (parsing, math, database lookups), and reserve `...` for the genuinely fuzzy judgment calls (sentiment, summarization, "does this response sound polite").

**The model doesn't see your source code — it sees `doc()`.** When a generation method runs, the framework doesn't hand the LLM your Python file. It renders a text description of the agent's current state and its available methods (via a function called `doc()`), plus the docstring of the method being called, plus the conversation history so far. Every design decision about "what should the model be able to see/do" routes through this rendering step — which is why hiding something (an internal `_private` helper, a `secrets` field) is as simple as a Python naming convention or a decorator, not a separate permissions system to configure.

**Iteration happens inside a Python REPL, not inside the chat loop.** The default strategy, CodeAct, doesn't ask the model "what's your final answer" in one shot. It gives the model a code-execution tool and lets it write and run Python — including calling other methods on the same agent — across multiple turns, observing output each time, until it's ready to call `return_result(value)`. This is why NOOA agents can use "tools" that are just plain methods: the model isn't picking a tool from a fixed menu via structured function-calling, it's writing `self.get_stock("apple")` the same way you would.

## Run the guided walkthrough

Now put hands on keyboard. If you haven't already, do [Prerequisites](prerequisites.md) (Python 3.12+, `uv`, an API key) and clone the repo:

```bash
git clone https://github.com/NVIDIA-NeMo/labs-OO-Agents.git
cd labs-OO-Agents
uv sync --group dev
export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY / GEMINI_API_KEY
```

Work through the numbered tutorial in order — each script is standalone and runnable:

```bash
uv run python examples/quickstart/01_first_generation_method.py   # your first `...` method
uv run python examples/quickstart/02_structured_outputs.py        # Pydantic return types, validated
uv run python examples/quickstart/03_codeact_tools.py             # plain methods as tools
uv run python examples/quickstart/04_strategies.py                # PredictStrategy vs CodeActStrategy
uv run python examples/quickstart/05_progressive_disclosure.py    # doc(obj) for unknown types
uv run nooa start-dev &                                           # trace viewer on :5001, run in background
uv run python examples/quickstart/06_tracing.py                   # then open http://localhost:5001
uv run python examples/quickstart/07_dynamic_prompts.py           # {self.attr} templating in docstrings
uv run python examples/quickstart/08_context_blocks.py            # self.context[...] pinned prompt state
uv run python examples/quickstart/09_summarization.py             # bounding history on long-running agents
uv run python examples/quickstart/10_skills.py                    # TextSkill — attach curated context
uv run python examples/quickstart/11_mcp.py                       # MCP tools as self.<name> attributes
```

For each one, before running it: read the file, guess what it'll print, then run it and see if you were right. That loop is the fastest way to internalize "the method signature and docstring are the prompt" — you'll be surprised at least once by how much the model infers from a name alone.

Each step is explained in full prose (with the "key insight" that step demonstrates) in [`examples/README.md`](../../examples/README.md); Steps 1–6 are also walked through with expected output in the [Quickstart](quickstart.md).

## A realistic end-to-end scenario

Here's how the pieces compose into something closer to a real agent — a technical interview bot that runs a multi-turn conversation, keeps its own notes, and doesn't blow up the context window no matter how long the interview runs:

```python
from nooa import Agent, hidden
from nooa.agentdoc import spec
from nooa.agents import TokenBudgetSummarizer
from nooa.config import TokenBudgetConfig
from nooa.unifiedllm import get_llm_client

llm = get_llm_client("claude-sonnet-4-5-20250514")


class InterviewAgent(Agent, llm=llm):
    """A technical interviewer conducting a multi-turn conversation."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._topics_covered: list[str] = []
        spec(self, "events", hidden=False)   # let the model query its own history

    @hidden
    def _log_topic(self, topic: str) -> None:
        self._topics_covered.append(topic)

    async def ask(self, candidate_answer: str) -> str:
        """Continue the technical interview based on the candidate's latest answer.

        Ask a relevant follow-up or move to a new topic. Track what has been covered
        using self._log_topic(...) via self.events if you need to check history.
        """
        ...

    async def evaluate(self) -> str:
        """Based on the full interview so far, provide a brief candidate evaluation."""
        ...


async def run_interview():
    agent = InterviewAgent()
    TokenBudgetSummarizer.install(agent, config=TokenBudgetConfig(max_tokens=1000))

    for candidate_answer in [
        "I'd use a hash map for O(1) lookups.",
        "Big-O for that approach is O(n) time, O(n) space.",
        # ... potentially dozens more turns ...
    ]:
        question = await agent.ask(candidate_answer)
        print(question)

    print(await agent.evaluate())
```

Walk through what's happening, mapping back to the mental model above:

1. **`ask` and `evaluate` are generation methods** — both `...`-bodied, both driven by the class docstring (system prompt) plus their own docstrings (task instructions).
2. **`_log_topic` is `@hidden`** — a private deterministic helper the *developer* can call from orchestration code, invisible to the model. (In this sketch it isn't actually invoked by `ask`'s generated code, since `ask` is LLM-driven CodeAct and would need to be told about it via `doc(self)` — the point here is just to show the visibility mechanism, not a complete working agent.)
3. **`spec(self, "events", hidden=False)`** exposes the agent's own conversation history to itself, so `evaluate()` can reason over everything `ask()` produced across many turns — without you manually threading a transcript variable through every call.
4. **`TokenBudgetSummarizer.install(agent, ...)`** means this conversation can run for an arbitrary number of turns: once accumulated event history crosses `max_tokens=1000`, older turns get compressed automatically, so `ask()` on turn 50 doesn't choke the context window the way a naive "just append every message" chat loop would.
5. **Nothing here mentions a specific model's function-calling API, a JSON tool schema, or a prompt template engine.** That's not an accident — it's the payoff of the "one class, one thing to keep in sync" bet from the top of this doc.

## Where to go next

- Building a real agent right now? [`guides/write-your-first-agent.md`](../guides/write-your-first-agent.md).
- Need the deeper "why" behind strategies, visibility, or execution safety? Start at [`concepts/agents-and-generation-methods.md`](../concepts/agents-and-generation-methods.md) and follow its links.
- Something not working the way this doc implied it should? [`troubleshooting/common-issues.md`](../troubleshooting/common-issues.md).
- Want the terse, rule-based version of everything above for quick lookup while coding? [`../AGENTS.md`](../../AGENTS.md) — written for coding agents, equally useful as a cheat sheet for you.
