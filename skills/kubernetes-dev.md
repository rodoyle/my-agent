---
name: kubernetes-dev
description: Safely validate authorized Kubernetes changes in the designated development namespace.
---

# Kubernetes development validation

Read `.agent/environment.yaml`. It is authoritative for context, namespace,
release, timeout, and allowed verbs.

Use only:
- `agentctl k8s render ...`
- `agentctl k8s apply ...`
- `agentctl k8s wait ...`
- `agentctl k8s events ...`
- `agentctl k8s logs ...`
- `agentctl k8s cleanup ...`

After an apply:
1. Wait for the workload's declared readiness condition.
2. Inspect pod events and container logs on failure.
3. Correct only the failure that evidence supports.
4. Re-run rendering and validation after every manifest change.
5. Clean up only resources labeled with this run ID.

Never target a context or namespace absent from environment.yaml.
