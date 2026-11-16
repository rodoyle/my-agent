#!/bin/sh
# Load skills/extensions from the gitFS at $PI_CODING_AGENT_DIR (the agent
# directory), not from the repo checkout. The agent directory is a PVC
# populated by an initContainer that clones github.com/rodoyle/my-agent.git.
set -eu
exec pi \
  --mode rpc \
  --no-session \
  --thinking high \
  --tools read,grep,find,ls,write,edit,bash \
  --no-extensions \
  --no-skills \
  --no-prompt-templates \
  --extension "${PI_CODING_AGENT_DIR}/extensions/task-contract.ts" \
  --skill "${PI_CODING_AGENT_DIR}/skills/task-execution" \
  --skill "${PI_CODING_AGENT_DIR}/skills/verification" \
  --skill "${PI_CODING_AGENT_DIR}/skills/kubernetes-dev" \
  --append-system-prompt "$(cat "${PI_CODING_AGENT_DIR}/APPEND_SYSTEM.md")"