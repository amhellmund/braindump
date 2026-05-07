# braindump

**Dump your thoughts as Markdown. Ask questions across all of them at once.**

braindump is a local-first, AI-powered knowledge base.
Write short notes called **spikes** in a built-in Markdown editor.
The app automatically builds a living wiki that connects related spikes by shared tags, semantic relationships, and temporal proximity — then lets you query across your entire corpus in a single shot.

Everything is plain `.md` files on your machine. No proprietary format, no cloud sync, no data leaving your device.

---

## Prerequisites

- Python ≥ 3.13
- An authenticated Claude Code installation (`claude login` — the `claude` binary does not need to be on `PATH`; the SDK ships a bundled copy)

---

## Single-user setup

The default mode. No accounts, no passwords — anyone who can reach the server has full access.

```bash
# 1. Install
pip install braindump-ai

# 2. Initialise a workspace
braindump init ~/my-knowledge-base

# 3. Start the server
braindump run ~/my-knowledge-base
```

Open `http://localhost:8000`.

**What you can do:**

- **Write spikes** — click **+** in the sidebar, write Markdown, add tags and an optional stream, save.
  The wiki index updates in the background automatically.
- **Query** — type a question in the query bar at the bottom of the screen.
  The answer is grounded in your spikes and includes inline citations (`[1]`, `[2]`, …) linking back to the source.
- **Browse** — switch between the **Browse** (thematic hierarchy) and **Graph** tabs in the main panel.
  Zoom out to see major topic clusters; zoom in to see individual spikes and their connections.
- **Streams** — assign spikes to a named stream (project, topic, area) and generate an AI summary of that stream.
- **Dailies** — view all spikes created on a given day and generate a daily digest summary.
- **Chat** — continue a multi-turn conversation with your knowledge base; previous turns are stored as named sessions.

**Optional: keep images in git-lfs**

```bash
braindump init ~/my-knowledge-base --git --no-git-lfs  # git without LFS
braindump init ~/my-knowledge-base --git               # git + LFS for images
```

**Run on a custom port or bind to all interfaces**

```bash
braindump run ~/my-knowledge-base --port 9000 --host 0.0.0.0
```

---

## Multi-user setup

Multi-user mode adds bearer-token authentication so several people can share one server instance, each with their own access token.
It is activated automatically when a user registry exists in the workspace.

### 1. Initialise the workspace (same as single-user)

```bash
braindump init ~/shared-knowledge-base
```

### 2. Add users

Each user gets an opaque token shown **once** at creation time.
Store it somewhere safe — it cannot be recovered, only rotated.

```bash
# Add a user and print their token
braindump user add ~/shared-knowledge-base alice
# → Token for alice: bd_a1b2c3…  (copy this)

braindump user add ~/shared-knowledge-base bob
# → Token for bob: bd_d4e5f6…
```

The user registry is stored in `<workspace>/.users/users.json` and is automatically gitignored.

### 3. Start the server

```bash
braindump run ~/shared-knowledge-base --host 0.0.0.0 --port 8000
```

### 4. Log in

Open `http://<server>:8000` in a browser.
You are presented with a login page; paste the token you received.
A 30-day session cookie is set — no need to re-enter the token on subsequent visits.

### Token management

```bash
# Rotate a token (invalidates the old one immediately)
braindump user update-token ~/shared-knowledge-base alice

# List all users
braindump user list ~/shared-knowledge-base

# Remove a user
braindump user remove ~/shared-knowledge-base alice
```

---

## How it works

### Wiki layer

The core of braindump is a **wiki layer** — a set of human-readable Markdown files maintained by the LLM:

| File | Purpose |
|---|---|
| `wiki/index.md` | One entry per spike: title, tags, 2–3 sentence summary, related spikes; used as the primary retrieval index |
| `wiki/connections.md` | Explicit semantic links between related spikes |
| `wiki/hierarchy.md` | Thematic community groupings; every spike belongs to exactly one community |
| `wiki/meta.json` | Fast metadata cache (no LLM); used for listings and graph edges |

Every create / update / delete triggers a background LLM job that rewrites these files in sequence.

### Query pipeline

No vector embeddings. One LLM call per query:

1. Load `meta.json` (spike titles and tags) and `index.md` (summaries).
2. Send them to the LLM together with the user question and any chat history.
   The LLM is also given a `Read` tool scoped to the spikes directory so it can
   fetch the full content of individual spikes when the index summary alone is
   not sufficient to answer a detailed question.
3. Parse `[N]` citation markers from the answer to produce source cards.

### Knowledge graph

| Zoom | View | Source |
|---|---|---|
| 0 | Community clusters only | `hierarchy.md` |
| 1 | Clusters + spike nodes | `hierarchy.md` |
| 2 | Spikes + tag / semantic / temporal edges | `meta.json`, `connections.md` |

### Health checks

braindump runs periodic consistency checks (default: every 60 minutes) and repairs any drift between the spike files on disk and the wiki layer automatically.
Run an immediate check via the **Repair** button in the UI or `GET /api/v1/wiki/health`.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python ≥ 3.13, FastAPI, Uvicorn |
| Frontend | React 18, TypeScript, Vite, Cytoscape.js |
| LLM | Claude via `claude-agent-sdk` (Anthropic subscription auth) |
| Storage | Plain Markdown + JSON files |
