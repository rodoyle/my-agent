# Build context: agents/. Build/push base first with Kaniko, then pass its
# immutable registry reference as BASE_IMAGE. Inherits Pi, extensions and Ovis.
ARG BASE_IMAGE=ghcr.io/rodoyle/agents-base:latest
FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash-completion fd-find less nano openssh-client ripgrep tmux \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd
# Pin, verify and select the native architecture; no curl-to-shell installer.
# Match this version to the cluster's supported +/-1 minor skew before building.
ARG KUBECTL_VERSION=v1.36.6
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in amd64|arm64) ;; *) exit 1 ;; esac \
    && curl --fail --location --retry 3 --max-time 120 \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl" \
      -o /tmp/kubectl \
    && curl --fail --location --retry 3 --max-time 60 \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl.sha256" \
      -o /tmp/kubectl.sha256 \
    && echo "$(cat /tmp/kubectl.sha256)  /tmp/kubectl" | sha256sum --check - \
    && install -m 755 /tmp/kubectl /usr/local/bin/kubectl \
    && rm /tmp/kubectl /tmp/kubectl.sha256
USER 1000:1000
WORKDIR /workspace
RUN kubectl version --client=true --output=json \
    && agent-entrypoint node /opt/agent-tests/image-smoke.mjs \
    && rm -rf /home/agent/.pi/agent/* /home/agent/.pi-lens
# Deliberately no sudo, kubeconfig, credential, service auto-start or public port.
CMD ["bash"]
