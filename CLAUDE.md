# braindump — CLAUDE.md

## Project overview

braindump is a local-first, AI-powered knowledge base that builds a living wiki from plain Markdown files and lets users query across all their spikes simultaneously.

## Technology stack

### Backend
- **Python 3.13** + **FastAPI** — local HTTP server
- **python-frontmatter** + **mistune** — Markdown parsing, frontmatter extraction
- **claude-agent-sdk** — LLM backend via `claude` CLI (Anthropic subscription auth)
- **python-dotenv** — optional `.env` file loading at server startup

### Frontend
- **React 18** + **Vite** + **TypeScript** (strict mode, no JS)
- **Cytoscape.js** — interactive knowledge graph with force-directed layout
- **FontAwesome** — icons

### Data layout (per workspace)
```
<workspace>/
├── spikes/          # Source-of-truth .md files
│   └── images/      # Uploaded images
├── wiki/            # LLM-managed knowledge layer (human-readable markdown)
│   ├── SCHEMA.md    # LLM operational guidelines (written once by braindump init)
│   ├── index.md     # LLM-authored catalog: one entry per spike with rich summary
│   ├── connections.md  # LLM-derived semantic links between spikes
│   ├── hierarchy.md    # LLM-managed thematic community groupings
│   ├── meta.json    # Fast metadata cache: spike_id → {title, tags, timestamps}
│   └── log.md       # Append-only event log
└── llm.json         # LLM backend config (model, health-check interval, env_file)
```

## Key architectural decisions

### LLM backend (`llm.py`)
`ChatBackend` ABC with one implementation:
- **`ClaudeBackend`** — runs the system `claude` CLI as a subprocess via `claude-agent-sdk`; requires a working, authenticated Claude Code installation (`~/.claude/` credentials)

Model is stored in `llm.json` (written by `braindump init`) and loaded lazily on first query.
An optional `.env` file path may be stored in `llm.json["env_file"]`; it is loaded at server startup.
`ChatBackend.ping()` sends a prompt expecting "pong" — called once at server startup to verify connectivity.

### Wiki layer (`wiki.py`)
The wiki is an LLM-maintained knowledge index stored as plain markdown files in `<workspace>/wiki/`.
On every spike create/update/delete the LLM rewrites three files in sequence:

1. **`index.md`** — one `## {uuid}` section per spike with title, tags, creation timestamp, a 2–3 sentence summary, and a `Related:` line naming up to three related spike IDs.
2. **`connections.md`** — one line per semantic link: `- {uuid-a} <-> {uuid-b}: {reason}`. Only recorded when there is a clear conceptual relationship (shared concepts, complementary techniques, contradictions, dependency).
3. **`hierarchy.md`** — thematic communities: `## Community: {Name}` followed by spike UUID bullets. Every spike belongs to exactly one community; new communities are created when no existing one fits.

`meta.json` is a derived metadata cache written without LLM involvement on every CRUD operation so listings are always fast.
`log.md` is an append-only event log for diagnostics.

`wiki/SCHEMA.md` contains the LLM's standing instructions (rules for formatting, output style, ID handling).
It is written once during `braindump init` and never overwritten.

### Query pipeline (`query.py`)
No embeddings or vector search.
Single LLM call per query:

1. Read `wiki/meta.json` → build a numbered spike reference list `[1] uuid — "Title" (tags: …)`.
2. Read `wiki/index.md` for LLM-authored summaries.
3. Call `ChatBackend.complete()` with: system prompt + reference list + full index + user question + conversation history.
4. Parse `[N]` citation markers from the answer to build `QuerySource` objects.
5. Append the event to `wiki/log.md`.

Because `index.md` summaries are rich enough to answer most questions, raw spike content is not sent to the model.

### Knowledge graph (`wiki.py → get_graph`)
Derived from wiki markdown files — no SQLite, no embeddings.
Zoom levels:

| Level | Description | Source |
|---|---|---|
| 0 | Cluster/macro view — one node per community | `hierarchy.md` |
| 1 | Mid view — cluster nodes + spike nodes with membership edges | `hierarchy.md` |
| 2 | Spike view — spike nodes + tag, semantic, and temporal edges | `meta.json`, `connections.md` |
| 3 | Same as zoom=2 (section view not implemented in current architecture) | — |

Edge types at zoom 2: `tag` (shared tags), `semantic` (from `connections.md`), `temporal` (spikes created within 7 days of each other).

### Health checks (`health.py`)
Lightweight consistency check run without LLM involvement:
- Spikes on disk missing from `wiki/meta.json`
- `meta.json` entries with no corresponding file on disk
- Broken UUID references in `connections.md`
- Spike IDs in `hierarchy.md` that no longer exist on disk

Runs on a configurable interval (default 60 minutes, set in `llm.json["health_check_interval_minutes"]`).
Also exposed as `GET /api/v1/wiki/health`.

### WebSocket sync (`app.py`)
`GET /api/v1/ws` — clients connect to receive real-time `{"type": "sync_done", "spike_id": "…"}` events pushed after each background wiki update.
The frontend uses this to refresh the spike list without polling.

### Build
The React frontend is compiled into `frontend/dist/` by `tools/hatch_build.py` (Hatchling hook) and bundled into the wheel at `braindump/frontend/dist/`.
`app.py` checks the package path first, falls back to the dev-layout path.

### Privacy
No content leaves the machine.
The only outbound connection is to the `claude` CLI subprocess, which uses the credentials of your authenticated Claude Code installation.

## Spike format

```markdown
---
tags: [rag, retrieval, search]
created: 2025-02-10T09:00:00+00:00
modified: 2025-02-10T09:00:00+00:00
---

# Spike title

Content written freely — no enforced structure.
```

`created` and `modified` are ISO-8601 timestamps managed automatically by the backend (`storage.enrich_spike`). `tags` is the only user-facing frontmatter field.
