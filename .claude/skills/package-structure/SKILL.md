---
name: package-structure
description: >
    Activate this skill for any task adding new files to the repository.
---

# Package Structure

## Project structure

```
braindump/
├── src/braindump/       # Python backend package (FastAPI, RAG pipeline, LLM backends)
├── frontend/
│   └── src/
│       └── components/  # React components (one .tsx + .css pair per component)
├── tests/               # Pytest integration tests
├── tools/               # Build hooks and dev helper scripts
└── pyproject.toml       # Package config, hatch build, ruff, ty, bandit
```

## Key conventions

- New backend modules go in `src/braindump/`; register new API routes in `app.py`.
- New React components go in `frontend/src/components/` with a matching `.css` file.