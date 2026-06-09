"""
laptop-agent: MLX-backed code generation agent for M1/16GB
=========================================================
Depends: mlx-lm[server], mlx-code, chromadb, sentence-transformers

Start the inference server first (separate terminal):
    mlx_lm.server --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
                  --port 8080 --host 127.0.0.1 --context-size 32768

Then run this module:
    python agent.py                              # interactive REPL
    echo "refactor auth.py" | python agent.py   # one-shot pipe
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# mlx-code imports
# ---------------------------------------------------------------------------
from mlx_code.repl import Agent, repl
from mlx_code.tools import Tool
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Optional: Jupyter support — get_ipython injected at runtime if in notebook
# ---------------------------------------------------------------------------
try:
    from IPython import get_ipython as _get_ipython

    _IPYTHON = _get_ipython()
except ImportError:
    _IPYTHON = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RESULT_STORE: dict[str, str] = {}  # in-process large-result cache
TMP_DIR = pathlib.Path("/tmp/agent")
TMP_DIR.mkdir(parents=True, exist_ok=True)

CONTEXT_LIMIT = 32_768
COMPACT_AT = 0.70  # trigger compaction at 70% utilisation
TOOL_BUDGET = 800  # max tokens returned by any single tool call
KEEP_TURNS = 6  # verbatim turns preserved during compaction
KEEP_OBS = 3  # recent tool observations kept unmasked

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
PRIMARY_MODEL = "gemma-4-12B-it-OptiQ-4bit"


# ===========================================================================
# Utility helpers
# ===========================================================================


def _count_tokens(text: str | list | dict) -> int:
    """Rough estimate: 1 token ~ 4 chars."""
    if isinstance(text, (list, dict)):
        text = json.dumps(text)
    return max(1, len(str(text)) // 4)


def _truncate(text: str, max_tokens: int) -> str:
    limit = max_tokens * 4
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[truncated to {max_tokens} tokens]"


def _spill_to_disk(tool_name: str, content: str) -> str:
    """Write large result to /tmp and return a compact pointer string."""
    ref_id = f"{tool_name}-{uuid.uuid4().hex[:8]}"
    path = TMP_DIR / f"{ref_id}.txt"
    path.write_text(content)
    RESULT_STORE[ref_id] = content
    summary = _truncate(content, 300)
    return (
        f"[LARGE_RESULT ref={ref_id} tokens~{_count_tokens(content)} path={path}]\n"
        f"{summary}"
    )


def _gate_output(tool_name: str, raw: str, budget: int = TOOL_BUDGET) -> str:
    """Compress or spill large tool output before it enters context."""
    if _count_tokens(raw) <= budget:
        return raw
    return _spill_to_disk(tool_name, raw)


def _tool_response(text: str, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "is_error": is_error}


# ===========================================================================
# Context management
# ===========================================================================


def mask_old_observations(
    messages: list[dict], keep_last_n: int = KEEP_OBS
) -> list[dict]:
    """Replace old tool-result messages with a token-count placeholder."""
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for i in tool_indices[:-keep_last_n]:
        tokens = _count_tokens(messages[i].get("content", ""))
        messages[i] = {
            **messages[i],
            "content": f"[OBSERVATION MASKED — ~{tokens} tokens]",
        }
    return messages


def maybe_compact(
    messages: list[dict], context_limit: int = CONTEXT_LIMIT
) -> list[dict]:
    """
    Anchored iterative compaction.
    Evicts old turns into a persistent ANCHOR block.
    Triggered pre-emptively at COMPACT_AT utilisation, not on overflow.
    """
    used = _count_tokens(messages)
    if used / context_limit < COMPACT_AT:
        return messages

    keep = messages[-KEEP_TURNS:]
    evicted = messages[:-KEEP_TURNS]

    if not evicted:
        return messages

    decisions = [
        m["content"][:120]
        for m in evicted
        if m.get("role") == "assistant" and isinstance(m.get("content"), str)
    ]
    anchor_text = "[SESSION ANCHOR]\n" + "\n".join(f"- {d}" for d in decisions[-8:])

    return [
        {"role": "assistant", "content": anchor_text},
        *keep,
    ]


async def safe_run(agent: Agent, query: str) -> str:
    """Pre-flight compaction + single emergency recovery on context overflow."""
    agent.messages = maybe_compact(agent.messages)
    try:
        return await agent.run(query)
    except Exception as exc:
        if any(
            k in str(exc).lower() for k in ("context", "token", "length", "overflow")
        ):
            agent.messages = mask_old_observations(agent.messages, keep_last_n=2)
            agent.messages = maybe_compact(agent.messages, int(CONTEXT_LIMIT * 0.5))
            return await agent.run(query)
        raise


# ===========================================================================
# MCP process management
# ---------------------------------------------------------------------------
# MCP servers are launched as LOCAL PROCESSES via `uvx run <package>`.
# They communicate over stdio (stdin/stdout JSON-RPC 2.0).
#
# Lifecycle:
#   - start_mcp() called ONCE in main() at agent startup
#   - McpClient passed into Tool constructors that need it
#   - All clients terminated in the finally block on exit
#
# Required env vars (set before running agent.py):
#   PERPLEXITY_API_KEY   — for mcp-perplexity-ask
#
# To install MCP packages into the uvx environment:
#   uvx install mcp-perplexity-ask
#   uvx install mcp-server-filesystem   # if you want the official fs MCP
# ===========================================================================


class McpClient:
    """Minimal stdio JSON-RPC 2.0 client for a local MCP process."""

    def __init__(self, proc: subprocess.Popen):
        self._proc = proc
        self._seq = 0

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    async def call(self, method: str, params: dict) -> dict:
        msg = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": method,
                    "params": params,
                }
            )
            + "\n"
        )
        self._proc.stdin.write(msg.encode())
        self._proc.stdin.flush()
        line = await asyncio.get_event_loop().run_in_executor(
            None, self._proc.stdout.readline
        )
        return json.loads(line).get("result", {})

    def terminate(self):
        self._proc.terminate()


def start_mcp(package: str, env_extras: dict | None = None) -> McpClient:
    """
    Launch a local MCP server as a uvx subprocess and return a client.

    The process is started here; Tool constructors receive the client object.
    No tool spawns its own subprocess — all share the processes started here.
    """
    env = {**os.environ, **(env_extras or {})}
    proc = subprocess.Popen(
        ["uvx", "run", package],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    return McpClient(proc)


# ===========================================================================
# Tool definitions
# ===========================================================================

# ---------------------------------------------------------------------------
# Perplexity (via MCP process — requires PERPLEXITY_API_KEY)
# ---------------------------------------------------------------------------


class PerplexityParams(BaseModel):
    query: str = Field(description="Search query or question")
    mode: str = Field(default="search", description="search | ask | research")


class PerplexityTool(Tool):
    """
    Web search/ask/research via Perplexity MCP.
    Returns citations + lead sentences (~400 tokens).
    Full result spilled to /tmp — use Read() if you need the full text.
    MCP process: uvx run mcp-perplexity-ask (started in main())
    """

    name = "Perplexity"
    description = (
        "Web search/research. Returns compressed leads + /tmp path for full result."
    )
    parameters = PerplexityParams

    def __init__(self, mcp: McpClient):
        super().__init__()
        self._mcp = mcp

    def _extract_leads(self, raw: str, max_tokens: int = 400) -> str:
        lines, output = raw.splitlines(), []
        for line in lines:
            if line.startswith("##") or line.startswith("**"):
                output.append(line)
            elif line.strip() and output:
                output.append(line.split(". ")[0])
            if _count_tokens("\n".join(output)) >= max_tokens:
                break
        return "\n".join(output)

    async def execute(self, params: PerplexityParams, signal=None) -> dict:
        try:
            result = await self._mcp.call(
                "tools/call",
                {
                    "name": f"perplexity_{params.mode}",
                    "arguments": {"query": params.query},
                },
            )
            raw = result.get("content", [{}])[0].get("text", "")
        except Exception as exc:
            return _tool_response(f"Perplexity MCP error: {exc}", is_error=True)

        compressed = self._extract_leads(raw)
        if _count_tokens(raw) > TOOL_BUDGET:
            spilled = _spill_to_disk("perplexity", raw)
            tmp_path = spilled.split("path=")[1].split("]")[0].strip()
            compressed += f"\n\n[Full result -> {tmp_path}]"
        return _tool_response(compressed)


# ---------------------------------------------------------------------------
# Repo search (ripgrep)
# ---------------------------------------------------------------------------


class RepoSearchParams(BaseModel):
    pattern: str = Field(description="Regex or literal string")
    path: str = Field(default=".", description="Search root")
    file_glob: str = Field(default="*.py", description="File filter glob")
    max_hits: int = Field(default=20, description="Max lines returned")


class RepoSearchTool(Tool):
    """
    ripgrep search over the repo. Prefer over Ls/Find for large directories.
    Requires: brew install ripgrep
    """

    name = "RepoSearch"
    description = "ripgrep search. Use instead of Ls/Find. Returns file:line matches."
    parameters = RepoSearchParams

    async def execute(self, params: RepoSearchParams, signal=None) -> dict:
        cmd = [
            "rg",
            "--line-number",
            f"--max-count={params.max_hits}",
            "-g",
            params.file_glob,
            params.pattern,
            params.path,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            out = r.stdout.strip() or "(no matches)"
        except FileNotFoundError:
            return _tool_response("rg not found: brew install ripgrep", is_error=True)
        except subprocess.TimeoutExpired:
            return _tool_response("rg timed out (>10s)", is_error=True)
        return _tool_response(_truncate(out, TOOL_BUDGET))


# ---------------------------------------------------------------------------
# Paginated file reader
# ---------------------------------------------------------------------------


class ReadLinesParams(BaseModel):
    path: str = Field(description="File path")
    start: int = Field(default=1, description="Start line (1-indexed)")
    end: int = Field(default=80, description="End line (inclusive)")


class ReadLinesTool(Tool):
    """Read a specific line range. Use RepoSearch first to locate relevant lines."""

    name = "ReadLines"
    description = "Read lines start..end from a file. Default: lines 1-80."
    parameters = ReadLinesParams

    async def execute(self, params: ReadLinesParams, signal=None) -> dict:
        try:
            lines = pathlib.Path(params.path).read_text(errors="replace").splitlines()
        except FileNotFoundError:
            return _tool_response(f"File not found: {params.path}", is_error=True)
        total = len(lines)
        chunk = lines[params.start - 1 : params.end]
        header = (
            f"# {params.path} lines {params.start}-{min(params.end, total)} / {total}\n"
        )
        return _tool_response(_truncate(header + "\n".join(chunk), TOOL_BUDGET))


# ---------------------------------------------------------------------------
# Bash (scoped, hard output ceiling)
# ---------------------------------------------------------------------------


class BashParams(BaseModel):
    command: str = Field(description="Shell command to run")
    cwd: str = Field(default=".", description="Working directory")
    timeout: int = Field(default=30, description="Timeout seconds")


RISKY_BASH = ["rm -rf", "dd if=", "mkfs", ":(){:|:&}", "shutdown", "reboot", "sudo"]


class BashTool(Tool):
    """Run a shell command. Output capped at TOOL_BUDGET tokens. Destructive patterns blocked."""

    name = "Bash"
    description = "Shell command. Output capped. Destructive patterns blocked."
    parameters = BashParams

    async def execute(self, params: BashParams, signal=None) -> dict:
        if any(p in params.command for p in RISKY_BASH):
            return _tool_response(
                f"Blocked risky command: {params.command}", is_error=True
            )
        try:
            r = subprocess.run(
                params.command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=params.cwd,
                timeout=params.timeout,
            )
            out = (r.stdout + r.stderr).strip() or "(no output)"
            return _tool_response(_gate_output("bash", out))
        except subprocess.TimeoutExpired:
            return _tool_response(f"Timed out after {params.timeout}s", is_error=True)


# ---------------------------------------------------------------------------
# Execute cell (Jupyter only)
# ---------------------------------------------------------------------------


class ExecCellParams(BaseModel):
    code: str = Field(description="Python code to execute in the notebook kernel")
    dry_run: bool = Field(
        default=False, description="Stage for review without executing"
    )


_SAFE_PATS = {"pd.", "pl.", "plt.", "print(", "df.", "np.", "sns.", "display("}
_RISKY_PATS = {"open(", "os.remove", "shutil", "subprocess", "write(", "unlink"}


class ExecuteCellTool(Tool):
    """
    Execute or stage a Python cell in the host Jupyter notebook kernel.
    Risky patterns automatically staged for human review.
    No-op outside a Jupyter kernel.
    """

    name = "ExecuteCell"
    description = "Run Python in notebook kernel. Risky code staged for review."
    parameters = ExecCellParams

    async def execute(self, params: ExecCellParams, signal=None) -> dict:
        ip = _IPYTHON
        if ip is None:
            return _tool_response("Not in a Jupyter kernel — ExecuteCell unavailable.")
        is_risky = any(p in params.code for p in _RISKY_PATS)
        if params.dry_run or is_risky:
            note = "# Agent-generated — review before running\n" if is_risky else ""
            ip.set_next_input(note + params.code, replace=False)
            return _tool_response(
                "Staged for review ("
                + ("risky pattern" if is_risky else "dry_run")
                + ")"
            )
        result = ip.run_cell(params.code)
        if result.error_in_exec:
            return _tool_response(str(result.error_in_exec), is_error=True)
        out = str(result.result) if result.result is not None else "(executed)"
        return _tool_response(_truncate(out, TOOL_BUDGET))


# ---------------------------------------------------------------------------
# Memory (Chroma + sentence-transformers)
# ---------------------------------------------------------------------------


class MemoryParams(BaseModel):
    query: str = Field(description="Semantic query over past sessions")
    top_k: int = Field(default=3, description="Results to return")
    store: str = Field(default="", description="Text to store (empty = query mode)")


class MemoryTool(Tool):
    """Semantic memory across sessions. Backend: Chroma + all-MiniLM-L6-v2 (~80MB)."""

    name = "Memory"
    description = "Store or retrieve facts/snippets across sessions."
    parameters = MemoryParams

    def __init__(self):
        super().__init__()
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            try:
                import chromadb
                from sentence_transformers import SentenceTransformer

                db_path = pathlib.Path.home() / ".agent" / "memory"
                db_path.mkdir(parents=True, exist_ok=True)
                self._embedder = SentenceTransformer(EMBEDDING_MODEL)
                self._chroma = chromadb.PersistentClient(path=str(db_path))
                self._collection = self._chroma.get_or_create_collection("sessions")
            except ImportError:
                return None
        return self._collection

    async def execute(self, params: MemoryParams, signal=None) -> dict:
        coll = self._get_collection()
        if coll is None:
            return _tool_response(
                "Memory unavailable: pip install chromadb sentence-transformers"
            )
        if params.store:
            emb = self._embedder.encode([params.store])[0].tolist()
            coll.add(documents=[params.store], embeddings=[emb], ids=[uuid.uuid4().hex])
            return _tool_response("Stored.")
        emb = self._embedder.encode([params.query])[0].tolist()
        results = coll.query(query_embeddings=[emb], n_results=params.top_k)
        docs = results.get("documents", [[]])[0]
        return _tool_response(
            _truncate(
                "\n---\n".join(docs) if docs else "No memories found.", TOOL_BUDGET
            )
        )


# ===========================================================================
# System prompt
# ===========================================================================

SYSTEM = """You are a laptop-scale code generation agent (M1 MacBook, 16 GB, MLX).

Tool discipline:
- Use RepoSearch instead of Ls/Find for any non-trivial codebase.
- Use ReadLines(path, start, end) to read specific sections; never read whole large files.
- Perplexity returns a compressed summary + /tmp path. Call Read(/tmp/...) only if you need full detail.
- Bash output is capped — pipe to head/tail if you expect large output.
- ExecuteCell is only available inside a Jupyter kernel.
- Use Memory.store to save useful facts, decisions, and file locations for future sessions.

Token discipline:
- Prefer narrow targeted tool calls over broad exploratory ones.
- Do not re-read files already seen this session unless they changed.
- Reference code by filename:line rather than repeating it verbatim.
"""


# ===========================================================================
# Entry point
# ===========================================================================


async def main():
    # ------------------------------------------------------------------
    # MCP SERVER STARTUP
    # ------------------------------------------------------------------
    # MCP servers run as LOCAL PROCESSES (uvx run <package>) and
    # communicate over stdio. They are started ONCE here and their
    # client handles are passed into Tool constructors.
    #
    # Install MCP packages:
    #   pip install uvx
    #   uvx install mcp-perplexity-ask
    #
    # Required env vars:
    #   export PERPLEXITY_API_KEY=pplx-...
    # ------------------------------------------------------------------
    mcp_clients = []

    perplexity_mcp = None
    if pplx_key := os.environ.get("PERPLEXITY_API_KEY"):
        perplexity_mcp = start_mcp(
            "mcp-perplexity-ask",
            env_extras={"PERPLEXITY_API_KEY": pplx_key},
        )
        mcp_clients.append(perplexity_mcp)

    # ------------------------------------------------------------------
    # TOOL INSTANTIATION
    # ------------------------------------------------------------------
    tools: list[Tool] = [
        RepoSearchTool(),
        ReadLinesTool(),
        BashTool(),
        ExecuteCellTool(),
        MemoryTool(),
    ]
    if perplexity_mcp:
        tools.append(PerplexityTool(mcp=perplexity_mcp))

    # ------------------------------------------------------------------
    # AGENT
    # ------------------------------------------------------------------
    agent = Agent(
        system=SYSTEM,
        extra_tool_classes=[type(t) for t in tools],
        tool_names=[
            "Read",
            "Write",
            "Edit",
            "Grep",  # mlx-code builtins
            "RepoSearch",
            "ReadLines",
            "Bash",
            "ExecuteCell",
            "Memory",
            *(["Perplexity"] if perplexity_mcp else []),
        ],
    )

    # ------------------------------------------------------------------
    # RUN — interactive REPL or stdin pipe (non-TTY)
    # ------------------------------------------------------------------
    try:
        await repl(agent, run_fn=safe_run)
    finally:
        for client in mcp_clients:
            client.terminate()


if __name__ == "__main__":
    asyncio.run(main())
