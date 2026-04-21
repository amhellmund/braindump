---
name: feature-development
description: >
    Activate this skill for any feature development task that adds or modifies source code
    across the braindump stack (Python backend and/or React frontend).

    This includes:
      - implementing new features end-to-end
      - modifying existing backend or frontend behaviour
      - tasks that span both Python and React code
---

# Feature Development Skill

## Startup Checklist

Before writing any code, complete these steps in order:

- [ ] **Task list** — use TodoWrite to create a minimal todo list scoped to what was asked. Only include steps needed to ship the feature.
- [ ] **Load skills** — invoke the correct skill(s) based on what files will be touched:
  - Frontend files under `frontend/` → invoke the `react-dev` skill
  - Python files (`.py`) → invoke the `python-dev` skill
  - Both → invoke both skills

## Implementation Checklist

- [ ] **Read before editing** — read every file you plan to modify before changing it
- [ ] **Follow existing patterns** — match the conventions of the file being edited; do not introduce new abstractions
- [ ] **Pydantic for file I/O** — use Pydantic models for all structured file reads and writes, not raw `json.loads`/`json.dumps`
- [ ] **Top-level imports** — all imports at module top level, never inside function bodies
- [ ] **Frontend build** — after any frontend source change, run `npm run build` in `frontend/`
- [ ] **No scope creep** — do not add comments, docstrings, or type annotations to code you did not change; do not implement features beyond what was asked

## Completion Checklist

- [ ] **Code quality** — invoke the `code-quality` skill and pass all checks
- [ ] **Mark todos done** — mark each todo item complete as it finishes
