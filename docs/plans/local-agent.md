# Laptop-Scale Code Generation Agent — Quick Reference

## Architecture Summary

```
mlx_lm.server :8080          <- inference (Qwen2.5-Coder-7B-4bit, MLX native)
     |
agent.py (mlx-code harness)  <- Tool subclasses, context management, safe_run()
     |
MCP processes (uvx run ...)  <- started by agent.py, communicate over stdio
     |
 Tools: RepoSearch | ReadLines | Bash | ExecuteCell | Memory | Perplexity
```

**Key design decisions:**

- All context compression is code, not prompt engineering — no tokens wasted coaxing behaviour
- Tool output is gated at `TOOL_BUDGET = 800 tokens` before it enters `agent.messages`
- MCP servers are owned by `main()`, not by individual tools — one process per server, shared client
- Compaction fires pre-emptively at 70% context utilisation, not on overflow

---

## Prerequisites

```bash
# Python deps
pip install "mlx-lm[server]" mlx-code chromadb sentence-transformers

# System tools (Homebrew)
brew install ripgrep     # RepoSearchTool
brew install tokei       # optional: LOC stats
brew install delta       # optional: pretty diffs

# MCP packages (Perplexity)
pip install uvx
uvx install mcp-perplexity-ask

# Model weights (~4.3 GB, downloaded on first run)
python -m mlx_lm.convert \
  --hf-path Qwen/Qwen2.5-Coder-7B-Instruct \
  --mlx-path ~/.agent/models/qwen2.5-coder-7b-4bit \
  -q
```

---

## Starting the MLX Inference Server

Always start the server before running `agent.py`. It binds to `localhost:8080`
and exposes an OpenAI-compatible API. The `--context-size 32768` is the ceiling;
`agent.py` manages staying well under it.

```bash
# Standard startup
mlx_lm.server \
  --model ~/.agent/models/qwen2.5-coder-7b-4bit \
  --port 8080 \
  --host 127.0.0.1 \
  --context-size 32768

# Background (e.g., in a tmux pane)
mlx_lm.server --model ~/.agent/models/qwen2.5-coder-7b-4bit --port 8080 &
```

The server loads the model once and keeps it resident. Leave it running for the
full session — cold-load time on M1 16GB is ~8 seconds.

---

## MCP Process Lifecycle

MCP servers are **local stdio processes** started by `agent.py` at startup via `uvx run`.
They are NOT started by individual tools. The flow is:

```
main()
  └── start_mcp("mcp-perplexity-ask")  ->  McpClient (wraps subprocess.Popen)
        └── passed into PerplexityTool(mcp=perplexity_mcp)
              └── tool calls mcp.call("tools/call", {...}) over stdin/stdout
  └── finally: client.terminate()      ->  subprocess killed on exit
```

**Required environment variable:**

```bash
export PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxxxxxxxxxxxxxx
```

Set this before starting `agent.py`. If the key is absent, the Perplexity tool
is silently omitted from the tool list — the agent runs without it.

**Adding more MCP servers** (e.g., official filesystem MCP):

```python
# In main(), alongside the Perplexity block:
fs_mcp = start_mcp("mcp-server-filesystem")
mcp_clients.append(fs_mcp)
# Then pass fs_mcp into a custom FilesystemMcpTool(mcp=fs_mcp)
```

---

## Running the Agent

### Interactive REPL

```bash
# Terminal 1: server (keep running)
mlx_lm.server --model ~/.agent/models/qwen2.5-coder-7b-4bit --port 8080

# Terminal 2: agent
export PERPLEXITY_API_KEY=pplx-...
python agent.py
```

### One-Shot Pipe

```bash
echo "refactor auth.py to use async/await" | python agent.py
```

### Pipe chaining

```bash
# Research then implement in two passes
echo "research gRPC retry strategies for Python" | python agent.py > research.md
cat research.md | python agent.py --system "implement the top retry strategy in grpc_client.py"
```

### Feed a file as context

```bash
cat src/main.py | python agent.py
```

### Watch mode (re-run on file change)

```bash
# Requires: brew install entr
ls src/*.py | entr -s 'echo "what changed?" | python agent.py'
```

---

## Jupyter Notebook Usage

```python
# Cell 1 — start server as background process (run once per session)
import subprocess, time
server = subprocess.Popen([
    "python", "-m", "mlx_lm.server",
    "--model", "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    "--port", "8080",
])
time.sleep(8)  # wait for model load
print(f"Server PID: {server.pid}")
```

```python
# Cell 2 — import and wire up the agent
import os, sys
os.environ["PERPLEXITY_API_KEY"] = "pplx-..."
sys.path.insert(0, ".")  # if agent.py is in cwd

from agent import Agent, safe_run, PerplexityTool, RepoSearchTool
from agent import ReadLinesTool, BashTool, ExecuteCellTool, MemoryTool, start_mcp, SYSTEM

perplexity_mcp = start_mcp("mcp-perplexity-ask",
                            env_extras={"PERPLEXITY_API_KEY": os.environ["PERPLEXITY_API_KEY"]})
agent = Agent(
    system=SYSTEM,
    extra_tool_classes=[RepoSearchTool, ReadLinesTool, BashTool, ExecuteCellTool, MemoryTool, PerplexityTool],
    tool_names=["Read","Write","Edit","Grep","RepoSearch","ReadLines","Bash","ExecuteCell","Memory","Perplexity"],
)
# Inject live kernel handle for ExecuteCell
import agent as ag
from IPython import get_ipython
ag._IPYTHON = get_ipython()
```

```python
# Cell 3 — use await directly (Jupyter has a running event loop)
response = await safe_run(agent, "explain the retry logic in grpc_client.py")
print(response)
```

```python
# Cell 4 — streaming output
async for chunk in agent.stream("write unit tests for parser.py"):
    print(chunk, end="", flush=True)
```

```python
# Cleanup
server.terminate()
perplexity_mcp.terminate()
```

---

## Context Budget (After Compression)

| Slot | Budget | Mechanism |
|---|---|---|
| System prompt + minimal schemas | ~600 tokens | Pydantic one-liners, no examples |
| Session anchor (compacted history) | ~500 tokens | `maybe_compact()` at 70% utilisation |
| Last 6 verbatim turns | ~2,000 tokens | `KEEP_TURNS = 6` |
| Tool results (gated) | ~1,200 tokens | `_gate_output()` + `mask_old_observations()` |
| Code generation headroom | ~6,000 tokens | |
| **Total in-context** | **~10,300 tokens** | **~10k of 32k used** |

---

## Tuning Constants (top of agent.py)

| Constant | Default | Effect |
|---|---|---|
| `CONTEXT_LIMIT` | 32768 | Must match `--context-size` on the server |
| `COMPACT_AT` | 0.70 | Compact when context is 70% full |
| `TOOL_BUDGET` | 800 | Max tokens any single tool returns |
| `KEEP_TURNS` | 6 | Verbatim turns kept after compaction |
| `KEEP_OBS` | 3 | Recent tool observations kept unmasked |

---

## Adding a Custom Tool

```python
from mlx_code.tools import Tool
from pydantic import BaseModel, Field
import subprocess

class MyToolParams(BaseModel):
    target: str = Field(description="What to operate on")

class MyTool(Tool):
    name        = "MyTool"
    description = "One sentence. No examples — keeps schema tokens minimal."
    parameters  = MyToolParams

    async def execute(self, params: MyToolParams, signal=None) -> dict:
        result = subprocess.run(["my-cli", params.target],
                                capture_output=True, text=True, timeout=10)
        return _tool_response(_truncate(result.stdout, TOOL_BUDGET))
```

Register in `main()`:

```python
tools.append(MyTool())
# and add "MyTool" to the tool_names list in Agent(...)
```
