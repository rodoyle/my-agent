# Build context: agents/. This is a Pi RPC worker, NOT the unfinished SDK
# controller in src/index.ts. The external controller owns task/workspace policy.
ARG BASE_IMAGE=ghcr.io/rodoyle/agents-base:latest
FROM ${BASE_IMAGE}
USER 1000:1000
WORKDIR /workspace
# Retain the base init/entrypoint. Do not auto-trust checkout-supplied executable
# resources in unattended mode. Controllers may add reviewed explicit -e paths.
CMD ["pi", "--mode", "rpc", "--no-session", "--no-approve", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files"]
