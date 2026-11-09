# Specialist image template. Build context is agents/.
# Always supply the tested base digest/tag; never reinstall Pi under Bun here.
ARG BASE_IMAGE=ghcr.io/rodoyle/agents-base:latest
FROM ${BASE_IMAGE}
# USER root
# RUN apt-get update && apt-get install -y --no-install-recommends <tools> \
#     && rm -rf /var/lib/apt/lists/*
USER 1000:1000
WORKDIR /workspace
CMD ["pi"]
