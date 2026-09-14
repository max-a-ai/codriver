#!/usr/bin/env bash
# Stand-in for the real recording script, so the topic switches can be driven on
# a laptop. The panel appends the selected topics as arguments and also puts
# them in CODRIVER_TOPICS; a real script would pass them straight to
# `ros2 bag record -o ~/recordings/$(date +%Y%m%d_%H%M%S) "$@"`.
set -euo pipefail

trap 'echo "recording: caught SIGINT, closing the bag"; exit 0' INT
trap 'echo "recording: caught SIGTERM, closing the bag"; exit 0' TERM

echo "recording: would record $# topics"
for topic in "$@"; do
  echo "recording:   $topic"
done
if [ -n "${CODRIVER_TOPICS:-}" ]; then
  echo "recording: CODRIVER_TOPICS carries the same list"
else
  echo "recording: CODRIVER_TOPICS is empty"
fi
echo "recording: ready"

while true; do
  sleep 1
done
