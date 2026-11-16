# Build context: agents/. Build/push base first with Kaniko, then pass its
# immutable registry reference as BASE_IMAGE. Inherits Pi, extensions, Ovis and kubectl.
ARG BASE_IMAGE=ghcr.io/rodoyle/agents-base:latest
FROM ${BASE_IMAGE}
ENV AGENT_PROFILE=devpod
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash-completion fd-find less nano openssh-client ripgrep tmux \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd
USER 1000:1000
WORKDIR /workspace
RUN agent-entrypoint node /opt/agent-tests/image-smoke.mjs \
    && rm -rf /home/agent/.pi/agent/* /home/agent/.pi-lens
# Deliberately no sudo, kubeconfig, credential, service auto-start or public port.
CMD ["bash"]
