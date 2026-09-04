#!/usr/bin/env bash
# Stand-in for a real pipeline launcher, so the panel can be driven on a laptop.
#
#   fake_pipeline.sh <name> [seconds-until-ready] [exit-after-seconds]
#
# Prints a startup line, waits, announces itself ready, then idles until it is
# interrupted. Exits non-zero if a third argument is given, which is how the
# crashed light gets exercised.
set -euo pipefail

name="${1:-pipeline}"
ready_after="${2:-3}"
die_after="${3:-}"

trap 'echo "$name: caught SIGINT, shutting down"; exit 0' INT
trap 'echo "$name: caught SIGTERM, shutting down"; exit 0' TERM

echo "$name: starting up"
sleep "$ready_after"

if [ -n "$die_after" ]; then
  echo "$name: something went wrong" >&2
  sleep "$die_after"
  exit 1
fi

echo "$name: ready"
while true; do
  sleep 1
done
