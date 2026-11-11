# Declarative agent profile verification

## Implementation

The extension catalog is `base/runtime/package.json` → `piImage.extensions`.
Versions remain in npm dependencies and the committed lockfile. Profile JSON
selects that installed catalog and Pi settings; the build compiles absolute
local-package sources. Every image sets its own `AGENT_PROFILE`.

The entrypoint initializes empty state and updates settings only while a hash
marker proves they remain image-managed. Operator edits and unmarked legacy
settings are preserved. The Kaniko source allowlist includes the compiler and
all four profiles. Every image has a profile-aware, credential-free RUN gate.

## Observed checks

- `node --test tests/profile-config.test.mjs`: 4 passed, 0 failed. Covers shipped
  inheritance/settings, resource filtering, invalid input, profile switching and
  preservation of operator edits.
- `python3 -m unittest discover -s tests -v`: 7 passed, 0 failed. The startup
  fixture runs the real entrypoint and initializer with relocated fixture paths.
- Active LSP checks: 10 changed source files, zero diagnostics.
- Node syntax, shell syntax and `git diff --check` passed.
- A clean temporary runtime installed the committed npm graph with
  `npm ci --ignore-scripts --no-audit --no-fund --userconfig=/dev/null`, followed
  by the explicit ast-grep postinstall. Fresh isolated Pi RPC processes loaded
  the expected package commands: base 4, devpod 4, headless 0, template 4.
  Each returned successful `get_state` and `get_commands` responses, without
  provider requests, credentials, human configuration or project resources.
  Temporary runtime/check script: `/tmp/agent-profile-verification/`.

## Correction and boundaries

The old startup fixture assumed one flat defaults file and a copy-only
entrypoint. After initialization moved to Node it failed with MODULE_NOT_FOUND.
The fixture now relocates both defaults and the real initializer, and uses the
profile defaults directory layout. No startup behavior was mocked in the final
fixture.

These are local macOS checks on Node 26.8.2, not a claim that updated Linux
images were built or deployed. The earlier image digests in
`agent-images-verification.md` predate these profile changes. The image runtime
remains pinned to Node 22.23.4. No cluster grant was requested or used for this
profile verification; an actual Kaniko rebuild needs a task-pinned temporary
build grant and its usual cleanup. No model inference or authenticated service
workflow was exercised.
