#!/bin/sh
# Start `herdr server` separately as this same user before launching Ovis.
set -eu
: "${HOST:=127.0.0.1}"
: "${PORT:=7317}"
# Terminals are write-capable. Fail closed for all non-loopback bind addresses.
case "$HOST" in
    127.0.0.1|localhost|::1) ;;
    *)
        if [ -z "${OVIS_TOKEN:-}" ]; then
            echo 'Remote Ovis binding requires a user-supplied OVIS_TOKEN.' >&2
            exit 64
        fi
        ;;
esac
export HOST PORT
export OVIS_AUTO_UPDATE=0 OVIS_NO_OPEN=1
cd /opt/ovis
# Assets and the checked Rust PTY host were baked in; no runtime build/update.
exec bun run server/index.ts "$@"
