---
name: verification
description: Run repository verification and perform bounded fix-and-retest cycles.
---

# Verification contract

Required checks are mandatory. A successful edit is not a successful task.

- Run static checks before expensive integration checks where possible.
- Do not delete, skip, weaken, or mark tests xfail to obtain a green result
  unless that exact change is an acceptance criterion.
- Record command, exit status, duration, and a concise outcome in result.json.
- For Kubernetes work, rendering and static schema validation do not prove
  runtime behavior. If the task authorizes dev-cluster verification, perform:
  apply -> wait/watch -> inspect events/logs -> fix -> reapply.
- Use the task contract's namespace and release only. Never infer a namespace
  from local kubeconfig context.