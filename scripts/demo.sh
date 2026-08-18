#!/bin/sh
# Run the tool end to end against declared synthetic
# readings, printing exactly what a user would see.
#
# Synthetic on purpose. A transcript captured against real
# accounts would publish the operator's actual quota, and the
# behaviour being demonstrated does not depend on the numbers
# being real.
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
work=${1:-$(mktemp -d)}
export AGENT_USAGE_STATE_DIR="$work"
export PYTHONPATH="$root"

echo "# Readings below are synthetic. No provider account was"
echo "# contacted and no real quota appears in this transcript."
echo
echo "\$ agent-usage doctor"
python3 -m agent_usage.cli --state-dir "$work" doctor |
  python3 "$root/scripts/seed_demo.py" --redact-doctor

echo
echo "\$ agent-usage collect   # synthetic readings, seeded"
python3 "$root/scripts/seed_demo.py" --seed "$work"

echo
echo "\$ agent-usage report"
python3 -m agent_usage.cli --state-dir "$work" report

echo
echo "\$ agent-usage forecast claude"
python3 -m agent_usage.cli --state-dir "$work" forecast claude
