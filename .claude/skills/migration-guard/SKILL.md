---
name: migration-guard
description: >
    Activate this skill when any of the following on-disk format changes are made:
      - Fields of `SpikeMeta` in `src/braindump/types.py` (add, remove, rename, or type change)
      - `_SCHEMA_CONTENT` in `src/braindump/wiki.py` (LLM operational guidelines format)
      - Parsed structure of `index.md`, `connections.md`, or `hierarchy.md`
        (e.g. changes to regex patterns in `parse_connections`, `parse_hierarchy`, or `_update_index`)
      - How `meta.json` is read or written (field additions, removals, or structural changes)
---

# Migration Guard

When you change a data format that braindump stores on disk, you must update
the migration system so that existing workspaces can be upgraded automatically.

## Which aspect is affected?

| What changed | Aspect to bump |
|---|---|
| `SpikeMeta` fields or `meta.json` structure | `meta` |
| `_SCHEMA_CONTENT` in `wiki.py` | `wiki_schema` |
| Parsed format of `index.md`, `connections.md`, or `hierarchy.md` | `wiki_schema` |

## Checklist

- [ ] **Bump `CURRENT_VERSIONS`** in `src/braindump/migrations.py` — increment the
      relevant field (`wiki_schema` or `meta`) by 1.

- [ ] **Write a `Migration` subclass** in `src/braindump/migrations.py`:
  - Set class attributes: `aspect`, `from_version` (old value), `to_version` (new value), `description` (one line)
  - Implement `migrate(self, workspace: Path) -> None` — transform existing on-disk data
    from the old format to the new format (e.g. rewrite `meta.json`, update `SCHEMA.md`)
  - Append an instance to `_MIGRATIONS`

- [ ] **Write a migration test** in `tests/test_migrations.py` that:
  - Seeds the workspace with on-disk data in the old format
  - Calls `run_migrations(workspace)` (with `CURRENT_VERSIONS` patched via `monkeypatch` if needed)
  - Asserts the on-disk data was correctly transformed to the new format
