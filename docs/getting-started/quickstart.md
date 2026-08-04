# Quickstart

Working agent in under 15 minutes. This walks through the first four steps of the framework's own progressive tutorial ([`examples/README.md`](../../examples/README.md)); it stops at "your first agent, structured output, methods-as-tools, and choosing a strategy" — enough to write a real agent. For the full 11-step tutorial plus advanced topics (skills, MCP, sandboxing, self-extending agents), continue to [`getting-started/onboarding.md`](onboarding.md).

Complete [`getting-started/prerequisites.md`](prerequisites.md) first (Python 3.12+, `uv`, an LLM API key).

## Step 1: Install

In a new or existing project:

```bash
uv init my-agent-project
cd my-agent-project
uv add nooa
```

Or with pip: `pip install nooa`.

Expected output ends with something like:

```
Resolved N packages in ...
Installed N packages in ...
 + nooa==0.0.x
```

## Step 2: Choose a model

NOOA wraps [LiteLLM](https://docs.litellm.ai/), so any LiteLLM model string works. Pick one based on which API key you set in Prerequisites:

```python
from nooa.unifiedllm import get_llm_client

llm = get_llm_client("claude-haiku-4-5")                                           # needs ANTHROPIC_API_KEY
# llm = get_llm_client("gpt-5-mini")                                                # needs OPENAI_API_KEY
# llm = get_llm_client("ollama_chat/qwen3:1.7b", api_base="http://localhost:11434")  # local, no key
```

## Step 3: Your first generation method

Create `feedback_agent.py`:

```python
import asyncio
from nooa import Agent
from nooa.unifiedllm import get_llm_client

llm = get_llm_client("claude-haiku-4-5")


class FeedbackAgent(Agent, llm=llm):
    """You are an agent specializing in analyzing customer feedback."""

    async def analyze_feedback(self, text: str) -> str:
        """Analyze customer feedback for sentiment and key topics in one sentence."""
        ...


async def main():
    agent = FeedbackAgent()
    result = await agent.analyze_feedback("Great product, but shipping was slow")
    print(result)


asyncio.run(main())
```

Run it:

```bash
uv run python feedback_agent.py
```

Expected output: one sentence of sentiment/topic analysis, e.g. `Positive sentiment overall, with a specific concern about slow shipping speed.` (exact wording varies by model — that's expected, it's a live LLM call).

If you're working inside the cloned repo instead of a fresh project, the same file is checked in — run it directly:

```bash
uv run python examples/quickstart/01_first_generation_method.py
```

**What just happened:** `analyze_feedback` has an `...` body, so the framework intercepted the call, built a prompt from the method's docstring plus its arguments, sent it to the model attached via `llm=llm`, and returned the model's text. Rename the method to `analyze_feedback_briefly` and re-run — the output changes, because the method name is part of the prompt. See [`concepts/agents-and-generation-methods.md`](../concepts/agents-and-generation-methods.md).

## Step 4: Structured output

Swap the return type for a Pydantic model and the framework validates the model's output against it, auto-retrying with the validation error fed back to the model if it doesn't match:

```python
from typing import Literal
from pydantic import BaseModel, Field
from nooa import Agent
from nooa.unifiedllm import get_llm_client

llm = get_llm_client("claude-haiku-4-5")


class FeedbackAnalysis(BaseModel):
    sentiment: Literal["positive", "negative", "neutral", "mixed"]
    topics: list[str]
    urgency: Literal["low", "medium", "high"]
    summary: str
    confidence: float = Field(ge=0, le=1)


class FeedbackAgent(Agent, llm=llm):
    """Agent for analyzing customer feedback with structured output."""

    async def analyze_feedback(self, text: str) -> FeedbackAnalysis:
        """Analyze customer feedback comprehensively."""
        ...
```

Run the checked-in version:

```bash
uv run python examples/quickstart/02_structured_outputs.py
```

Expected output: a printed `FeedbackAnalysis(sentiment=..., topics=[...], urgency=..., summary='...', confidence=0.xx)` — a real, type-valid Python object, not a raw string you'd have to parse yourself.

## Step 5: Methods are tools — no separate tool abstraction

Add a plain Python helper method and the LLM can call it from inside a generation method, with zero registration:

```python
from typing import TypedDict
from nooa import Agent
from nooa.unifiedllm import get_llm_client

llm = get_llm_client("claude-haiku-4-5")


class Result(TypedDict):
    can_fulfill: bool
    total_cost: float
    unavailable_items: list[str]


class InventoryAgent(Agent, llm=llm):
    """You are an agent that checks inventory using deterministic helper methods."""

    def __init__(self):
        super().__init__()
        self.inventory = {
            "apple": {"stock": 50, "price": 0.75},
            "banana": {"stock": 30, "price": 0.50},
            "orange": {"stock": 0, "price": 0.80},
        }

    def get_stock(self, item: str) -> int:
        """Get current stock for an item."""
        return self.inventory.get(item, {}).get("stock", 0)

    def get_price(self, item: str) -> float:
        """Get price for an item."""
        return self.inventory.get(item, {}).get("price", 0.0)

    async def can_fulfill_order(self, items: list[str], budget: float) -> Result:
        """Check if order can be fulfilled within budget."""
        ...
```

```bash
uv run python examples/quickstart/03_codeact_tools.py
```

Expected output: a `Result` dict — the model wrote Python that called `get_stock`/`get_price` on `self` to compute `can_fulfill`, `total_cost`, and `unavailable_items`, without you writing a tool schema anywhere. This is the default strategy, `CodeActStrategy`, at work — see Step 6.

## Step 6: Choose how a method thinks

Attach `@strategy(...)` to switch between the iterative CodeAct loop (default, good for tasks needing tool use or multi-step reasoning) and single-shot `PredictStrategy` (faster, good for classification/extraction with no iteration needed):

```python
from nooa import Agent
from nooa.decorators import strategy
from nooa.strategies import CodeActStrategy, PredictStrategy
from nooa.config import CodeActConfig
from nooa.unifiedllm import get_llm_client

llm = get_llm_client("claude-haiku-4-5")


class AnalysisAgent(Agent, llm=llm):
    """Agent demonstrating different strategy options."""

    @strategy(PredictStrategy())
    async def classify_sentiment(self, text: str) -> str:
        """Classify as positive, negative, or neutral."""
        ...

    @strategy(CodeActStrategy(config=CodeActConfig(max_iterations=10)))
    async def perform_task(self, request: str) -> str:
        """Perform the task requested by the user and provide a friendly response."""
        ...
```

```bash
uv run python examples/quickstart/04_strategies.py
```

Expected output: both methods run to completion and print their results; `classify_sentiment` makes exactly one LLM call, `perform_task` may make several (up to `max_iterations`). See [`concepts/strategies.md`](../concepts/strategies.md) and [`guides/choose-a-strategy.md`](../guides/choose-a-strategy.md) for the full decision guide.

## Step 7: Watch what your agent did

Every method call — LLM-driven or not — is traced automatically. Start the trace viewer in one terminal:

```bash
uv run nooa start-dev
```

Expected output:

```
Uvicorn running on http://127.0.0.1:5001 ...
```

Open `http://localhost:5001` in a browser, then re-run any script from the steps above in another terminal — the run appears in the viewer with the full call tree, LLM prompts/responses, and (for CodeAct) the executed code and its output. If the viewer isn't running, tracing is silently a no-op — no configuration needed either way. See [`concepts/tracing-and-observability.md`](../concepts/tracing-and-observability.md).

## You now have

- A working install with a model wired up.
- One generation method calling an LLM (Step 3).
- Typed, validated structured output (Step 4).
- Deterministic helper methods callable by the model with no tool schema (Step 5).
- Per-method strategy selection (Step 6).
- A live view of everything the agent did (Step 7).

Next: [`getting-started/onboarding.md`](onboarding.md) walks through the same territory as a guided narrative for someone with zero prior context, and continues into context blocks, tracing config, dynamic prompts, summarization, skills, and MCP — the rest of the 11-step tutorial in [`examples/README.md`](../../examples/README.md).
