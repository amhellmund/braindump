---
name: python-dev
description: >
    Activate this skill for any task involving writing Python source code (extension: .py)
    
    This includes:
      - writing new module
      - fixing bugs
      - adding type hints
      - writing docstrings
      - creating unit tests
      - structuring packages
      - reviewing Python code.
---

# Python Development Skill

## Core Principles

1. **Always write idiomatic Python** — follow PEP 8 and PEP 20.
2. **Prefer clarity over cleverness** — readable code is maintainable code.
3. **Type hints by default** — add type hints for all functions.
4. **Fail loudly** — raise specific exceptions with helpful messages rather than silently swallowing errors.
5. **Test-first mindset** — suggest or produce `pytest` tests alongside non-trivial implementations.
6. **Assert code** — use `assert` statements only for internal assertions and type deductions.

---

## General Python Coding Guidelines

Before finalising any Python output, verify:

- [ ] **File Structure** — use the Python structure from [python_template.md](python_template.md)
- [ ] **Identifier** — use snake_case names, use a leading underscore for private constants and functions
- [ ] **PEP 8 compliant** — 4-space indent
- [ ] **Type-annotated** — all function signatures have parameter and return types
- [ ] **Docstrings** — public functions/classes have Google-style
- [ ] **Error handling** — no bare `except:`, raise specific exception types
- [ ] **No mutable defaults** — never `def f(x=[]):`, use `None` sentinel instead
- [ ] **f-strings over %/format** — prefer f-strings
- [ ] **Context managers** — use `with` for files, DB connections, locks
- [ ] **Init Files** — use ``__init__.py`` files only for exposing constants and functions, do not add code


## Test Guidelines

- [ ] **Test Functions** — use free-floating test functions instead of nested functions in test classes
- [ ] **Public Functions** — write tests for new public functions
- [ ] **Private Functions** — write tests for private functions if suitable to reduce test variation on the public function level
- [ ] **Test Updates** — modify existing tests as least as possible to assure software stability  


### Project-Specific Guidelines

Use these guidelines in addition to the general coding guidelines:

- [ ] **Pydantic** — use `pydantic` types for file I/O and for `fastapi` routes.

---

## Patterns & Best Practices

### Idiomatic Constructs

```python
# Prefer enumerate over manual indexing
for i, item in enumerate(items):
    ...

# Prefer unpacking over indexing
first, *rest = collection

# Use walrus operator for assignment in conditions (Python 3.8+)
if m := pattern.match(line):
    process(m.group(0))

# Prefer dataclasses for plain data containers
from dataclasses import dataclass, field

@dataclass
class Config:
    host: str = "localhost"
    port: int = 8080
    tags: list[str] = field(default_factory=list)
```

### Error Handling

```python
# Always be specific
try:
    result = risky_call()
except (ValueError, KeyError) as exc:
    raise RuntimeError(f"Failed to process item: {exc}") from exc
```

### Typing Patterns

```python

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

def process(items: Sequence[str]) -> dict[str, int]:
    return {item: len(item) for item in items}
```

### File I/O

```python
# Always specify encoding
file_path.read_text(encoding="utf-8")

# Use pathlib over os.path
from pathlib import Path

config_path = Path(__file__).parent / "config.yaml"
```

---

## Testing

Default test framework: **pytest**. Place tests in `tests/` mirroring the source layout.
Test files start with `test_<module>.py`.

```python
# tests/test_example.py
import pytest
from mymodule import my_function

def test_happy_path():
    assert my_function("input") == "expected"

def test_raises_on_bad_input():
    with pytest.raises(ValueError, match="must be positive"):
        my_function(-1)

@pytest.mark.parametrize("val,expected", [
    ("a", 1),
    ("ab", 2),
    ("", 0),
])
def test_parametrized(val, expected):
    assert len(val) == expected
```

Run tests:
```bash
uv run python -m pytest -v
# With coverage:
uv run python -m pytest --cov=src --cov-report=term-missing
```

---

## Debugging Tips

```bash
# Run with verbose traceback
python -m traceback script.py

# Quick REPL inspection
python -c "import module; print(dir(module))"

# Profile a script
python -m cProfile -s cumulative script.py | head -20
```