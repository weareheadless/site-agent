#!/usr/bin/env bash
set -euo pipefail

# Launch the read-only comparison UI for a retained local design-lab run.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON_FALLBACK:-python3}"
fi

WORKSPACE="${1:-${DESIGN_LAB_WORKSPACE:-/tmp/site-agent-design-lab/oceanicvibes-prompted}}"
RUN_ID="${2:-${DESIGN_LAB_RUN_ID:-}}"
HOST="${DESIGN_LAB_HOST:-127.0.0.1}"
if [[ -n "${DESIGN_LAB_PORT:-}" ]]; then
  PORT="$DESIGN_LAB_PORT"
else
  PORT="$($PYTHON - <<'PY'
import socket

for candidate in range(8765, 8785):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", candidate))
        except OSError:
            continue
        print(candidate)
        break
else:
    raise SystemExit("No free comparison port found in 8765-8784. Set DESIGN_LAB_PORT explicitly.")
PY
  )"
fi

if [[ -z "$RUN_ID" ]]; then
  RUN_ID="$({
    "$PYTHON" - "$WORKSPACE" <<'PY'
from pathlib import Path
import sys

workspace = Path(sys.argv[1]).expanduser().resolve()
runs = [path for path in (workspace / "reports").glob("*/run.json") if path.is_file()]
if not runs:
    raise SystemExit("No retained design-lab runs found. Run generate-oceanicvibes-test.sh first.")
print(max(runs, key=lambda path: path.stat().st_mtime).parent.name)
PY
  })"
fi

printf '%s\n' "Launching OceanicVibes comparison UI"

exec "$PYTHON" -m site_agent.main design-lab serve \
  --workspace "$WORKSPACE" \
  --run "$RUN_ID" \
  --host "$HOST" \
  --port "$PORT"
