#!/bin/sh
# Mount a writable agent directory, not over /opt/pi-runtime or /opt/pi-defaults.
set -eu
: "${HOME:=/home/agent}"
: "${PI_CODING_AGENT_DIR:=$HOME/.pi/agent}"
export HOME PI_CODING_AGENT_DIR
mkdir -p "$PI_CODING_AGENT_DIR"
# Preserve operator settings, including deliberate package filters. First start
# with an empty mounted HOME still gets every image-provided package.
if [ ! -e "$PI_CODING_AGENT_DIR/settings.json" ]; then
    cp /opt/pi-defaults/settings.json "$PI_CODING_AGENT_DIR/settings.json"
fi
if [ "$#" -eq 0 ]; then
    set -- pi
fi
exec "$@"
