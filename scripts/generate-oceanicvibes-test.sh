#!/usr/bin/env bash
set -euo pipefail

# Generate a disposable, local-only initial homepage candidate. The checked-in
# intake is the creative input; use the optional environment overrides below
# when a repeatable test needs a different intake or owner request.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON_FALLBACK:-python3}"
fi

WORKSPACE="${1:-${DESIGN_LAB_WORKSPACE:-/tmp/site-agent-design-lab/oceanicvibes-prompted}}"
PLANNER="${DESIGN_LAB_PLANNER:-llm}"
MODEL="${DESIGN_LAB_MODEL:-}"
TIMEOUT="${DESIGN_LAB_TIMEOUT:-900}"
RUN_ID="${DESIGN_LAB_RUN_ID:-}"
CONFIG="${SITE_AGENT_CONFIG:-}"
ENV_FILE="${SITE_AGENT_ENV_FILE:-}"
SOURCE_INTAKE="${DESIGN_LAB_INTAKE_FILE:-$ROOT_DIR/examples/oceanicvibes.intake.json}"
PROMPT_FILE="${DESIGN_LAB_INTAKE_PROMPT_FILE:-}"
PROMPT_TEXT="${DESIGN_LAB_INTAKE_PROMPT:-}"

if [[ -z "$CONFIG" ]]; then
  if [[ -f /SOCIAL/configs/oceanicvibes/config.yaml ]]; then
    CONFIG="/SOCIAL/configs/oceanicvibes/config.yaml"
  else
    CONFIG="$ROOT_DIR/examples/oceanicvibes.config.yaml"
  fi
fi

if [[ -z "$ENV_FILE" ]]; then
  CONFIG_DIR="$(dirname -- "$CONFIG")"
  if [[ -f "$CONFIG_DIR/.env" ]]; then
    ENV_FILE="$CONFIG_DIR/.env"
  elif [[ -f "$ROOT_DIR/.env" ]]; then
    ENV_FILE="$ROOT_DIR/.env"
  fi
fi

mkdir -p "$WORKSPACE"
INTAKE_FILE="$WORKSPACE/intake-simulation.json"

if [[ -n "$PROMPT_FILE" ]]; then
  if [[ ! -f "$PROMPT_FILE" ]]; then
    printf '%s\n' "intake prompt file does not exist: $PROMPT_FILE" >&2
    exit 2
  fi
  PROMPT_TEXT="$(<"$PROMPT_FILE")"
fi
export INTAKE_PROMPT="$PROMPT_TEXT"

"$PYTHON" - "$SOURCE_INTAKE" "$INTAKE_FILE" <<'PY'
import json
import os
import sys
from pathlib import Path

source = Path(sys.argv[1])
output = Path(sys.argv[2])
intake = json.loads(source.read_text(encoding="utf-8"))
prompt = os.environ.get("INTAKE_PROMPT", "").strip()
if prompt:
    intake["design_request"] = prompt
    intake.setdefault("provenance", {})["intake_prompt"] = "scripts/generate-oceanicvibes-test.sh"
output.write_text(json.dumps(intake, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
PY

ARGS=(
  -m site_agent.main
  design-lab generate
  --config "$CONFIG"
  --intake "$INTAKE_FILE"
  --workspace "$WORKSPACE"
  --planner "$PLANNER"
  --no-serve
  --timeout "$TIMEOUT"
)
if [[ -n "$MODEL" ]]; then
  ARGS+=(--model "$MODEL")
fi
if [[ -n "$RUN_ID" ]]; then
  ARGS+=(--run-id "$RUN_ID")
fi
if [[ -n "$ENV_FILE" ]]; then
  ARGS+=(--env-file "$ENV_FILE")
fi
if [[ "${DESIGN_LAB_BROWSER:-1}" == "0" ]]; then
  ARGS+=(--no-browser)
fi

printf '%s\n' "Generating OceanicVibes test site"
printf '%s\n' "  planner:   $PLANNER"
printf '%s\n' "  model:     ${MODEL:-configured model}"
printf '%s\n' "  run id:    ${RUN_ID:-generated}"
printf '%s\n' "  config:    $CONFIG"
printf '%s\n' "  source:    $SOURCE_INTAKE"
printf '%s\n' "  intake:    $INTAKE_FILE"
printf '%s\n' "  workspace: $WORKSPACE"
"$PYTHON" "${ARGS[@]}"
