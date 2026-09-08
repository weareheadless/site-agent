"""Read-only local comparison server for retained design-lab artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from ..application.design_lab import DesignLabError, DesignLabService
from ..application.model_comparison import ModelComparisonError, load_model_comparison


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_VARIANTS = {"baseline", "candidate"}
_ROOT_RELATIVE_ATTRIBUTE = re.compile(r"((?:href|src|action|poster|component-url|renderer-url)\s*=\s*[\"'])/(?!/)([^\"']*)", re.I)


def _safe_run_id(value: str) -> str:
    result = str(value or "").strip()
    if not _RUN_ID.fullmatch(result):
        raise HTTPException(status_code=400, detail="invalid design-lab run id")
    return result


def _safe_file(root: Path, relative: str) -> Path:
    value = str(relative or "").replace("\\", "/").lstrip("/")
    if not value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise HTTPException(status_code=400, detail="invalid artifact path")
    target = (root / value).resolve()
    if target == root or root not in target.parents or target.is_symlink() or not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return target


def _rewrite_artifact_html(content: str, run_id: str, variant: str) -> str:
    """Keep root-relative site assets and internal links inside the mounted artifact."""
    prefix = f"/artifacts/{run_id}/{variant}/"

    def rewrite(match: re.Match[str]) -> str:
        path = match.group(2) or "index.html"
        return f"{match.group(1)}{prefix}{path}"

    return _ROOT_RELATIVE_ATTRIBUTE.sub(rewrite, content)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="retained report not found") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=500, detail="retained report is invalid")
    return value


def _comparison_ui() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ada Design Lab</title>
  <style>
    :root { color-scheme: dark; font: 14px/1.45 system-ui, sans-serif; background: #0b1017; color: #e8eef5; }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; }
    header { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; padding: 16px 20px; border-bottom: 1px solid #293746; background: #111a24; }
    h1 { margin: 0; font: 600 20px/1.1 Georgia, serif; }
    .controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    label { color: #9aaaba; font-size: 12px; }
    select, button { border: 1px solid #3b4d5f; border-radius: 5px; padding: 7px 9px; color: #e8eef5; background: #0d1520; }
    button { cursor: pointer; }
    button[aria-pressed="true"] { border-color: #7ec8ff; color: #7ec8ff; }
    main { padding: 20px; }
    .meta { display: grid; gap: 6px; margin-bottom: 18px; color: #9aaaba; }
    .meta code { color: #b9e8de; overflow-wrap: anywhere; }
    .stage { display: flex; gap: 14px; align-items: flex-start; overflow: auto; }
    .frame { flex: 1 1 0; min-width: 320px; }
    .frame[hidden] { display: none; }
    .frame h2 { margin: 0 0 8px; font-size: 12px; letter-spacing: .1em; text-transform: uppercase; color: #9aaaba; }
    iframe { display: block; width: 100%; min-height: 650px; border: 1px solid #3b4d5f; border-radius: 5px; background: #fff; }
    .findings { margin-top: 20px; padding: 14px; border: 1px solid #293746; border-radius: 5px; background: #111a24; }
    .findings h2 { margin: 0 0 8px; font-size: 14px; }
    pre { margin: 0; max-height: 260px; overflow: auto; color: #b9e8de; white-space: pre-wrap; }
    @media (max-width: 700px) { main { padding: 12px; } .stage { display: block; } .frame { margin-bottom: 14px; } iframe { min-height: 580px; } }
  </style>
</head>
<body>
  <header>
    <h1>Ada Design Lab</h1>
    <div class="controls">
      <label for="page">Page</label><select id="page"></select>
      <label for="viewport">Viewport</label><select id="viewport">
        <option value="desktop">Desktop 1440</option><option value="tablet">Tablet 768</option><option value="mobile">Mobile 390</option>
      </select>
      <button type="button" data-mode="candidate" aria-pressed="true">Candidate</button>
      <button type="button" data-mode="baseline" aria-pressed="false">Baseline</button>
      <button type="button" data-mode="split" aria-pressed="false">Side by side</button>
    </div>
  </header>
  <main>
    <div class="meta" id="meta">Loading retained run...</div>
    <div class="stage">
      <section class="frame" id="baseline-frame" hidden><h2>Baseline</h2><iframe id="baseline" title="Baseline site"></iframe></section>
      <section class="frame" id="candidate-frame"><h2>Candidate</h2><iframe id="candidate" title="Candidate site"></iframe></section>
    </div>
    <section class="findings"><h2>Quality evidence</h2><pre id="findings"></pre></section>
  </main>
  <script>
    const runId = new URLSearchParams(location.search).get("run") || "";
    let data = null;
    let mode = "candidate";
    const page = document.querySelector("#page");
    const viewport = document.querySelector("#viewport");
    const baselineFrame = document.querySelector("#baseline-frame");
    const candidateFrame = document.querySelector("#candidate-frame");
    const baseline = document.querySelector("#baseline");
    const candidate = document.querySelector("#candidate");
    function render() {
      if (!data) return;
      const selected = data.pages.find((item) => item.path === page.value) || data.pages[0];
      const widths = { desktop: [1440, 1000], tablet: [768, 1024], mobile: [390, 844] };
      const [width, height] = widths[viewport.value] || widths.desktop;
      for (const frame of [baseline, candidate]) { frame.style.width = `${width}px`; frame.style.height = `${height}px`; }
      baselineFrame.hidden = !(mode === "baseline" || mode === "split");
      candidateFrame.hidden = mode === "baseline";
      baseline.src = selected && selected.baseline ? selected.baseline : "about:blank";
      candidate.src = selected && selected.candidate ? selected.candidate : "about:blank";
      for (const button of document.querySelectorAll("[data-mode]")) button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    }
    async function load() {
      if (!runId) { document.querySelector("#meta").textContent = "Missing ?run=..."; return; }
      const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
      if (!response.ok) { document.querySelector("#meta").textContent = "Retained run unavailable."; return; }
      data = await response.json();
      for (const item of data.pages) { const option = document.createElement("option"); option.value = item.path; option.textContent = item.path; page.append(option); }
      document.querySelector("#meta").innerHTML = `<span>Run <code>${data.run_id}</code></span><span>Baseline <code>${data.baseline_sha || "unavailable"}</code></span><span>Candidate <code>${data.candidate_sha || "unavailable"}</code></span>`;
      document.querySelector("#findings").textContent = JSON.stringify(data.quality || {}, null, 2);
      render();
    }
    page.addEventListener("change", render); viewport.addEventListener("change", render);
    for (const button of document.querySelectorAll("[data-mode]")) button.addEventListener("click", () => { mode = button.dataset.mode; render(); });
    load().catch(() => { document.querySelector("#meta").textContent = "Retained run could not be loaded."; });
  </script>
</body>
</html>"""


def _model_comparison_ui() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ada Model Comparison</title>
  <style>
    :root { color-scheme: dark; font: 14px/1.45 system-ui, sans-serif; background: #0b1017; color: #e8eef5; }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; }
    header { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; padding: 16px 20px; border-bottom: 1px solid #293746; background: #111a24; }
    h1 { margin: 0; font: 600 20px/1.1 Georgia, serif; }
    .controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    label { color: #9aaaba; font-size: 12px; }
    select { border: 1px solid #3b4d5f; border-radius: 5px; padding: 7px 9px; color: #e8eef5; background: #0d1520; }
    main { padding: 20px; }
    .meta { display: grid; gap: 6px; margin-bottom: 18px; color: #9aaaba; }
    .meta code, .model code { color: #b9e8de; overflow-wrap: anywhere; }
    .stage { display: grid; grid-template-columns: repeat(3, minmax(360px, 1fr)); gap: 14px; align-items: start; overflow-x: auto; }
    .model { min-width: 360px; }
    .model[hidden] { display: none; }
    .model h2 { margin: 0 0 3px; font-size: 13px; letter-spacing: .08em; text-transform: uppercase; color: #e8eef5; }
    .model p { margin: 0 0 8px; color: #9aaaba; font-size: 12px; }
    iframe { display: block; border: 1px solid #3b4d5f; border-radius: 5px; background: #fff; }
    .unavailable { min-height: 180px; padding: 16px; border: 1px dashed #7b4d5d; border-radius: 5px; color: #ffb2bf; background: #241923; }
    .findings { margin-top: 20px; padding: 14px; border: 1px solid #293746; border-radius: 5px; background: #111a24; }
    .findings h2 { margin: 0 0 8px; font-size: 14px; }
    pre { margin: 0; max-height: 260px; overflow: auto; color: #b9e8de; white-space: pre-wrap; }
    @media (max-width: 700px) { main { padding: 12px; } .stage { display: block; overflow: visible; } .model { min-width: 0; margin-bottom: 14px; } }
  </style>
</head>
<body>
  <header>
    <h1 id="title">Ada Model Comparison</h1>
    <div class="controls">
      <label for="page">Page</label><select id="page"></select>
      <label for="viewport">Viewport</label><select id="viewport">
        <option value="desktop">Desktop 1440</option><option value="tablet">Tablet 768</option><option value="mobile">Mobile 390</option>
      </select>
    </div>
  </header>
  <main>
    <div class="meta" id="meta">Loading retained model comparison...</div>
    <div class="stage" id="stage"></div>
    <section class="findings"><h2>Run summary</h2><pre id="summary"></pre></section>
  </main>
  <script>
    let data = null;
    const page = document.querySelector("#page");
    const viewport = document.querySelector("#viewport");
    const stage = document.querySelector("#stage");
    const frames = new Map();
    function render() {
      if (!data) return;
      const selected = page.value;
      const sizes = { desktop: [1440, 1000], tablet: [768, 1024], mobile: [390, 844] };
      const [width, height] = sizes[viewport.value] || sizes.desktop;
      for (const model of data.models) {
        const view = frames.get(model.id);
        if (!view) continue;
        view.iframe.style.width = `${width}px`;
        view.iframe.style.height = `${height}px`;
        const source = (model.candidates || {})[selected] || "";
        if (view.iframe.src !== `${location.origin}${source}` && source) view.iframe.src = source;
        if (!source) view.iframe.removeAttribute("src");
      }
    }
    function addModel(model) {
      const section = document.createElement("section");
      section.className = "model";
      const heading = document.createElement("h2");
      heading.textContent = model.label;
      section.append(heading);
      const detail = document.createElement("p");
      detail.textContent = `${model.model || "model not specified"} | ${model.status}`;
      section.append(detail);
      const iframe = document.createElement("iframe");
      iframe.title = `${model.label} candidate`;
      const pages = Object.keys(model.candidates || {});
      if (pages.length) {
        section.append(iframe);
      } else {
        const unavailable = document.createElement("div");
        unavailable.className = "unavailable";
        unavailable.textContent = model.error || "No retained candidate is available.";
        section.append(unavailable);
      }
      stage.append(section);
      frames.set(model.id, { iframe });
    }
    async function load() {
      const response = await fetch("/api/model-comparison");
      if (!response.ok) throw new Error("comparison unavailable");
      data = await response.json();
      document.querySelector("#title").textContent = `${data.subject} | Model Comparison`;
      document.querySelector("#meta").innerHTML = `<span>Comparison <code>${data.comparison_id}</code></span><span>${data.models.length} model candidates; each remains in its own retained workspace.</span>`;
      for (const item of data.pages) { const option = document.createElement("option"); option.value = item; option.textContent = item; page.append(option); }
      if (!data.pages.length) { const option = document.createElement("option"); option.textContent = "No retained candidate pages"; page.append(option); }
      for (const model of data.models) addModel(model);
      document.querySelector("#summary").textContent = JSON.stringify(data.models.map((model) => ({ id: model.id, model: model.model, status: model.status, ok: model.ok, candidate_sha: model.candidate_sha, error: model.error })), null, 2);
      render();
    }
    page.addEventListener("change", render); viewport.addEventListener("change", render);
    load().catch(() => { document.querySelector("#meta").textContent = "Retained model comparison could not be loaded."; });
  </script>
</body>
</html>"""


def create_app(workspace: str | Path, run_id: str | None = None) -> FastAPI:
    root = Path(workspace).expanduser().resolve()
    if root == Path(root.anchor):
        raise DesignLabError("design-lab server workspace is too broad")
    default_run = str(run_id or "").strip()
    app = FastAPI(title="Ada Design Lab", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index(run: str | None = Query(default=None)) -> HTMLResponse:
        selected = run or default_run
        if selected:
            _safe_run_id(selected)
        return HTMLResponse(_comparison_ui())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "read_only"}

    @app.get("/api/runs/{selected_run}")
    def get_run(selected_run: str) -> JSONResponse:
        selected_run = _safe_run_id(selected_run)
        try:
            run = DesignLabService.load_retained(root, selected_run)
        except DesignLabError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        comparison_path = root / "reports" / selected_run / "comparison.json"
        if comparison_path.is_file() and not comparison_path.is_symlink():
            comparison = _read_json(comparison_path)
        else:
            comparison = {}
        return JSONResponse({**run, **comparison, "quality": comparison.get("quality", run.get("quality", {}))})

    @app.get("/artifacts/{selected_run}/{variant}/{artifact_path:path}")
    def artifact(selected_run: str, variant: str, artifact_path: str) -> Response:
        selected_run = _safe_run_id(selected_run)
        if variant not in _VARIANTS:
            raise HTTPException(status_code=404, detail="unknown artifact variant")
        root_path = root / "artifacts" / selected_run / variant
        target = _safe_file(root_path, artifact_path)
        if target.suffix.lower() in {".html", ".htm"}:
            try:
                content = target.read_text(encoding="utf-8")
            except OSError as exc:
                raise HTTPException(status_code=404, detail="artifact not found") from exc
            return HTMLResponse(_rewrite_artifact_html(content, selected_run, variant))
        return FileResponse(target)

    @app.get("/screenshots/{selected_run}/{variant}/{screenshot_path:path}")
    def screenshot(selected_run: str, variant: str, screenshot_path: str) -> FileResponse:
        selected_run = _safe_run_id(selected_run)
        if variant not in _VARIANTS:
            raise HTTPException(status_code=404, detail="unknown screenshot variant")
        root_path = root / "screenshots" / selected_run / variant
        return FileResponse(_safe_file(root_path, screenshot_path))

    return app


def create_model_comparison_app(manifest_path: str | Path) -> FastAPI:
    """Create a read-only app for a manifest of isolated model candidates."""
    manifest = Path(manifest_path).expanduser().resolve(strict=False)
    app = FastAPI(title="Ada Model Comparison", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(_model_comparison_ui())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "read_only"}

    @app.get("/api/model-comparison")
    def get_model_comparison() -> JSONResponse:
        try:
            comparison = load_model_comparison(manifest)
        except ModelComparisonError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(comparison.to_dict())

    @app.get("/model-artifacts/{model_id}/{selected_run}/{variant}/{artifact_path:path}")
    def model_artifact(model_id: str, selected_run: str, variant: str, artifact_path: str) -> Response:
        try:
            comparison = load_model_comparison(manifest)
            target = comparison.artifact_path(model_id, selected_run, variant, artifact_path)
        except ModelComparisonError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if target.suffix.lower() in {".html", ".htm"}:
            try:
                content = target.read_text(encoding="utf-8")
            except OSError as exc:
                raise HTTPException(status_code=404, detail="artifact not found") from exc
            prefix = f"/model-artifacts/{model_id}/{selected_run}/{variant}/"
            return HTMLResponse(_ROOT_RELATIVE_ATTRIBUTE.sub(lambda match: f"{match.group(1)}{prefix}{match.group(2) or 'index.html'}", content))
        return FileResponse(target)

    return app


def serve_design_lab(workspace: str | Path, run_id: str, *, host: str = "127.0.0.1", port: int = 0) -> tuple[str, Any]:
    """Run the read-only comparison app; returns only after the server stops."""
    import uvicorn

    app = create_app(workspace, run_id)
    if not port:
        port = 8765
    url = f"http://{host}:{int(port)}/?run={run_id}"
    uvicorn.run(app, host=host, port=int(port), log_level="warning")
    return url, app


def serve_model_comparison(manifest_path: str | Path, *, host: str = "127.0.0.1", port: int = 0) -> tuple[str, Any]:
    """Run the read-only model comparison app until the server stops."""
    import uvicorn

    app = create_model_comparison_app(manifest_path)
    if not port:
        port = 8765
    url = f"http://{host}:{int(port)}/"
    uvicorn.run(app, host=host, port=int(port), log_level="warning")
    return url, app


__all__ = ["create_app", "create_model_comparison_app", "serve_design_lab", "serve_model_comparison"]
