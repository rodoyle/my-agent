---
name: task-execution
description: Execute bounded repository tasks autonomously from .agent/task.json.
---

# Task execution

Use this skill for every automated issue task.

1. Read `.agent/task.json` and validate that required fields exist.
2. Read the nearest `AGENTS.md` files and relevant repository docs.
3. Inspect existing tests and analogous implementation before editing.
4. Keep changes within `allowed_paths`.
5. Implement the minimum complete solution.
6. Run every `required_checks` command through `agentctl`.
7. If a check fails, diagnose from output, make one targeted correction, and rerun.
8. After the validation-cycle budget is reached, emit `FAILED` with the complete
   failing command, output location, and best diagnosis.
9. Always write `.agent/result.json`.
