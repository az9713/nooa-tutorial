# NVIDIA OO Agents (NOOA) Documentation

NOOA is a model-agnostic Python framework for building AI agents as ordinary Python classes — fields are state, methods are capabilities, docstrings are prompts, and a method body of `...` tells the runtime "an LLM implements this." This is the documentation set for the framework, its CLI, its trace viewer, and its companion packages.

Not sure where to start? Read [What Is This?](overview/what-is-this.md), then work through the [Quickstart](getting-started/quickstart.md).

## Navigation

| Section | Contents |
|---|---|
| [Overview](overview/what-is-this.md) | What NOOA is, the mental model, and the glossary of terms used throughout these docs |
| [Getting Started](getting-started/prerequisites.md) | Install, run your first agent, and a guided onboarding walkthrough |
| [Concepts](concepts/agents-and-generation-methods.md) | Deep dives into each subsystem: agents, strategies, visibility/context, tools/skills/MCP, tracing, execution/storage |
| [Guides](guides/write-your-first-agent.md) | Task-oriented how-tos for common jobs |
| [Reference](reference/cli-reference.md) | Complete CLI command reference and configuration field reference |
| [Architecture](architecture/system-design.md) | System design and the reasoning behind non-obvious choices (ADRs) |
| [Troubleshooting](troubleshooting/common-issues.md) | Symptom → cause → fix for the issues you're most likely to hit |

## Quick links by document type

- **New to NOOA?** [`overview/what-is-this.md`](overview/what-is-this.md) → [`getting-started/quickstart.md`](getting-started/quickstart.md) → [`getting-started/onboarding.md`](getting-started/onboarding.md)
- **Writing an agent right now?** [`guides/write-your-first-agent.md`](guides/write-your-first-agent.md), [`guides/choose-a-strategy.md`](guides/choose-a-strategy.md)
- **Debugging a run?** [`guides/trace-and-debug-a-run.md`](guides/trace-and-debug-a-run.md), [`troubleshooting/common-issues.md`](troubleshooting/common-issues.md)
- **Looking up a flag, field, or command?** [`reference/cli-reference.md`](reference/cli-reference.md), [`reference/configuration-reference.md`](reference/configuration-reference.md)
- **Understanding why the framework is shaped this way?** [`architecture/system-design.md`](architecture/system-design.md)

## What already exists outside `docs/`

This documentation set complements, and deliberately does not duplicate, material that already lives elsewhere in the repository:

- [`README.md`](../README.md) — project pitch, install instructions, citation. Still the best entry point from GitHub/PyPI.
- [`examples/README.md`](../examples/README.md) — the official progressive code tutorial (`examples/quickstart/01`–`15`). The [Quickstart](getting-started/quickstart.md) and [Onboarding](getting-started/onboarding.md) docs here summarize and sequence it; they link out to the runnable files rather than re-pasting them.
- [`AGENTS.md`](../AGENTS.md) — terse, rule-based conventions for coding agents authoring NOOA agents (visibility table, strategy table, reserved parameters). The [Concepts](concepts/agents-and-generation-methods.md) docs here explain the *why*; `AGENTS.md` remains the fast lookup table.
- [`skills/`](../skills/README.md) — eleven `SKILL.md` bundles that teach a coding agent (Claude Code, Cursor, Codex) how to author NOOA agents, tune strategies, capture traces, etc. [`concepts/tools-skills-and-mcp.md`](concepts/tools-skills-and-mcp.md) explains what these are and when to reach for each.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md), [`RELEASING.md`](../RELEASING.md), [`SECURITY.md`](../SECURITY.md) — contribution workflow, release process, and vulnerability reporting. Not duplicated here.
- [`CHANGELOG.md`](../CHANGELOG.md) — version history.
- `packages/nooa-cli/docs/activity-introspection-design.md` — a design note for one CLI subsystem; linked from [`reference/cli-reference.md`](reference/cli-reference.md) rather than restated.

## Keeping these docs true

- **Same-change rule.** If a change touches `src/nooa/agent.py`, `src/nooa/decorators.py`, `src/nooa/strategies/*`, `src/nooa/config/*`, `src/nooa/mcp/*`, `src/nooa/tracing/*`, or the `nooa` CLI (`packages/nooa-cli/src/nooa_cli/commands/*`), update the matching file under `docs/` in the same commit or PR. The ownership line at the top of each reference doc names exactly which source files it tracks.
- **Staleness markers.** Version numbers, CLI flags, and config field defaults are only as current as the commit this was written against (`pyproject.toml` version `0.0.6`+dev at time of writing — check `nooa --version` / `CHANGELOG.md` if something here looks stale).
- **Re-validate on edit.** After changing any file in `docs/`, re-check cross-links, re-run a stub search (`TBD`, `TODO`, `coming soon`), and confirm terminology (see [`overview/key-concepts.md`](overview/key-concepts.md)) is still used consistently.
