# Build context: agents/ (not base/). See docs/plans/agent-images.md.
ARG NODE_IMAGE=docker.io/library/node:22.23.4-bookworm-slim
ARG BUN_IMAGE=docker.io/oven/bun:1.4.4
FROM ${BUN_IMAGE} AS bun

FROM ${NODE_IMAGE} AS runtime
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git gh jq procps tini unzip \
    && rm -rf /var/lib/apt/lists/*
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
RUN ln -s /usr/local/bin/bun /usr/local/bin/bunx

# Keep Pi on Node; Bun is separate tooling, NOT a replacement node executable.
WORKDIR /opt/pi-runtime
COPY base/runtime/package.json base/runtime/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
    && node node_modules/@ast-grep/cli/postinstall.js \
    && ln -s /opt/pi-runtime/node_modules/.bin/pi /usr/local/bin/pi \
    && ln -s /opt/pi-runtime/node_modules/.bin/ast-grep /usr/local/bin/ast-grep \
    && npm cache clean --force

ENV PI_OFFLINE=1 PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0
# Register locked local packages with Pi itself, rather than merely npm-installing
# extensions and hoping discovery sees them. This seed is copied on first start.
RUN for package in pi-subagents pi-lens pi-goal-list-loop-audit pi-intercom; do \
      PI_CODING_AGENT_DIR=/opt/pi-defaults pi install "/opt/pi-runtime/node_modules/$package"; \
    done \
    && node -e 'const fs=require("node:fs"),path=require("node:path"); const file="/opt/pi-defaults/settings.json"; const settings=JSON.parse(fs.readFileSync(file,"utf8")); settings.packages=settings.packages.map(source=>path.resolve("/opt/pi-defaults",source)); fs.writeFileSync(file,JSON.stringify(settings,null,2)+"\n");'

# Herdr is a Rust binary, not the unrelated npm package named "herdr".
ARG HERDR_VERSION=0.9.5
ARG HERDR_SHA256_AMD64=14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d
ARG HERDR_SHA256_ARM64=17d7536f2da50859523680ef279dffcac8e4a235f4e46fe8da6c2ec44141897c
RUN case "$(dpkg --print-architecture)" in \
      amd64) arch=x86_64; checksum="$HERDR_SHA256_AMD64" ;; \
      arm64) arch=aarch64; checksum="$HERDR_SHA256_ARM64" ;; \
      *) echo 'Unsupported Herdr architecture' >&2; exit 1 ;; \
    esac \
    && curl --fail --location --retry 3 --max-time 120 \
      "https://github.com/herdrdev/herdr/releases/download/v${HERDR_VERSION}/herdr-linux-${arch}" \
      -o /usr/local/bin/herdr \
    && echo "$checksum  /usr/local/bin/herdr" | sha256sum --check - \
    && chmod 755 /usr/local/bin/herdr

FROM runtime AS ovis-build
# github.com/devswha/herdr-web-ui redirects to devswha/ovis. Pin the release
# commit as well as its dependency lock; never update or build on container start.
ARG OVIS_REF=c99017754cb330143589afb2f74473828b86615e
RUN git init /opt/ovis \
    && cd /opt/ovis \
    && git remote add origin https://github.com/devswha/ovis.git \
    && git fetch --depth=1 origin "$OVIS_REF" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "$OVIS_REF" \
    && bun install --frozen-lockfile \
    && bun scripts/pty-sidecar.ts install --strict \
    && bun run build \
    && rm -rf .git

FROM runtime AS base
COPY --from=ovis-build /opt/ovis /opt/ovis
COPY base/agent-entrypoint.sh /usr/local/bin/agent-entrypoint
COPY base/ovis.sh /usr/local/bin/ovis
COPY tests/image-smoke.mjs /opt/agent-tests/image-smoke.mjs
RUN chmod 755 /usr/local/bin/agent-entrypoint /usr/local/bin/ovis \
    && usermod --login agent --home /home/agent --move-home node \
    && groupmod --new-name agent node \
    && mkdir -p /workspace /home/agent/.pi/agent /home/agent/.config \
    && chown -R 1000:1000 /workspace /home/agent
ENV HOME=/home/agent \
    PI_CODING_AGENT_DIR=/home/agent/.pi/agent \
    PI_CODING_AGENT_SESSION_DIR=/home/agent/.pi/agent/sessions \
    OVIS_STATE_DIR=/home/agent/.config/ovis \
    OVIS_AUTO_UPDATE=0 OVIS_NO_OPEN=1 \
    TERM=xterm-256color
USER 1000:1000
WORKDIR /workspace
# No provider calls/credentials: exercise Node, native modules and Pi RPC loading.
RUN agent-entrypoint node /opt/agent-tests/image-smoke.mjs \
    && rm -rf /home/agent/.pi/agent/* /home/agent/.pi-lens
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agent-entrypoint"]
CMD ["pi"]
