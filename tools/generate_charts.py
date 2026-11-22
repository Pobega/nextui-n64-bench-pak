#!/usr/bin/env python3
"""Generate high-DPI comparison charts for 1 to N NextUI N64Bench result sets."""

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from PIL import Image, ImageDraw, ImageFont

SCALE = 2

BG_PAGE = "#0d1117"
BG_CARD = "#161b22"
BORDER = "#30363d"
GRID_LINE = "#21262d"
REF_LINE = "#6e7681"
TEXT_MAIN = "#e6edf3"
TEXT_MUTED = "#8b949e"
TEXT_DIM = "#6e7681"

DEVICE_PALETTE = [
    "#38bdf8",
    "#fb923c",
    "#a78bfa",
    "#2dd4bf",
    "#f472b6",
    "#facc15",
    "#60a5fa",
    "#34d399",
]
COLOR_WARN = "#f85149"

FONT_SANS_BOLD = "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Bold.otf"
FONT_SANS_EXTRABOLD = "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-ExtraBold.otf"
FONT_SANS_REG = "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Regular.otf"
FONT_MONO_BOLD = "/usr/share/fonts/adobe-source-code-pro-fonts/SourceCodePro-Bold.otf"
FONT_MONO_REG = "/usr/share/fonts/adobe-source-code-pro-fonts/SourceCodePro-Regular.otf"

KNOWN_DEVICE_LABELS: Dict[str, Tuple[str, str]] = {
    "rgsp": ("Anbernic H700", "Mali-G31"),
    "rg35xxsp": ("Anbernic H700", "Mali-G31"),
    "brick": ("TrimUI Brick", "PowerVR"),
    "tg5040": ("TrimUI tg5040", "PowerVR"),
    "tg5050": ("TrimUI tg5050", "Mali"),
}

CORE_PROFILES = [
    ("ReARMed · Rice", "rearmed-rice-240p", "rearmed-rice-480p"),
    ("ParaLLEl · Glide64", "parallel-glide64-240p", "parallel-glide64-480p"),
    ("ReARMed · gles2n64", "rearmed-gles2n64-240p", "rearmed-gles2n64-480p"),
    ("ParaLLEl · Rice", "parallel-rice-240p", "parallel-rice-480p"),
    ("ReARMed · Glide64", "rearmed-glide64-240p", "rearmed-glide64-480p"),
]

MAX_HEATMAP_COLS = 7
HEATMAP_HDR_H = 42
HEATMAP_STRIP_HDR_H = 36
HEATMAP_ROW_H = 46
HEATMAP_STRIP_GAP = 6
HEATMAP_CARD_PAD_BOTTOM = 12
HEATMAP_CARD_GAP = 18

GAME_SPECS: List[Tuple[Tuple[str, ...], str, str, str]] = [
    (("conker-demo",), "Conker", "Conker's Bad Fur Day", "30 FPS"),
    (("goldeneye-demo", "goldeneye-dam"), "GoldenEye 007", "GoldenEye 007", "30 FPS"),
    (("sm64-demo", "sm64-bobomb"), "Super Mario 64", "Super Mario 64", "30 FPS"),
    (("fzerox-demo", "fzerox-race"), "F-Zero X", "F-Zero X", "60 FPS"),
    (("oot-demo", "oot-hyrule"), "Ocarina of Time", "Ocarina of Time", "20 FPS"),
    (("mk64-demo", "mk64-race"), "Mario Kart 64", "Mario Kart 64", "30 FPS"),
]


def load_font(path: str, size: float) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, int(size * SCALE))
    except OSError:
        return ImageFont.load_default()


def s(val: float) -> int:
    return int(round(val * SCALE))


def new_canvas(width: int, height: int) -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (s(width), s(height)), BG_PAGE)
    draw = ImageDraw.Draw(img)
    return img, draw


def finish_canvas(img: Image.Image, out_path: Path) -> None:
    final = img.resize((img.width // SCALE, img.height // SCALE), Image.LANCZOS)
    final.save(out_path, "PNG", optimize=True)


def draw_dashed_vline(
    draw: ImageDraw.ImageDraw,
    x: int,
    y0: int,
    y1: int,
    color: str,
    dash: float = 6,
    gap: float = 5,
    width: float = 2,
) -> None:
    y = y0
    while y < y1:
        y_end = min(y + s(dash), y1)
        draw.line([(x, y), (x, y_end)], fill=color, width=s(width))
        y += s(dash + gap)


def draw_header(draw: ImageDraw.ImageDraw, width: int, title: str, subtitle: str) -> None:
    f_title = load_font(FONT_SANS_EXTRABOLD, 22)
    f_sub = load_font(FONT_SANS_REG, 13)
    draw.text((s(32), s(22)), title, font=f_title, fill=TEXT_MAIN)
    draw.text((s(32), s(52)), subtitle, font=f_sub, fill=TEXT_MUTED)
    draw.line([(s(32), s(78)), (s(width - 32), s(78))], fill=BORDER, width=s(1))


def draw_legend(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    max_width: int,
    items: Sequence[Tuple[str, str]],
) -> int:
    f_leg = load_font(FONT_SANS_BOLD, 12)
    cx = s(x)
    cy = s(y)
    line_h = s(22)
    rows = 1
    right_limit = s(max_width - 32)
    for color, label in items:
        tb = draw.textbbox((0, 0), label, font=f_leg)
        item_w = s(20) + (tb[2] - tb[0]) + s(22)
        if cx > s(x) and cx + item_w > right_limit:
            cx = s(x)
            cy += line_h
            rows += 1
        draw.rounded_rectangle([cx, cy + s(2), cx + s(14), cy + s(14)], radius=s(3), fill=color)
        cx += s(20)
        draw.text((cx, cy), label, font=f_leg, fill=TEXT_MAIN)
        cx += (tb[2] - tb[0]) + s(22)
    return rows * 22


def shorten_gl_renderer(raw: str) -> str:
    txt = (raw or "").strip()
    if not txt or txt.lower() == "unknown":
        return ""
    m_mali = re.search(r"(Mali-[A-Za-z0-9]+)", txt)
    if m_mali:
        return m_mali.group(1)
    m_pvr = re.search(r"(PowerVR\s+[A-Za-z0-9]+)", txt)
    if m_pvr:
        return m_pvr.group(1)
    txt = re.sub(r"^OpenGL\s+ES\s+", "", txt, flags=re.IGNORECASE)
    return txt[:24]


def build_device_label(data: Dict[str, Any], idx: int, custom_labels: Optional[List[str]]) -> str:
    if custom_labels and idx < len(custom_labels):
        return custom_labels[idx]
    device = str(data.get("device") or data.get("platform") or f"Device {idx + 1}")
    platform = str(data.get("platform") or "")
    gl_raw = str(data.get("gl_renderer") or "")
    khz = int(data.get("cpu_max_khz") or 0)

    known = KNOWN_DEVICE_LABELS.get(device) or KNOWN_DEVICE_LABELS.get(platform)
    base_name = known[0] if known else (f"{device} ({platform})" if platform and platform != device else device)

    gpu = shorten_gl_renderer(gl_raw)
    if not gpu and known:
        gpu = known[1]

    details = [p for p in [gpu, f"@ {khz / 1_000_000:.2f} GHz" if khz > 0 else ""] if p]
    if details:
        return f"{base_name} ({' '.join(details)})"
    return base_name


def avg_metric(runs: List[Dict[str, Any]], pid: str, mode: str, field: str) -> float:
    vals = [float(r[field]) for r in runs if r.get("profile_id") == pid and r.get("mode") == mode and field in r]
    return sum(vals) / len(vals) if vals else 0.0


def sum_metric(runs: List[Dict[str, Any]], pid: str, mode: str, field: str) -> float:
    vals = [float(r[field]) for r in runs if r.get("profile_id") == pid and r.get("mode") == mode and field in r]
    return sum(vals)


def get_run(runs: List[Dict[str, Any]], sid: str, pid: str, mode: str) -> Optional[Dict[str, Any]]:
    for r in runs:
        if r.get("scenario_id") == sid and r.get("profile_id") == pid and r.get("mode") == mode:
            return r
    return None


def get_game_run(
    runs: List[Dict[str, Any]],
    sid_candidates: Sequence[str],
    pid: str,
    mode: str,
) -> Optional[Dict[str, Any]]:
    for sid in sid_candidates:
        found = get_run(runs, sid, pid, mode)
        if found is not None:
            return found
    return None


def compute_axis_scale(
    values_matrix: Sequence[Sequence[float]],
    default_max: float,
    step: int,
) -> Tuple[float, List[int]]:
    peak = max((v for row in values_matrix for v in row), default=0.0)
    x_max = max(default_max, float(math.ceil((peak * 1.15) / step) * step))
    ticks = list(range(0, int(x_max) + 1, step))
    if len(ticks) > 7:
        stride = max(2, len(ticks) // 5)
        ticks = ticks[::stride]
    return x_max, ticks


def draw_grouped_barh_panel(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    w: int,
    h: int,
    panel_title: str,
    panel_subtitle: str,
    labels: Sequence[str],
    series_vals: Sequence[Sequence[float]],
    series_colors: Sequence[str],
    x_max: float,
    ticks: Sequence[int],
    val_fmt: Callable[[float], str],
    ref_x: Optional[float] = None,
    ref_label: Optional[str] = None,
    warn_thresh: Optional[float] = None,
    lower_is_better: bool = False,
    annotations: Optional[Dict[Tuple[int, int], str]] = None,
) -> None:
    draw.rounded_rectangle(
        [s(x0), s(y0), s(x0 + w), s(y0 + h)],
        radius=s(10),
        fill=BG_CARD,
        outline=BORDER,
        width=s(1),
    )

    f_ptitle = load_font(FONT_SANS_BOLD, 15)
    f_psub = load_font(FONT_SANS_REG, 11.5)
    f_label = load_font(FONT_SANS_BOLD, 12.5)
    f_tick = load_font(FONT_MONO_REG, 10.5)
    f_val = load_font(FONT_MONO_BOLD, 11 if len(series_vals) <= 2 else 9.5)
    f_ref = load_font(FONT_SANS_BOLD, 10)

    draw.text((s(x0 + 18), s(y0 + 14)), panel_title, font=f_ptitle, fill=TEXT_MAIN)
    draw.text((s(x0 + 18), s(y0 + 36)), panel_subtitle, font=f_psub, fill=TEXT_MUTED)

    label_col_w = 148
    right_pad = 92
    plot_x0 = x0 + 18 + label_col_w
    plot_x1 = x0 + w - right_pad
    plot_y0 = y0 + 78
    plot_y1 = y0 + h - 34
    plot_w = plot_x1 - plot_x0

    def map_x(v: float) -> int:
        clamped = max(0.0, min(float(v), float(x_max)))
        return s(plot_x0 + (clamped / x_max) * plot_w)

    for t in ticks:
        tx = map_x(t)
        draw.line([(tx, s(plot_y0)), (tx, s(plot_y1))], fill=GRID_LINE, width=s(1))
        t_str = val_fmt(t)
        tb = draw.textbbox((0, 0), t_str, font=f_tick)
        tw = tb[2] - tb[0]
        draw.text((tx - tw // 2, s(plot_y1 + 7)), t_str, font=f_tick, fill=TEXT_DIM)

    if ref_x is not None and ref_x <= x_max:
        rx = map_x(ref_x)
        draw_dashed_vline(draw, rx, s(plot_y0 - 4), s(plot_y1), REF_LINE, dash=5, gap=4, width=1.5)
        if ref_label:
            rb = draw.textbbox((0, 0), ref_label, font=f_ref)
            rw = rb[2] - rb[0]
            draw.text((rx - rw // 2, s(plot_y0 - 18)), ref_label, font=f_ref, fill=TEXT_MUTED)

    n_rows = len(labels)
    n_dev = max(1, len(series_vals))
    row_h = (plot_y1 - plot_y0) / n_rows
    bar_gap = 3 if n_dev >= 3 else 4
    bar_h = max(6.0, min(18.0, (row_h - 12.0 - (n_dev - 1) * bar_gap) / n_dev))
    group_h = n_dev * bar_h + (n_dev - 1) * bar_gap

    best_per_dev = [
        (min(vals) if lower_is_better else max(vals)) if vals else 0.0
        for vals in series_vals
    ]

    for i, lbl in enumerate(labels):
        cy = plot_y0 + (i + 0.5) * row_h
        if i > 0:
            sep_y = s(plot_y0 + i * row_h)
            draw.line([(s(x0 + 18), sep_y), (s(plot_x1 + right_pad - 18), sep_y)], fill=GRID_LINE, width=s(1))

        lb = draw.textbbox((0, 0), lbl, font=f_label)
        lh = lb[3] - lb[1]
        draw.text((s(x0 + 18), s(cy) - lh // 2), lbl, font=f_label, fill=TEXT_MAIN)

        group_y0 = cy - group_h / 2.0
        for d_idx, vals in enumerate(series_vals):
            v = vals[i]
            color = series_colors[d_idx]
            is_warn = False
            if warn_thresh is not None:
                if (lower_is_better and v >= warn_thresh) or (not lower_is_better and v <= warn_thresh):
                    color = COLOR_WARN
                    is_warn = True

            by0 = group_y0 + d_idx * (bar_h + bar_gap)
            by1 = by0 + bar_h
            bx1 = max(s(plot_x0 + 3), map_x(v))
            draw.rounded_rectangle([s(plot_x0), s(by0), bx1, s(by1)], radius=s(3), fill=color)

            txt = val_fmt(v)
            if annotations and (d_idx, i) in annotations:
                txt += f" {annotations[(d_idx, i)]}"
            elif v == best_per_dev[d_idx] and v > 0:
                txt += " *"
            txt_col = TEXT_MAIN if (v == best_per_dev[d_idx] or is_warn) else TEXT_MUTED
            tb = draw.textbbox((0, 0), txt, font=f_val)
            tx = bx1 + s(7)
            ty = s((by0 + by1) / 2) - (tb[3] - tb[1]) // 2
            draw.rectangle([tx - s(2), ty - s(1), tx + (tb[2] - tb[0]) + s(2), ty + (tb[3] - tb[1]) + s(2)], fill=BG_CARD)
            draw.text((tx, ty), txt, font=f_val, fill=txt_col)

    draw.line([(s(plot_x0), s(plot_y0)), (s(plot_x0), s(plot_y1))], fill=BORDER, width=s(1))


def chart_overview_speed(devices: List[Dict[str, Any]], out_path: Path) -> None:
    width = 1180
    n_dev = len(devices)
    row_h = max(46, 20 + n_dev * 16)
    panel_h = 78 + 34 + row_h * len(CORE_PROFILES)

    img_tmp, draw_tmp = new_canvas(width, 200)
    legend_items = [(d["color"], d["label"]) for d in devices]
    leg_h = draw_legend(draw_tmp, 32, 92, width, legend_items)
    panel_y0 = 92 + leg_h + 10
    height = panel_y0 + panel_h + 24

    img, draw = new_canvas(width, height)
    n_games = len({r.get("scenario_id") for d in devices for r in d["runs"]})
    title_prefix = f"{n_games}-Game " if n_games else ""
    draw_header(
        draw,
        width,
        f"{title_prefix}Average Uncapped Speed Headroom",
        "VSync OFF (higher is better; 100% = full 60 VI/s N64 speed). Asterisk (*) marks each device's leader.",
    )
    draw_legend(draw, 32, 92, width, legend_items)

    labels = [p[0] for p in CORE_PROFILES]
    vals_240 = [[avg_metric(d["runs"], p[1], "uncapped", "speed_pct") for p in CORE_PROFILES] for d in devices]
    vals_480 = [[avg_metric(d["runs"], p[2], "uncapped", "speed_pct") for p in CORE_PROFILES] for d in devices]
    colors = [d["color"] for d in devices]
    x_max, ticks = compute_axis_scale(vals_240 + vals_480, 240.0, 50)

    panel_w = 548
    draw_grouped_barh_panel(
        draw,
        32,
        panel_y0,
        panel_w,
        panel_h,
        "320×240 Native Resolution",
        "All-scenario mean speed headroom across cores and renderers",
        labels,
        vals_240,
        colors,
        x_max,
        ticks,
        lambda v: f"{v:.0f}%" if isinstance(v, int) else f"{v:.1f}%",
        ref_x=100,
        ref_label="100% Full",
    )
    draw_grouped_barh_panel(
        draw,
        600,
        panel_y0,
        panel_w,
        panel_h,
        "640×480 2× Upscaled Resolution",
        "Resolution scaling headroom across cores and renderers",
        labels,
        vals_480,
        colors,
        x_max,
        ticks,
        lambda v: f"{v:.0f}%" if isinstance(v, int) else f"{v:.1f}%",
        ref_x=100,
        ref_label="100% Full",
    )
    finish_canvas(img, out_path)


def chart_overview_pacing(devices: List[Dict[str, Any]], out_path: Path) -> None:
    width = 1180
    n_dev = len(devices)
    row_h = max(46, 20 + n_dev * 16)
    panel_h = 78 + 34 + row_h * len(CORE_PROFILES)

    img_tmp, draw_tmp = new_canvas(width, 200)
    legend_items = [(d["color"], d["short_label"]) for d in devices] + [
        (COLOR_WARN, "GPU Driver Stutter Outlier (>500 missed)")
    ]
    leg_h = draw_legend(draw_tmp, 32, 92, width, legend_items)
    panel_y0 = 92 + leg_h + 10
    height = panel_y0 + panel_h + 24

    img, draw = new_canvas(width, height)
    draw_header(
        draw,
        width,
        "Real-Gameplay Frame Pacing & Smoothness",
        "VSync ON (paced gameplay). Red bars highlight GPU driver stutter outliers (>500 missed VSyncs).",
    )
    draw_legend(draw, 32, 92, width, legend_items)

    labels = [p[0] for p in CORE_PROFILES]
    miss_240 = [[sum_metric(d["runs"], p[1], "paced", "missed_vsyncs") for p in CORE_PROFILES] for d in devices]
    low1_480 = [[avg_metric(d["runs"], p[2], "paced", "fps_1pct_low") for p in CORE_PROFILES] for d in devices]
    colors = [d["color"] for d in devices]

    miss_max, miss_ticks = compute_axis_scale(miss_240, 800.0, 200)
    low_max, low_ticks = compute_axis_scale(low1_480, 40.0, 10)

    panel_w = 548
    draw_grouped_barh_panel(
        draw,
        32,
        panel_y0,
        panel_w,
        panel_h,
        "Total Missed VSyncs @ 320×240 (All-Game Sum)",
        "Lower is better · Measures frame pacing stability at native resolution",
        labels,
        miss_240,
        colors,
        miss_max,
        miss_ticks,
        lambda v: f"{int(round(v))}",
        warn_thresh=500,
        lower_is_better=True,
    )
    draw_grouped_barh_panel(
        draw,
        600,
        panel_y0,
        panel_w,
        panel_h,
        "Average 1% Low FPS @ 640×480",
        "Higher is better · Measures worst frame-time stutters at 2× resolution",
        labels,
        low1_480,
        colors,
        low_max,
        low_ticks,
        lambda v: f"{v:.0f}" if isinstance(v, int) else f"{v:.1f}",
        lower_is_better=False,
    )
    finish_canvas(img, out_path)


def heat_color(pct: float) -> Tuple[str, str]:
    if pct < 100:
        return "#5a1e24", "#ffa198"
    if pct < 130:
        return "#4c3614", "#f0b756"
    if pct < 175:
        return "#143d4d", "#79c0ff"
    if pct < 220:
        return "#144234", "#56d364"
    return "#0f533a", "#7ee787"


def resolve_active_games(
    devices: List[Dict[str, Any]],
) -> List[Tuple[Tuple[str, ...], str, str, str]]:
    seen_sids: set = set()
    fps_by_sid: Dict[str, Any] = {}
    for d in devices:
        for r in d.get("runs", []):
            sid = str(r.get("scenario_id") or "")
            if sid:
                seen_sids.add(sid)
                if sid not in fps_by_sid and r.get("target_game_fps") is not None:
                    fps_by_sid[sid] = r.get("target_game_fps")

    active: List[Tuple[Tuple[str, ...], str, str, str]] = []
    covered: set = set()
    for spec in GAME_SPECS:
        if any(sid in seen_sids for sid in spec[0]):
            active.append(spec)
            covered.update(spec[0])

    for sid in sorted(seen_sids - covered):
        fps_val = fps_by_sid.get(sid, 30)
        fps_label = f"{int(fps_val)} FPS" if isinstance(fps_val, (int, float)) else "30 FPS"
        active.append(((sid,), sid[:15], sid, fps_label))

    return active or list(GAME_SPECS)


def compute_heatmap_block_height(num_games: int) -> int:
    strips = max(1, math.ceil(num_games / MAX_HEATMAP_COLS))
    strip_h = HEATMAP_STRIP_HDR_H + HEATMAP_ROW_H * len(CORE_PROFILES)
    return HEATMAP_HDR_H + strips * strip_h + max(0, strips - 1) * HEATMAP_STRIP_GAP + HEATMAP_CARD_PAD_BOTTOM


def draw_heatmap_block(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    w: int,
    title: str,
    accent_color: str,
    runs: List[Dict[str, Any]],
    active_games: Sequence[Tuple[Tuple[str, ...], str, str, str]],
) -> int:
    block_h = compute_heatmap_block_height(len(active_games))

    draw.rounded_rectangle(
        [s(x0), s(y0), s(x0 + w), s(y0 + block_h)],
        radius=s(10),
        fill=BG_CARD,
        outline=BORDER,
        width=s(1),
    )
    draw.rounded_rectangle(
        [s(x0 + 16), s(y0 + 14), s(x0 + 22), s(y0 + 34)],
        radius=s(3),
        fill=accent_color,
    )
    f_btitle = load_font(FONT_SANS_BOLD, 15)
    f_col_sub = load_font(FONT_SANS_REG, 10)
    f_row = load_font(FONT_SANS_BOLD, 12.5)
    f_big = load_font(FONT_MONO_BOLD, 14)
    f_small = load_font(FONT_MONO_REG, 10.5)

    draw.text((s(x0 + 32), s(y0 + 13)), title, font=f_btitle, fill=TEXT_MAIN)

    strips = [
        active_games[i:i + MAX_HEATMAP_COLS]
        for i in range(0, len(active_games), MAX_HEATMAP_COLS)
    ]
    cols_for_width = len(strips[0]) if len(strips) == 1 else MAX_HEATMAP_COLS
    f_col = load_font(FONT_SANS_BOLD, 11 if cols_for_width > 5 else 12)

    label_w = 178
    gap = 8
    cell_w = (w - 32 - label_w - gap * (cols_for_width - 1)) / cols_for_width
    grid_x0 = x0 + 16 + label_w
    strip_h = HEATMAP_STRIP_HDR_H + HEATMAP_ROW_H * len(CORE_PROFILES)

    for s_idx, strip_games in enumerate(strips):
        strip_y0 = y0 + HEATMAP_HDR_H + s_idx * (strip_h + HEATMAP_STRIP_GAP)
        col_hdr_y = strip_y0 + 2

        for c, (_, gshort, _, gfps) in enumerate(strip_games):
            cx = grid_x0 + c * (cell_w + gap) + cell_w / 2
            gb = draw.textbbox((0, 0), gshort, font=f_col)
            draw.text((s(cx) - (gb[2] - gb[0]) // 2, s(col_hdr_y)), gshort, font=f_col, fill=TEXT_MAIN)
            sb = draw.textbbox((0, 0), gfps, font=f_col_sub)
            draw.text((s(cx) - (sb[2] - sb[0]) // 2, s(col_hdr_y + 16)), gfps, font=f_col_sub, fill=TEXT_DIM)

        grid_y0 = strip_y0 + HEATMAP_STRIP_HDR_H
        col_best_240: Dict[int, float] = {}
        for c, (sids, _, _, _) in enumerate(strip_games):
            vals = [
                float(run["speed_pct"])
                for p in CORE_PROFILES
                for run in [get_game_run(runs, sids, p[1], "uncapped")]
                if run is not None
            ]
            col_best_240[c] = max(vals) if vals else -1.0

        for r_idx, (plabel, p240, p480) in enumerate(CORE_PROFILES):
            ry = grid_y0 + r_idx * HEATMAP_ROW_H
            lb = draw.textbbox((0, 0), plabel, font=f_row)
            draw.text(
                (s(x0 + 18), s(ry + (HEATMAP_ROW_H - 6) / 2) - (lb[3] - lb[1]) // 2),
                plabel,
                font=f_row,
                fill=TEXT_MAIN,
            )

            for c, (sids, _, _, _) in enumerate(strip_games):
                run240 = get_game_run(runs, sids, p240, "uncapped")
                run480 = get_game_run(runs, sids, p480, "uncapped")
                cx0 = grid_x0 + c * (cell_w + gap)
                cx1 = cx0 + cell_w
                mid_x = s((cx0 + cx1) / 2)

                if run240 is None:
                    draw.rounded_rectangle(
                        [s(cx0), s(ry), s(cx1), s(ry + HEATMAP_ROW_H - 6)],
                        radius=s(6),
                        fill="#1c2128",
                    )
                    mb = draw.textbbox((0, 0), "—", font=f_big)
                    draw.text((mid_x - (mb[2] - mb[0]) // 2, s(ry + 11)), "—", font=f_big, fill=TEXT_DIM)
                    continue

                r240 = float(run240["speed_pct"])
                r480 = float(run480["speed_pct"]) if run480 is not None else None
                bg, fg = heat_color(r240)
                is_best = r240 == col_best_240[c]
                draw.rounded_rectangle(
                    [s(cx0), s(ry), s(cx1), s(ry + HEATMAP_ROW_H - 6)],
                    radius=s(6),
                    fill=bg,
                    outline=TEXT_MAIN if is_best else None,
                    width=s(1.5) if is_best else 0,
                )

                t_main = f"{r240:.0f}%"
                t_sub = f"480p: {r480:.0f}%" if r480 is not None else "480p: —"
                mb = draw.textbbox((0, 0), t_main, font=f_big)
                sb = draw.textbbox((0, 0), t_sub, font=f_small)
                draw.text((mid_x - (mb[2] - mb[0]) // 2, s(ry + 4)), t_main, font=f_big, fill=fg)
                draw.text((mid_x - (sb[2] - sb[0]) // 2, s(ry + 23)), t_sub, font=f_small, fill=TEXT_MUTED)

    return block_h


def chart_heatmap_all_games(devices: List[Dict[str, Any]], out_path: Path) -> None:
    width = 1180
    active_games = resolve_active_games(devices)
    legend_items = [
        ("#5a1e24", "<100% (Too Slow)"),
        ("#4c3614", "100–129% (Tight)"),
        ("#143d4d", "130–174% (Good)"),
        ("#144234", "175–219% (Fast)"),
        ("#0f533a", "220%+ (Blazing)"),
    ]
    img_tmp, draw_tmp = new_canvas(width, 200)
    leg_h = draw_legend(draw_tmp, 32, 92, width, legend_items)
    cur_y0 = 92 + leg_h + 10

    block_h = compute_heatmap_block_height(len(active_games))
    height = cur_y0 + len(devices) * block_h + max(0, len(devices) - 1) * HEATMAP_CARD_GAP + 28
    img, draw = new_canvas(width, height)
    draw_header(
        draw,
        width,
        "All Games Uncapped Speed Matrix — 320×240 (Primary) & 640×480 (Secondary)",
        "Every game's raw headroom on one screen. White border highlights the fastest renderer per game on each device.",
    )
    draw_legend(draw, 32, 92, width, legend_items)

    cur_y = cur_y0
    for d in devices:
        bh = draw_heatmap_block(draw, 32, cur_y, width - 64, d["label"], d["color"], d["runs"], active_games)
        cur_y += bh + HEATMAP_CARD_GAP
    finish_canvas(img, out_path)


def select_stress_games(
    devices: List[Dict[str, Any]],
    active_games: Sequence[Tuple[Tuple[str, ...], str, str, str]],
) -> Tuple[Tuple[Tuple[str, ...], str, str, str], Tuple[Tuple[str, ...], str, str, str]]:
    ranked: List[Tuple[float, int, Tuple[Tuple[str, ...], str, str, str]]] = []
    for idx, spec in enumerate(active_games):
        sids = set(spec[0])
        uncapped = [
            float(r["speed_pct"])
            for d in devices
            for r in d.get("runs", [])
            if r.get("scenario_id") in sids and r.get("mode") == "uncapped" and r.get("speed_pct") is not None
        ]
        if uncapped:
            score = sum(uncapped) / len(uncapped)
        else:
            paced = [
                float(r["speed_pct"])
                for d in devices
                for r in d.get("runs", [])
                if r.get("scenario_id") in sids and r.get("mode") == "paced" and r.get("speed_pct") is not None
            ]
            score = sum(paced) / len(paced) if paced else float("inf")
        ranked.append((score, idx, spec))

    ranked.sort(key=lambda item: (item[0], item[1]))
    first = ranked[0][2]
    second = ranked[1][2] if len(ranked) > 1 else first
    return first, second


def chart_stress_spotlight(devices: List[Dict[str, Any]], out_path: Path) -> None:
    width = 1180
    n_dev = len(devices)
    row_h = max(48, 22 + n_dev * 16)
    panel_h = 78 + 34 + row_h * len(CORE_PROFILES)

    active_games = resolve_active_games(devices)
    stress_1, stress_2 = select_stress_games(devices, active_games)
    s1_ids, _, s1_full, _ = stress_1
    s2_ids, _, s2_full, _ = stress_2

    img_tmp, draw_tmp = new_canvas(width, 200)
    legend_items = [(d["color"], d["short_label"]) for d in devices] + [
        (COLOR_WARN, "Severe Pacing Regression")
    ]
    leg_h = draw_legend(draw_tmp, 32, 92, width, legend_items)
    panel_y0 = 92 + leg_h + 10
    height = panel_y0 + panel_h + 24

    img, draw = new_canvas(width, height)
    draw_header(
        draw,
        width,
        f"Real-Gameplay Stress Spotlight: {s1_full} & {s2_full}",
        "VSync ON (paced 60 Hz gameplay @ 320×240). Highlights the most demanding games' pacing regressions and frame-time spikes.",
    )
    draw_legend(draw, 32, 92, width, legend_items)

    labels = [p[0] for p in CORE_PROFILES]
    g1_vals: List[List[float]] = []
    g1_annots: Dict[Tuple[int, int], str] = {}
    g2_vals: List[List[float]] = []

    for d_idx, d in enumerate(devices):
        d_g1: List[float] = []
        d_g2: List[float] = []
        for p_idx, (_, p240, _) in enumerate(CORE_PROFILES):
            r_g1 = get_game_run(d["runs"], s1_ids, p240, "paced")
            if r_g1 is not None:
                vi = float(r_g1.get("vi_fps_avg", 0.0))
                d_g1.append(vi)
                if vi <= 52.0 and float(r_g1.get("frame_ms_max", 0.0)) >= 65.0:
                    g1_annots[(d_idx, p_idx)] = f"({float(r_g1['frame_ms_max']):.0f}ms)"
            else:
                d_g1.append(0.0)

            r_g2 = get_game_run(d["runs"], s2_ids, p240, "paced")
            d_g2.append(float(r_g2.get("missed_vsyncs", 0.0)) if r_g2 is not None else 0.0)
        g1_vals.append(d_g1)
        g2_vals.append(d_g2)

    colors = [d["color"] for d in devices]
    g2_max, g2_ticks = compute_axis_scale(g2_vals, 400.0, 100)

    panel_w = 548
    draw_grouped_barh_panel(
        draw,
        32,
        panel_y0,
        panel_w,
        panel_h,
        f"{s1_full} — Real Gameplay Paced VI FPS",
        "Higher is better (60 = full speed) · Red marks severe pacing drops",
        labels,
        g1_vals,
        colors,
        68,
        [0, 15, 30, 45, 60],
        lambda v: f"{v:.0f}" if isinstance(v, int) else f"{v:.1f}",
        ref_x=60,
        ref_label="60 Full",
        warn_thresh=52.0,
        lower_is_better=False,
        annotations=g1_annots,
    )
    draw_grouped_barh_panel(
        draw,
        600,
        panel_y0,
        panel_w,
        panel_h,
        f"{s2_full} — Paced Missed VSyncs",
        "Lower is better · Exposes GPU flip and shader compilation stutter",
        labels,
        g2_vals,
        colors,
        g2_max,
        g2_ticks,
        lambda v: f"{int(round(v))}",
        warn_thresh=200,
        lower_is_better=True,
    )
    finish_canvas(img, out_path)


def resolve_summary_path(raw: str) -> Path:
    p = Path(raw)
    if p.is_dir():
        cand = p / "summary.json"
        if cand.is_file():
            return cand
    if p.is_file():
        return p
    raise FileNotFoundError(f"Could not find summary.json at {raw}")


def load_devices(inputs: List[str], custom_labels: Optional[List[str]]) -> List[Dict[str, Any]]:
    devices: List[Dict[str, Any]] = []
    for idx, raw in enumerate(inputs):
        sfile = resolve_summary_path(raw)
        data = json.loads(sfile.read_text(encoding="utf-8"))
        full_label = build_device_label(data, idx, custom_labels)
        short_label = full_label.split(" @")[0].rstrip(")") + (")" if " (" in full_label and " @" in full_label else "")
        devices.append({
            "label": full_label,
            "short_label": custom_labels[idx] if custom_labels and idx < len(custom_labels) else short_label,
            "color": DEVICE_PALETTE[idx % len(DEVICE_PALETTE)],
            "runs": data.get("runs", []),
            "meta": data,
        })
    return devices


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate 4 high-DPI dark-theme comparison PNG charts for 1 to N N64Bench result sets."
    )
    ap.add_argument("inputs", nargs="+", help="One or more result directories or summary.json files")
    ap.add_argument("-o", "--out", required=True, help="Output directory for generated PNG charts")
    ap.add_argument("--labels", nargs="*", help="Optional custom display labels matching input order")
    args = ap.parse_args()

    devices = load_devices(args.inputs, args.labels)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    chart_overview_speed(devices, out_dir / "01-overview-uncapped-speed.png")
    chart_overview_pacing(devices, out_dir / "02-overview-pacing-health.png")
    chart_heatmap_all_games(devices, out_dir / "03-heatmap-all-games.png")
    chart_stress_spotlight(devices, out_dir / "04-stress-test-deep-dive.png")
    print(f"Generated 4 charts for {len(devices)} device(s) in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
