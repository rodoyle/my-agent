#PYAGENT

Local coding agent written with mlx-code. Largely intended to be called SDK-style from within a jupyter or quarto notebook session.

## Prompt and Task Structure
[Stable, versioned Pi system prompt]
[Stable agent-class policy]
[Stable repository AGENTS.md-derived instructions]
[Stable skill content or skill identifiers]
[Stable tool schemas]

[Per-run task contract: issue, branch, allowed paths, budget]
[Per-turn tool result / new event]

## Mounts
/opt/pi-base/                 read-only: global skills, extensions, models policy
/workspace/.pi/               repository checkout: project policy
/run/pi/sessions/<run-id>/    writable and unique
/workspace/.agent/            writable and unique task artifacts