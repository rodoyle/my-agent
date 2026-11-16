# Python Style
> **This file is the single source of truth for all AI coding agents.**
> Read it fully before writing, editing, or reviewing any Python code
> It takes precedence over any agent defaults or model priors.
---

## 0. Task phases

Every task has exactly two phases. Respect the boundary absolutely.

| Phase | What agents may do |
|-------|-------------------|
| **PLAN** | Read code, ask questions, propose design, propose new dependencies, draft `docs/plans/*.md` changes; glla drafting fits here|
| **ACT** | Write/edit code, edit `pyproject.toml` tool blocks and entry points, run CI scripts |

**Dependency rule:** Agents may propose new packages during PLAN phase. They may **never** add a new package name to `[project.dependencies]` or `[project.optional-dependencies]` during ACT. The human explicitly approves each dependency. Agents may edit tool configuration blocks, build backend settings, and entry point wiring.

**Install rule:** Agents may never run `pip install`, `uv add`, `uv pip install`, or any command that installs an arbitrary package at runtime. Assume the venv is already correct or flag [ACTION REQUIRED] to the user.

---

## 1. Python style — core principles

These rules encode the house style. Code must look like **one terse author wrote the entire repo in one session.**

### 1.1 General

- Python 3.12+. No compatibility shims, no `from __future__ import annotations`.
- Maximum **~600 SLOC per file**. Split early; it is cheaper than large context.
- Maximum function length: **one screen page** (~40–50 lines). If it grows, decompose.
- **Cyclomatic complexity ≤ 10** per function. Ruff enforces this; do not suppress.
- Consistency is absolute. No mixing styles across files. When in doubt, match the surrounding code exactly.

### 1.2 Formatting (Ruff is the sole formatter authority)

- **Line length:** 120 characters.
- **Quotes:** double everywhere — strings, f-strings, docstrings. Consistent with Rust/JSON convention.
- **Indentation:** 4 spaces, no tabs.
- **Line endings:** LF only.
- **Blank lines:** minimize to PEP8 minimum. No decorative whitespace between short logical steps.
  Use `#region` / `# ── section label ───` boundary markers when grouping helps context.
- Trailing commas in multi-line literals: yes (Black style, Ruff default).
- All formatting is auto-applied by `uv tool run ruff format .`. Never hand-format.

### 1.3 Imports

- **Absolute imports only**, like Rust module paths: `from your_pkg.config import Config`.
- `from x import y` preferred over `import x; x.y`.
- **Forbidden:** `import *` in any form.
- **Allowed aliases** (only these standard shorthands):
  `cfg`, `df` (DataFrames), `pl` (polars), `pd` (pandas — interop only), `pt` (pytorch),
  `np` (numpy), `plt` (matplotlib).
- **Inline imports** are begrudgingly allowed when they: reduce startup cost for heavy deps,
- break circular imports, or improve local context for agents reading a function in isolation.
  Annotate with `# lazy import — heavy dep` comment.
- All imports at module top unless inline rule applies above.

### 1.4 Functions, modules, composition

- **Prefer:** functions · modules · iterators · `itertools` · comprehensions.
- **Avoid:** class hierarchies, deep inheritance, service-style OOP.
- **Allowed classes:** dataclasses and Pydantic models for structured payloads and config. Nothing else by default.
- Use comprehensions over explicit loops when the intent is clear in one line.
- Side effects belong at entrypoints, not in library functions.
- Core library functions return a value or raise; they do not print, write files, or modify globals.

### 1.5 Type annotations

- **Mandatory:** all argument types and return types for public functions in `src/`.
- **Optional:** return type annotations for private helpers when the type is unambiguously obvious.
- **Tests:** untyped pytest tests are fine. Mocking and monkeypatching must not be impeded by typing.
- Use built-in generic syntax: `list[int]`, `dict[str, Any]`, `tuple[int, ...]` — not `typing.List`.
- `Any` is acceptable. If strong static typing were the goal, we'd use Rust.
- **Do not annotate** with `# type: ignore` as a workaround for real type errors.

### 1.6 Docstrings and comments

- **NumPy style** docstrings for all public functions and classes in `src/`.
- **Not required** in tests, scripts, notebooks, or private helpers.
- Docstrings and comments must **add information type annotations do not**. Never restate the signature.
- Doctests are encouraged when they demonstrate non-obvious usage and help agent context.
- Inline `#TODO - ` tags signal specific agent tasks and are the primary mechanism for directing work.

---

## 2. Error handling

- Library code: raise specific exceptions. Re-raise with context at boundaries.
- Never swallow exceptions silently.
- CLI / main entrypoints: catch at the outermost boundary, log to stderr, return appropriate exit code.
- Do **not** return `Result`-like unions or `Optional` error wrappers. They force noisy `if result and ...` chains that make Python unreadable.

```python
# ✅ correct pattern
def process(path: Path) -> pl.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    return pl.read_parquet(path)

# ✅ correct entrypoint pattern
def main() -> None:
    try:
        result = process(cfg.dataset_root / "train.parquet")
    except Exception as exc:
        log.error("fatal", error=str(exc))
        raise SystemExit(1) from exc
```

---

## 3. Logging

- **`structlog`** is the standard logger. Never use `print()` for logging.
- **stdout** is strictly for pipeline-consumable output (e.g., JSON records piped downstream).
- **All logs go to stderr** via structlog's stdlib bridge.
- Call `configure_logging(cfg.log_level)` once at app startup in `main()`.
- Standard event keys: `event`, `module`, `path`, `duration_ms`, `rows`, `split`, `device`, `error`.

```python
# ✅ correct
import structlog
log = structlog.get_logger(__name__)
log.info("dataset loaded", path=str(path), rows=df.height, duration_ms=elapsed)

# ❌ forbidden
print(f"Loaded {path}")
```

---

## 4. Configuration

- **Single source of truth:** `config.toml` (or `config.yaml` only when forced by external system).
- A **default config** must exist and be committed. The app must run with defaults.
- Config is loaded once at startup, merged (file → env vars → CLI args), and returned as a
- **frozen Pydantic model**. It is passed explicitly to the primary entry point.
- A `TestConfig` pytest fixture must be defined in `conftest.py` for any module that uses config.
- **Secrets** arrive as: path to a file (read and clear), or envar (read and clear immediately).
  Never commit secrets. Never log secrets.

```python
# src/your_pkg/config.py  — canonical shape
from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class Config(BaseModel, frozen=True):
    dataset_root: Path = Path("/datasets")
    model_root:   Path = Path("/models")
    log_level:    str  = "INFO"

class _EnvOverrides(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", extra="ignore")
    dataset_root: Path | None = None
    model_root:   Path | None = None
    log_level:    str  | None = None

def load_config(path: Path | None = None) -> Config:
    ...  # load TOML, merge env overrides, return frozen Config
```

---

## 5. Data and AI stack

### 5.1 Polars (mandatory)

- **pandas is banned** except at explicit interoperability boundaries (e.g., seaborn, sklearn).
- Treat DataFrames as immutable; return new frames.
- Prefer the **expression/lazy API** for non-trivial transforms.
- Use `pl` as the standard alias.

### 5.2 PyTorch

- Device handling: pass `device` explicitly; never rely on global defaults.
- Basic tensor type hint `torch.Tensor` is sufficient; specialised shape annotations only where they materially help.
- Seed RNG explicitly when determinism is required.

### 5.3 Directory contracts

```
/datasets/          # mounted or symlinked by operator/container; never committed
/models/            # model weights; yolo11n.pt lives here
/scripts/           # train.py, run.py (inference), data pipeline entry points
```

- `config.dataset_root` defaults to `/datasets` and is always present.
- Agents may assume `/datasets` exists at runtime; they may never write training data into the repo.

---

## 6. Repository layout

```
repo/
├── .devcontainer/          # VS Code devcontainer config
├── ci/
│   ├── precommit.py        # fast local checks (format, lint, unit)
│   ├── premerge.py         # full checks (lint, types, integration, coverage)
│   └── predeploy.py        # packaging, container, GPU matrix
├── .agent/
│   ├── task.json           # optional - mount point for headless task execution
│   ├── result.json         # Put the output of a headless task here 
│   └── environment.yaml    # Mount point for key environmental guidance, parameters 
├── models/                 # model weights, usually a mounted volume or symlink from external storage
│   └── yolo11n.pt
├── notebooks/              # Quarto / Jupyter — import from src/, minimal logic
├── scripts/                # train.py, run.py, data fetch/process entry points
├── src/
│   └── your_pkg/
│       ├── __init__.py
│       ├── config.py       # Config model + load_config()
│       ├── logging.py      # configure_logging()
│       └── ...
├── tests/
│   ├── conftest.py         # shared fixtures, TestConfig
│   ├── integration/        # mirror of src/ structure; marked @pytest.mark.integration
│   └── ...                 # other documents, reports, results 
└── README.md
```
---

## 7. CI gate contracts

Agents are responsible for passing CI gates when explicitly tasked.
Never suppress checks with `# noqa`, `# type: ignore`, or skip flags unless adding a `#TODO` explaining why.
CI hooks are typically triggered with pre-commit tooling

| Script | When | Checks |
|--------|------|--------|
| `ci/precommit.py` | Before every commit | Format, fast lint (auto-fix), unit tests |
| `ci/premerge.py`  | Before every merge  | Full lint, ty check, integration tests, coverage |
| `ci/predeploy.py` | Before deploy       | Build, container check, GPU tests, dependency audit |

Run with: `uv run python ci/precommit.py`

---

## 8. Approved dependency families

Plan-phase proposals may use any of the following. No others without explicit human approval.

**Runtime / data / AI**
`torch` · `torchvision` · `transformers` · `torchsig` · `polars` · `numpy` · `requests`
`mlflow` · `langchain` · `chromadb` · `scapy` · `pydantic` · `pydantic-settings` · `structlog`

**Services / platform**
`fastapi` · `uvicorn` · `flask` · `kopf` · `kubernetes`

**Native / build**
`maturin` · `pyo3` · `cffi` · `ctypes`

**Dev / tooling**
`uv` · `ruff` · `black` · `pytest` · `pytest-cov` · `pytest-asyncio` · `ty`
`matplotlib` · `seaborn` · `huggingface-hub`
