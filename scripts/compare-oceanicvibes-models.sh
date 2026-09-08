#!/usr/bin/env bash
set -uo pipefail

# Run the same owner request through three configured LLM model IDs. Each model
# gets its own disposable design-lab workspace; failures are retained in the
# manifest without preventing the other candidates from being generated.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON_FALLBACK:-python3}"
fi

MODEL_ROOT="${1:-${DESIGN_LAB_MATRIX_WORKSPACE:-/tmp/site-agent-design-lab/oceanicvibes-three-models}}"
GENERATOR="$ROOT_DIR/scripts/generate-oceanicvibes-test.sh"
STAMP="${MODEL_COMPARISON_RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
BROWSER="${DESIGN_LAB_BROWSER:-1}"
PLANNER="${DESIGN_LAB_PLANNER:-llm}"

GEMINI_MODEL="${GEMINI_MODEL:-google/gemini-2.5-pro}"
GPT_LUNA_MODEL="${GPT_LUNA_MODEL:-openai/gpt-5.6-luna}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek/deepseek-v4-flash-0731}"

MODEL_IDS=(gemini gpt-5-6-luna deepseek)
MODEL_LABELS=("Gemini" "GPT-5.6 Luna" "DeepSeek V4 0731")
MODEL_VALUES=("$GEMINI_MODEL" "$GPT_LUNA_MODEL" "$DEEPSEEK_MODEL")

mkdir -p "$MODEL_ROOT"
overall_status=0
for index in "${!MODEL_IDS[@]}"; do
  model_id="${MODEL_IDS[$index]}"
  model_label="${MODEL_LABELS[$index]}"
  model_value="${MODEL_VALUES[$index]}"
  workspace="$MODEL_ROOT/$model_id"
  run_id="${model_id}-${STAMP}"
  mkdir -p "$workspace"
  printf '%s\n' "$run_id" > "$workspace/model-run-id"
  printf '%s\n' "Generating $model_label ($model_value)"
  if DESIGN_LAB_MODEL="$model_value" \
    DESIGN_LAB_RUN_ID="$run_id" \
    DESIGN_LAB_WORKSPACE="$workspace" \
    DESIGN_LAB_PLANNER="$PLANNER" \
    DESIGN_LAB_BROWSER="$BROWSER" \
    "$GENERATOR" "$workspace" 2>&1 | tee "$workspace/generator.log"; then
    generator_status=0
  else
    generator_status=$?
    overall_status=1
    printf '%s\n' "Model run failed; retained evidence is in $workspace"
  fi
  printf '%s\n' "$generator_status" > "$workspace/generator.exit"
done

"$PYTHON" - "$MODEL_ROOT" "$STAMP" "${MODEL_IDS[@]}" "${MODEL_LABELS[@]}" "${MODEL_VALUES[@]}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser().resolve()
stamp = sys.argv[2]
ids = sys.argv[3:6]
labels = sys.argv[6:9]
models = sys.argv[9:12]
entries = []
for model_id, label, model in zip(ids, labels, models):
    workspace = (root / model_id).resolve()
    run_id_path = workspace / "model-run-id"
    run_id = run_id_path.read_text(encoding="utf-8").strip() if run_id_path.is_file() else ""
    run_path = workspace / "reports" / run_id / "run.json" if run_id else None
    run = {}
    if run_path is not None and run_path.is_file() and not run_path.is_symlink():
        try:
            value = json.loads(run_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("run_id") == run_id:
                run = value
        except (OSError, json.JSONDecodeError):
            pass
    exit_path = workspace / "generator.exit"
    try:
        exit_code = int(exit_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        exit_code = 1
    status = "passed" if run.get("ok") else ("failed" if run else "not_started")
    entries.append({
        "id": model_id,
        "label": label,
        "model": model,
        "workspace": str(workspace),
        "run_id": run_id,
        "status": status,
        "error": str(run.get("error") or "") if run else f"generator exit code {exit_code}",
        "generator_exit_code": exit_code,
    })
manifest = {
    "schema_version": 1,
    "comparison_id": f"oceanicvibes-{stamp}",
    "subject": "OceanicVibes",
    "models": entries,
}
path = root / "model-comparison.json"
path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"Model comparison manifest: {path}")
PY

printf '%s\n' "Comparison complete: $MODEL_ROOT/model-comparison.json"
printf '%s\n' "Serve it with: scripts/launch-oceanicvibes-model-comparison.sh $MODEL_ROOT"
exit "$overall_status"
