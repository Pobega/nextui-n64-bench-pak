#!/usr/bin/env python3
"""
Merge one or more N64Bench result folders (from tg5040, tg5050, h700) into:
  - <out>/index.html : self-contained interactive comparison dashboard
  - <out>/summary.md : GitHub-friendly Markdown comparison tables

Zero third-party dependencies (Python 3 standard library only).
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List


MAX_EMBEDDED_SAMPLES = 900


def load_frame_samples(csv_path: Path) -> List[List[Any]]:
    if not csv_path.is_file():
        return []
    rows: List[List[Any]] = []
    with csv_path.open("r", encoding="utf-8", errors="replace") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            try:
                rows.append([
                    int(row["vi_index"]),
                    round(float(row["frame_ms"]), 2),
                    int(row["was_new_frame"]),
                ])
            except (KeyError, ValueError):
                continue
    if len(rows) > MAX_EMBEDDED_SAMPLES:
        step = len(rows) / MAX_EMBEDDED_SAMPLES
        rows = [rows[int(i * step)] for i in range(MAX_EMBEDDED_SAMPLES)]
    return rows


def discover_summary_files(inputs: List[str]) -> List[Path]:
    found: List[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_file() and p.name.endswith(".json"):
            found.append(p)
        elif p.is_dir():
            direct = p / "summary.json"
            if direct.is_file():
                found.append(direct)
            else:
                for sub in sorted(p.rglob("summary.json")):
                    found.append(sub)
    return found


def load_all_runs(summary_files: List[Path]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for sfile in summary_files:
        try:
            data = json.loads(sfile.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Warning: skipping unreadable {sfile}: {exc}", file=sys.stderr)
            continue

        base_dir = sfile.parent
        meta = {
            "source_dir": base_dir.name,
            "schema_version": data.get("schema_version", 1),
            "timestamp_utc": data.get("timestamp_utc", ""),
            "platform": data.get("platform", "unknown"),
            "device": data.get("device", data.get("platform", "unknown")),
            "pak_version": data.get("pak_version", ""),
            "nextui_version": data.get("nextui_version", ""),
            "soc_model": data.get("soc_model", ""),
            "gl_renderer": data.get("gl_renderer", ""),
            "gl_version": data.get("gl_version", ""),
            "suite_scope": data.get("suite_scope", ""),
            "suite_target": data.get("suite_target", ""),
            "mode_selected": data.get("mode_selected", ""),
            "battery_start_pct": data.get("battery_start_pct", -1),
            "battery_end_pct": data.get("battery_end_pct", -1),
            "cpu_governor": data.get("cpu_governor", "unknown"),
            "cpu_max_khz": data.get("cpu_max_khz", 0),
            "kernel": data.get("kernel", ""),
        }

        for run in data.get("runs", []):
            rec = dict(meta)
            rec.update(run)
            rec["device_label"] = f"{rec['platform']} ({rec['device']})" if rec["device"] != rec["platform"] else rec["platform"]
            frames_rel = run.get("frames_csv", "")
            rec["samples"] = load_frame_samples(base_dir / frames_rel) if frames_rel else []
            records.append(rec)
    return records


def format_battery_delta(start_pct: Any, end_pct: Any) -> str:
    try:
        s_val = int(start_pct)
        e_val = int(end_pct)
    except (TypeError, ValueError):
        return "—"
    if s_val >= 0 and e_val >= 0:
        return f"{s_val}%→{e_val}%"
    if e_val >= 0:
        return f"{e_val}%"
    if s_val >= 0:
        return f"{s_val}%"
    return "—"


def generate_markdown(records: List[Dict[str, Any]]) -> str:
    lines: List[str] = [
        "# N64Bench Performance Report",
        "",
        f"Total benchmark runs loaded: **{len(records)}**",
        "",
    ]

    seen_sources: Dict[str, Dict[str, Any]] = {}
    for r in records:
        src = str(r.get("source_dir", ""))
        if src not in seen_sources:
            seen_sources[src] = r

    if seen_sources:
        lines.append("## Devices & Environment")
        lines.append("")
        lines.append("| Device | SoC | GL Renderer | CPU | Kernel | Pak / NextUI | Battery |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for r in seen_sources.values():
            khz = int(r.get("cpu_max_khz") or 0)
            cpu_str = f"{khz / 1000:.0f} MHz ({r.get('cpu_governor', 'unknown')})" if khz > 0 else str(r.get("cpu_governor", "unknown"))
            soc_str = str(r.get("soc_model") or "—")
            gl_str = str(r.get("gl_renderer") or "—")
            ver_parts = [p for p in [
                f"Pak {r['pak_version']}" if r.get("pak_version") and r.get("pak_version") != "unknown" else "",
                f"NextUI {r['nextui_version']}" if r.get("nextui_version") and r.get("nextui_version") != "unknown" else "",
            ] if p]
            ver_str = " / ".join(ver_parts) if ver_parts else "—"
            bat_str = format_battery_delta(r.get("battery_start_pct", -1), r.get("battery_end_pct", -1))
            lines.append(
                f"| {r['device_label']} | {soc_str} | {gl_str} | {cpu_str} | {r.get('kernel') or '—'} | {ver_str} | {bat_str} |"
            )
        lines.append("")

    scenarios = sorted({(r.get("scenario_id", ""), r.get("scenario_name", "")) for r in records})
    for sid, sname in scenarios:
        lines.append(f"## {sname or sid}")
        lines.append("")

        paced = [r for r in records if r.get("scenario_id") == sid and r.get("mode") == "paced"]
        if paced:
            lines.append("### Paced (Real Gameplay / VSync ON)")
            lines.append("")
            lines.append("| Device | Profile | VI FPS | 3D FPS | 1% Low | p99 (ms) | Missed VSync | Underruns | Temp (C) |")
            lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
            for r in sorted(paced, key=lambda x: (x["device_label"], -float(x.get("vi_fps_avg", 0)))):
                t0, t1 = r.get("soc_temp_start_c", -1), r.get("soc_temp_end_c", -1)
                temp_str = f"{t0:.0f}→{t1:.0f}" if t0 > 0 and t1 > 0 else "—"
                lines.append(
                    f"| {r['device_label']} | {r.get('profile_label', r.get('profile_id'))} "
                    f"| {r.get('vi_fps_avg', 0):.1f} | {r.get('rendered_fps_avg', 0):.1f} "
                    f"| {r.get('fps_1pct_low', 0):.1f} | {r.get('frame_ms_p99', 0):.1f} "
                    f"| {r.get('missed_vsyncs', 0)} | {r.get('audio_underruns', 0)} | {temp_str} |"
                )
            lines.append("")

        uncapped = [r for r in records if r.get("scenario_id") == sid and r.get("mode") == "uncapped"]
        if uncapped:
            lines.append("### Uncapped (Raw Headroom / VSync OFF)")
            lines.append("")
            lines.append("| Device | Profile | Max VI FPS | Speed % | Max 3D FPS | Avg (ms) | Temp (C) |")
            lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
            for r in sorted(uncapped, key=lambda x: (x["device_label"], -float(x.get("vi_fps_avg", 0)))):
                t0, t1 = r.get("soc_temp_start_c", -1), r.get("soc_temp_end_c", -1)
                temp_str = f"{t0:.0f}→{t1:.0f}" if t0 > 0 and t1 > 0 else "—"
                lines.append(
                    f"| {r['device_label']} | {r.get('profile_label', r.get('profile_id'))} "
                    f"| {r.get('vi_fps_avg', 0):.1f} | {r.get('speed_pct', 0):.0f}% "
                    f"| {r.get('rendered_fps_avg', 0):.1f} | {r.get('frame_ms_avg', 0):.2f} | {temp_str} |"
                )
            lines.append("")

    return "\n".join(lines)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>NextUI N64Bench Dashboard</title>
<style>
  :root {
    --bg: #0e1117; --card: #161b22; --border: #2b323c;
    --text: #e6edf3; --muted: #8b949e;
    --green: #3fb950; --blue: #58a6ff; --amber: #d29922; --red: #f85149; --purple: #bc8cff;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.45; }
  header { padding: 20px 28px; border-bottom: 1px solid var(--border); display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }
  header h1 { margin: 0; font-size: 1.35rem; }
  header .sub { color: var(--muted); font-size: 0.9rem; }
  main { max-width: 1280px; margin: 0 auto; padding: 20px 24px 48px; }
  .controls { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; align-items: center; }
  select, button { background: var(--card); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 7px 12px; font-size: 0.9rem; cursor: pointer; }
  button.active { border-color: var(--blue); color: var(--blue); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .card h2 { margin: 0 0 12px; font-size: 1rem; color: #f0f6fc; }
  .bar-row { display: grid; grid-template-columns: 230px 1fr 78px; align-items: center; gap: 10px; margin: 7px 0; font-size: 0.85rem; }
  .bar-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); }
  .bar-track { background: #21262d; border-radius: 4px; height: 18px; position: relative; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width 0.2s ease; }
  .bar-low { position: absolute; top: 0; bottom: 0; width: 3px; background: #ffffff; opacity: 0.85; }
  .bar-val { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th, td { padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; }
  th { color: var(--muted); font-weight: 600; cursor: pointer; user-select: none; }
  tr.clickable:hover { background: rgba(88, 166, 255, 0.08); cursor: pointer; }
  tr.selected { background: rgba(88, 166, 255, 0.16); }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .pill { display: inline-block; padding: 2px 7px; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
  .pill.rearmed { background: rgba(63,185,80,0.18); color: var(--green); }
  .pill.parallel { background: rgba(88,166,255,0.18); color: var(--blue); }
  .pill.uncapped { background: rgba(210,153,34,0.18); color: var(--amber); }
  .pill.paced { background: rgba(188,140,255,0.18); color: var(--purple); }
  canvas { width: 100%; height: 220px; display: block; background: #0b0e14; border-radius: 6px; border: 1px solid var(--border); }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 0.8rem; color: var(--muted); margin-top: 8px; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.78rem; color: var(--muted); }
  .env-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 18px; }
  .env-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; font-size: 0.82rem; }
  .env-card .env-title { font-weight: 600; color: #f0f6fc; margin-bottom: 6px; font-size: 0.9rem; }
  .env-card .env-row { color: var(--muted); display: flex; justify-content: space-between; gap: 8px; margin: 2px 0; }
  .env-card .env-val { color: var(--text); text-align: right; }
</style>
</head>
<body>
<header>
  <div>
    <h1>NextUI N64Bench Dashboard</h1>
    <div class="sub" id="meta-summary"></div>
  </div>
</header>
<main>
  <div class="env-grid" id="env-cards"></div>
  <div class="controls">
    <label>Scenario: <select id="sel-scenario"></select></label>
    <label>Device: <select id="sel-device"></select></label>
    <label>Mode:
      <button id="btn-paced" class="active">Paced (VSync ON)</button>
      <button id="btn-uncapped">Uncapped (Headroom)</button>
    </label>
  </div>

  <div class="grid">
    <div class="card">
      <h2 id="chart1-title">VI FPS (white tick = 1% low)</h2>
      <div id="chart-vi"></div>
    </div>
    <div class="card">
      <h2 id="chart2-title">Rendered 3D FPS / Headroom %</h2>
      <div id="chart-secondary"></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:20px;">
    <h2 id="spike-title">Frame-Time Timeline (click any table row below to inspect)</h2>
    <canvas id="spike-canvas" width="1100" height="220"></canvas>
    <div class="legend" id="spike-meta"></div>
  </div>

  <div class="card">
    <h2>Detailed Results</h2>
    <div style="overflow-x:auto;">
      <table id="results-table">
        <thead>
          <tr>
            <th>Device</th>
            <th>Scenario</th>
            <th>Profile</th>
            <th>Core</th>
            <th class="num">VI FPS</th>
            <th class="num">3D FPS</th>
            <th class="num">Speed %</th>
            <th class="num">1% Low</th>
            <th class="num">p99 ms</th>
            <th class="num">Miss</th>
            <th class="num">Underrun</th>
            <th class="num">Temp</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</main>
<script>
const DATA = __DATA_JSON__;

let currentMode = "paced";
let selectedRunKey = null;

const uniq = arr => [...new Set(arr)];
const escHtml = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;" }[c]));
const selScenario = document.getElementById("sel-scenario");
const selDevice = document.getElementById("sel-device");
const btnPaced = document.getElementById("btn-paced");
const btnUncapped = document.getElementById("btn-uncapped");

function fmtBattery(s, e) {
  if (s >= 0 && e >= 0) return `${s}% → ${e}%`;
  if (e >= 0) return `${e}%`;
  if (s >= 0) return `${s}%`;
  return "";
}

function renderEnvCards() {
  const bySource = new Map();
  DATA.forEach(r => { if (!bySource.has(r.source_dir)) bySource.set(r.source_dir, r); });
  const container = document.getElementById("env-cards");
  container.innerHTML = [...bySource.values()].map(r => {
    const cpu = r.cpu_max_khz > 0 ? `${(r.cpu_max_khz / 1000).toFixed(0)} MHz (${r.cpu_governor || "unknown"})` : (r.cpu_governor || "unknown");
    const bat = fmtBattery(r.battery_start_pct, r.battery_end_pct);
    const ver = [
      r.pak_version && r.pak_version !== "unknown" ? `Pak v${r.pak_version}` : "",
      r.nextui_version && r.nextui_version !== "unknown" ? `NextUI ${r.nextui_version}` : ""
    ].filter(Boolean).join(" · ");
    const rows = [
      r.soc_model && r.soc_model !== "unknown" ? ["SoC", r.soc_model] : null,
      r.gl_renderer && r.gl_renderer !== "unknown" ? ["GL Renderer", r.gl_renderer] : null,
      ["CPU", cpu],
      r.kernel ? ["Kernel", r.kernel] : null,
      ver ? ["Software", ver] : null,
      bat ? ["Battery", bat] : null
    ].filter(Boolean);
    return `<div class="env-card">
      <div class="env-title">${escHtml(r.device_label)} <span class="mono">(${escHtml(r.source_dir)})</span></div>
      ${rows.map(([k, v]) => `<div class="env-row"><span>${escHtml(k)}</span><span class="env-val">${escHtml(v)}</span></div>`).join("")}
    </div>`;
  }).join("");
}

function initFilters() {
  const devices = uniq(DATA.map(r => r.device_label)).sort();
  const scenarios = uniq(DATA.map(r => r.scenario_id)).sort();
  document.getElementById("meta-summary").textContent =
    `${DATA.length} runs across ${devices.length} device(s) and ${scenarios.length} scenario(s)`;
  renderEnvCards();

  selScenario.innerHTML = `<option value="ALL">All Scenarios</option>` +
    scenarios.map(id => {
      const name = (DATA.find(r => r.scenario_id === id) || {}).scenario_name || id;
      return `<option value="${id}">${name}</option>`;
    }).join("");
  if (scenarios.length > 0) selScenario.value = scenarios[0];

  selDevice.innerHTML = `<option value="ALL">All Devices</option>` +
    devices.map(d => `<option value="${d}">${d}</option>`).join("");

  selScenario.onchange = render;
  selDevice.onchange = render;
  btnPaced.onclick = () => { currentMode = "paced"; btnPaced.classList.add("active"); btnUncapped.classList.remove("active"); render(); };
  btnUncapped.onclick = () => { currentMode = "uncapped"; btnUncapped.classList.add("active"); btnPaced.classList.remove("active"); render(); };
}

function coreColor(core) {
  return (core || "").includes("rearmed") ? "var(--green)" : "var(--blue)";
}

function renderBars(el, rows, valueFn, maxVal, unit, lowFn) {
  if (!rows.length) { el.innerHTML = `<div class="sub">No runs match the selected filter.</div>`; return; }
  el.innerHTML = rows.map(r => {
    const v = valueFn(r);
    const pct = Math.min(100, Math.max(0, (v / maxVal) * 100));
    const lowHtml = lowFn ? `<div class="bar-low" style="left:${Math.min(100, (lowFn(r)/maxVal)*100).toFixed(1)}%" title="1% low: ${lowFn(r).toFixed(1)}"></div>` : "";
    const lbl = selDevice.value === "ALL" ? `[${r.platform}] ${r.profile_label}` : r.profile_label;
    return `<div class="bar-row">
      <div class="bar-label" title="${lbl}">${lbl}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct.toFixed(1)}%;background:${coreColor(r.core)}"></div>${lowHtml}</div>
      <div class="bar-val">${v.toFixed(1)}${unit}</div>
    </div>`;
  }).join("");
}

function drawSpikes(run) {
  const canvas = document.getElementById("spike-canvas");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!run || !run.samples || !run.samples.length) {
    ctx.fillStyle = "#8b949e";
    ctx.font = "14px sans-serif";
    ctx.fillText("Select a run with frame samples to inspect its frame-time timeline.", 18, H / 2);
    document.getElementById("spike-meta").textContent = "";
    return;
  }

  document.getElementById("spike-title").textContent =
    `Frame-Time Timeline: ${run.device_label} · ${run.scenario_id} · ${run.profile_label} (${run.mode.toUpperCase()})`;

  const samples = run.samples;
  const maxMs = Math.max(40, Math.min(100, Math.max(...samples.map(s => s[1])) * 1.1));
  const padL = 44, padR = 14, padT = 14, padB = 22;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  const yFor = ms => padT + plotH - (Math.min(ms, maxMs) / maxMs) * plotH;

  for (const ref of [16.67, 33.33, 50.0]) {
    if (ref > maxMs) continue;
    const y = yFor(ref);
    ctx.strokeStyle = ref < 20 ? "rgba(63,185,80,0.35)" : "rgba(248,81,73,0.3)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#8b949e";
    ctx.font = "11px monospace";
    ctx.fillText(`${ref.toFixed(0)}ms`, 4, y + 4);
  }

  ctx.beginPath();
  ctx.strokeStyle = run.mode === "uncapped" ? "#d29922" : "#58a6ff";
  ctx.lineWidth = 1.4;
  samples.forEach((s, i) => {
    const x = padL + (i / Math.max(1, samples.length - 1)) * plotW;
    const y = yFor(s[1]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  const romSha = run.rom_sha256 && run.rom_sha256 !== "unknown" ? `<span class="mono">ROM: ${escHtml(run.rom_sha256.slice(0, 12))}</span>` : "";
  const glInfo = run.gl_renderer && run.gl_renderer !== "unknown" ? `<span>GL: <b>${escHtml(run.gl_renderer)}</b></span>` : "";
  document.getElementById("spike-meta").innerHTML =
    `<span>Avg: <b>${run.frame_ms_avg.toFixed(2)}ms</b></span>` +
    `<span>p50: <b>${run.frame_ms_p50.toFixed(2)}ms</b></span>` +
    `<span>p95: <b>${run.frame_ms_p95.toFixed(2)}ms</b></span>` +
    `<span>p99: <b>${run.frame_ms_p99.toFixed(2)}ms</b></span>` +
    `<span>Max: <b>${run.frame_ms_max.toFixed(2)}ms</b></span>` +
    glInfo +
    `<span class="mono">Core: ${escHtml((run.core_sha256 || "").slice(0, 12))}</span>` +
    romSha;
}

function render() {
  const rows = DATA.filter(r =>
    r.mode === currentMode &&
    (selScenario.value === "ALL" || r.scenario_id === selScenario.value) &&
    (selDevice.value === "ALL" || r.device_label === selDevice.value)
  ).sort((a, b) => b.vi_fps_avg - a.vi_fps_avg);

  if (currentMode === "paced") {
    document.getElementById("chart1-title").textContent = "Paced VI FPS (target 60; white tick = 1% low)";
    document.getElementById("chart2-title").textContent = "Actual Rendered 3D FPS";
    renderBars(document.getElementById("chart-vi"), rows, r => r.vi_fps_avg, 65, " fps", r => r.fps_1pct_low);
    const max3d = Math.max(35, ...rows.map(r => r.rendered_fps_avg || 0));
    renderBars(document.getElementById("chart-secondary"), rows, r => r.rendered_fps_avg, max3d, " fps");
  } else {
    document.getElementById("chart1-title").textContent = "Uncapped Max VI FPS";
    document.getElementById("chart2-title").textContent = "Speed Headroom (% of 60 Hz)";
    const maxVi = Math.max(70, ...rows.map(r => r.vi_fps_avg || 0));
    const maxPct = Math.max(120, ...rows.map(r => r.speed_pct || 0));
    renderBars(document.getElementById("chart-vi"), rows, r => r.vi_fps_avg, maxVi, " fps");
    renderBars(document.getElementById("chart-secondary"), rows, r => r.speed_pct, maxPct, "%");
  }

  const tbody = document.querySelector("#results-table tbody");
  tbody.innerHTML = rows.map((r, idx) => {
    const key = `${r.source_dir}/${r.run_id}`;
    const isSel = selectedRunKey === key || (!selectedRunKey && idx === 0);
    if (isSel) selectedRunKey = key;
    const isRearmed = (r.core || "").includes("rearmed");
    const temp = (r.soc_temp_start_c > 0 && r.soc_temp_end_c > 0)
      ? `${r.soc_temp_start_c.toFixed(0)}→${r.soc_temp_end_c.toFixed(0)}°C` : "—";
    return `<tr class="clickable ${isSel ? "selected" : ""}" data-key="${key}">
      <td>${r.device_label}</td>
      <td>${r.scenario_id}</td>
      <td>${r.profile_label}</td>
      <td><span class="pill ${isRearmed ? "rearmed" : "parallel"}">${isRearmed ? "ReARMed" : "ParaLLEl"}</span></td>
      <td class="num">${r.vi_fps_avg.toFixed(1)}</td>
      <td class="num">${r.rendered_fps_avg.toFixed(1)}</td>
      <td class="num">${r.speed_pct.toFixed(0)}%</td>
      <td class="num">${r.fps_1pct_low.toFixed(1)}</td>
      <td class="num">${r.frame_ms_p99.toFixed(1)}</td>
      <td class="num">${r.missed_vsyncs}</td>
      <td class="num">${r.audio_underruns}</td>
      <td class="num">${temp}</td>
    </tr>`;
  }).join("");

  tbody.querySelectorAll("tr").forEach((tr, idx) => {
    tr.onclick = () => {
      selectedRunKey = tr.dataset.key;
      tbody.querySelectorAll("tr").forEach(x => x.classList.remove("selected"));
      tr.classList.add("selected");
      drawSpikes(rows[idx]);
    };
  });

  const activeRun = rows.find(r => `${r.source_dir}/${r.run_id}` === selectedRunKey) || rows[0];
  drawSpikes(activeRun);
}

initFilters();
render();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate HTML & Markdown benchmark comparison reports from N64Bench results.")
    ap.add_argument("inputs", nargs="+", help="Result directories or summary.json files")
    ap.add_argument("-o", "--out", default="report", help="Output directory (default: report/)")
    args = ap.parse_args()

    summary_files = discover_summary_files(args.inputs)
    if not summary_files:
        print("Error: no summary.json files found in inputs.", file=sys.stderr)
        return 1

    records = load_all_runs(summary_files)
    if not records:
        print("Error: no benchmark runs found in summary files.", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / "summary.md"
    md_path.write_text(generate_markdown(records), encoding="utf-8")

    html_path = out_dir / "index.html"
    html_content = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(records))
    html_path.write_text(html_content, encoding="utf-8")

    print(f"Merged {len(records)} runs from {len(summary_files)} result set(s):")
    print(f"  HTML dashboard : {html_path}")
    print(f"  Markdown table : {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
