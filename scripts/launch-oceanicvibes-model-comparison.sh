#!/usr/bin/env bash
set -euo pipefail

# Launch the read-only three-model comparison UI for a retained matrix.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON_FALLBACK:-python3}"
fi

MODEL_ROOT="${1:-${DESIGN_LAB_MATRIX_WORKSPACE:-/tmp/site-agent-design-lab/oceanicvibes-three-models}}"
MANIFEST="$MODEL_ROOT/model-comparison.json"
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

if [[ ! -f "$MANIFEST" ]]; then
  printf '%s\n' "No model comparison manifest found at $MANIFEST. Run compare-oceanicvibes-models.sh first." >&2
  exit 1
fi

printf '%s\n' "Launching OceanicVibes three-model comparison UI"
exec "$PYTHON" -m site_agent.main design-lab compare \
  --manifest "$MANIFEST" \
  --host "$HOST" \
  --port "$PORT"
