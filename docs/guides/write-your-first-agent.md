# Guide: Write Your First Agent

**Goal:** design and implement a small, real NOOA agent from scratch — not the single-method toy from the Quickstart, but something with multiple methods, a mix of deterministic and LLM-driven behavior, and a sensible split between orchestration and generation.

## Prerequisites

- Completed [`getting-started/prerequisites.md`](../getting-started/prerequisites.md) (Python 3.12+, `uv`, an LLM API key).
- Read [`concepts/agents-and-generation-methods.md`](../concepts/agents-and-generation-methods.md) — this guide assumes you know what a generation method is and what `...` does.

## Steps

### 1. Decide what's deterministic and what's fuzzy

Before writing any class, list the operations your agent needs and mark each one either "computable" (parsing, math, lookups, formatting — things you could write a unit test for) or "judgment call" (classification, summarization, "does this sound right"). This split maps directly onto the two kinds of methods you'll write: computable → real Python bodies; judgment calls → `...` bodies. Getting this split right up front avoids the most common first-agent mistake — writing one giant `...` method that tries to do everything, including things that didn't need an LLM at all.

Worked example — a support-ticket triage agent:

| Operation | Kind |
|---|---|
| Look up an order by ID | Computable |
| Check refund-eligibility policy (delivered, ≤30 days) | Computable |
| Decide urgency/category from a free-text message | Judgment call |
| Draft a reply to the customer | Judgment call |
| Sequence "triage, then draft, then log" | Computable (orchestration) |

### 2. Write the class skeleton with real bodies first

```python
from nooa import Agent
from nooa.unifiedllm import get_llm_client

llm = get_llm_client("claude-haiku-4-5")

class SupportAgent(Agent, llm=llm):
    """You are a customer support triage agent."""

    def __init__(self, order_db: dict):
        super().__init__()
        self.order_db = order_db

    def get_order(self, order_id: str) -> dict | None:
        """Look up an order by ID."""
        return self.order_db.get(order_id)

    def is_refund_eligible(self, order: dict) -> bool:
        """Check refund policy: delivered and within 30 days."""
        return order.get("delivered", False) and order.get("days_since_delivery", 999) <= 30
```

Notice these are ordinary methods with real bodies — nothing framework-specific yet. Run a quick sanity check that plain Python still works as plain Python:

```bash
uv run python -c "
from support_agent import SupportAgent
a = SupportAgent(order_db={'A1': {'delivered': True, 'days_since_delivery': 5}})
print(a.is_refund_eligible(a.get_order('A1')))
"
```

Expected output: `True`.

### 3. Add the judgment-call methods as generation methods

```python
from typing import Literal
from pydantic import BaseModel

class Ticket(BaseModel):
    category: Literal["billing", "shipping", "product", "other"]
    urgency: Literal["low", "medium", "high"]
    refund_eligible: bool
    draft_reply: str

class SupportAgent(Agent, llm=llm):
    """You are a customer support triage agent."""

    # ... __init__, get_order, is_refund_eligible from step 2 ...

    async def triage(self, message: str, order_id: str) -> Ticket:
        """Create a typed support ticket for this message.

        Use get_order and is_refund_eligible to check the order before deciding
        refund_eligible. Write a brief, empathetic draft_reply.
        """
        ...
```

The return type (`Ticket`) is the contract: whatever the model produces, you get back a validated `Ticket` or an exception — never raw text you have to parse. Because `get_order`/`is_refund_eligible` are visible methods on `self` (no `@hidden`, not underscore-prefixed), CodeAct's default strategy lets the model call them directly from generated code instead of guessing at order details or eligibility rules.

### 4. Add an orchestrator if you have a multi-step sequence

If "triage, then log the result" needs to always happen in that order regardless of what the model decides, make that sequencing a real-bodied method rather than trusting a single generation method to remember to do both:

```python
    async def handle_message(self, message: str, order_id: str) -> Ticket:
        """Orchestrator: triage, then persist."""
        ticket = await self.triage(message, order_id)
        self._log_ticket(ticket)          # deterministic — always runs
        return ticket

    def _log_ticket(self, ticket: Ticket) -> None:
        print(f"[{ticket.urgency}] {ticket.category}: {ticket.draft_reply[:60]}...")
```

`_log_ticket` is private (leading underscore) so it's hidden from the model by default — it's plumbing the developer controls, not something the LLM needs to know about or call itself.

### 5. Run it end-to-end

```python
import asyncio

async def main():
    agent = SupportAgent(order_db={"A1": {"delivered": True, "days_since_delivery": 5}})
    ticket = await agent.handle_message("My order hasn't arrived and I want a refund!", "A1")
    print(ticket)

asyncio.run(main())
```

```bash
uv run python support_agent.py
```

Expected output: a printed `Ticket(category=..., urgency=..., refund_eligible=True, draft_reply='...')`.

### 6. Choose strategies deliberately (don't just accept the default everywhere)

`triage` above defaults to `CodeActStrategy` (needs to call `get_order`/`is_refund_eligible`, so the default iterative REPL loop is appropriate). If you add a pure classification method with no tool calls — e.g. `async def spam_score(self, message: str) -> float`, see [`guides/choose-a-strategy.md`](choose-a-strategy.md) — attach `@strategy(PredictStrategy())` explicitly rather than paying for an unneeded iteration loop.

## Verification

- `uv run python support_agent.py` produces a well-typed `Ticket` with no exception.
- Start the trace viewer (`uv run nooa start-dev`) before re-running and confirm in `http://localhost:5001` that `handle_message` → `triage` → (nested calls to `get_order`/`is_refund_eligible`) → `_log_ticket` appear as a nested span tree matching the call structure you wrote. If `get_order`/`is_refund_eligible` never show up as nested spans under `triage`, the model didn't call them — check that they're actually visible (not accidentally marked `@hidden` or underscore-prefixed) and that the docstring on `triage` actually tells the model to use them.
- Rename `triage` to `triage_quickly` and re-run — the output should shift in tone/length, confirming the docstring-as-prompt mental model is actually in effect for your agent, not just the tutorial's.

## Troubleshooting

- **`ValueError: No LLM available for SupportAgent`** — you didn't pass `llm=` at class definition or construction. See [`concepts/agents-and-generation-methods.md`](../concepts/agents-and-generation-methods.md#cascading-llm-resolution).
- **The model never calls `get_order`/`is_refund_eligible`** — check visibility (they must not start with `_` and must not be `@hidden`), and check the docstring actually names them; `doc(self)` shows the model *that* they exist, but the docstring is what tells it to use them for this specific task.
- **Validation keeps retrying / never returns** — your Pydantic model may be stricter than the model can reliably satisfy in one attempt (e.g. an overly narrow `Literal`). Loosen the type or add clearer docstring guidance on how to pick a category.
- More generally: [`troubleshooting/common-issues.md`](../troubleshooting/common-issues.md).
