# braindump

**Dump your thoughts as Markdown. Ask questions across all of them at once.**

---

## TL;DR

```bash
# 1. Install
pip install braindump-ai

# 2. Initialize a workspace (creates spikes/, wiki/, and llm.json)
braindump init ~/my-knowledge-base

# 3. Run the local server
braindump run ~/my-knowledge-base
```

Open `http://localhost:8000` in your browser.
Write spikes in the editor, ask questions in the query bar, explore the knowledge graph.

Prerequisites: Claude Code credentials in `~/.claude/` (run `claude login` once to authenticate — the `claude` binary itself does not need to be on `PATH`, the SDK ships a bundled copy).

---

## The problem

Every knowledge tool forces a choice: organize first, think later.
You have to decide where a note belongs before you write it.
You end up with isolated notebooks that cannot talk to each other — ask the same question in two places and you get two disconnected answers.

## What braindump does differently

**braindump** treats each Markdown file as a **spike** — a timestamped, tagged unit of thinking.
Write in the built-in editor.
The app automatically builds a living wiki that connects related spikes by shared tags, semantic relationships, and temporal proximity.
No manual linking.
No folders to organize.

When you ask a question, braindump reasons **across your entire corpus at once** — not just one notebook, not just keyword search.
It gives you a grounded answer that cites exactly which spikes it drew from.

The knowledge graph is **hierarchical**: zoom out to see the major themes in your thinking, zoom in to individual spikes and their connections.
The structure emerges from your writing, not from a taxonomy you imposed upfront.

## Unique selling point

**Cross-corpus AI reasoning over a self-organizing, portable knowledge graph — entirely on your machine.**

- Everything is plain `.md` files. No proprietary format, no lock-in.
- No data leaves your machine. All LLM inference uses the `claude` CLI and your existing Anthropic subscription.

## How it works

Write a spike in the UI → braindump saves it and asynchronously updates a wiki index backed by three plain markdown files:

- **`wiki/index.md`** — LLM-authored summaries of every spike
- **`wiki/connections.md`** — LLM-authored explicit semantic links between related spikes
- **`wiki/hierarchy.md`** — LLM-authored thematic community groupings

Ask a question → the LLM reads the compiled index and answers with inline citations (`[1]`, `[2]`, …) pointing back to the source spikes.

Explore the graph → zoom out to major topic clusters derived from the hierarchy, zoom in to individual spikes and their connections.

## Architecture

### Wiki layer
The core innovation is the **wiki layer**: a set of human-readable markdown files maintained by the LLM.
Every create/update/delete triggers a background job that rewrites `index.md`, `connections.md`, and `hierarchy.md` in sequence.
The wiki doubles as both the retrieval index and a browsable knowledge artifact.

A lightweight `meta.json` cache (no LLM involved) keeps spike listings fast.
A `wiki/log.md` tracks all events for diagnostics.

### Query pipeline
No vector embeddings. One LLM call per query:

1. Feed the hierarchy `hierarchy.md` and full `index.md` summaries as context
2. LLM answers with `[N]` citations; citations are parsed into source cards

Because the index summaries are rich, raw spike content is not sent to the model.

### Knowledge graph
Derived purely from the wiki markdown files — no database:

| Zoom | View | Source |
|---|---|---|
| 0 | Community clusters only | `hierarchy.md` |
| 1 | Clusters + spike nodes | `hierarchy.md` |
| 2 | Spikes + tag / semantic / temporal edges | `meta.json`, `connections.md` |

## Stack

- Backend: Python >= 3.13 and `fastapi`
- Frontend: React + Cytoscape.js
- LLVM: Claude (via `claude` CLI)
- Storage: plain Markdown.
