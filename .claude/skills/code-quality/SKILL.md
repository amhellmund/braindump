---
name: code-quality
description: >
    Activate this skill for any task updating the source code.
    
    This includes:
      - creating a new source file
      - updating an existing source file
      - writing new tests
      - update existing tests
---

# Code Quality Guardian

This sections summarizes the checks that must pass before finalizing a code change.

## Software Quality Gate

There is a single entry point to run all SW quality gates for this project:

- [ ] **Software Quality Gate**: ``uv run tools/check.py``

The individual commands for finer-grain control are listed in the subsequent subsections.

## Python Checklist

- [ ] **Python Formatting**: ``uv run ruff format``
- [ ] **Python Linting**: ``uv run ruff check``
- [ ] **Python Type Checking**: ``uv run ty check``
- [ ] **Python Tests**: ``uv run pytest tests``
- [ ] **Python Security**: ``uv run bandit``

## React and Typescript

- [ ] **TS Type Checking**: `cd frontend && npx tsc --noEmit`
- [ ] **Linting**: `cd frontend && npm run lint`
- [ ] **Build**: `cd frontend && npm run build`