#!/bin/sh
# Mount a writable agent directory, not over /opt/pi-runtime or /opt/pi-defaults.
set -eu
: "${HOME:=/home/agent}"
: "${PI_CODING_AGENT_DIR:=$HOME/.pi/agent}"
: "${AGENT_PROFILE:=base}"
export HOME PI_CODING_AGENT_DIR AGENT_PROFILE
mkdir -p "$PI_CODING_AGENT_DIR"
# Seed empty state and safely refresh only settings still matching our marker.
# A mounted HOME can therefore switch image profiles without overwriting edits.
node /opt/pi-runtime/profile-config.mjs initialize \
    /opt/pi-defaults "$PI_CODING_AGENT_DIR" "$AGENT_PROFILE"
if [ "$#" -eq 0 ]; then
    set -- pi
fi
exec "$@"
