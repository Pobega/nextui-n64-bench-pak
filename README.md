# NextUI N64 Benchmark Tool Pak (`N64Bench.pak`)

Automated Nintendo 64 performance benchmark suite for NextUI (`tg5040`, `tg5050`, `h700`).

Measures real gameplay performance (Paced / VSync ON) and raw headroom (Uncapped / VSync OFF) through NextUI's actual MinArch GLES/HWR pipeline, allowing apples-to-apples comparisons between **Mupen64Plus-ReARMed** and **ParaLLEl-N64** across renderers (`gles2n64`, `Rice`, `Glide64`), resolutions (`320x240`, `640x480`), and frameskip modes.

## Quick Start (On-Device)

1. Extract `N64Bench.pak.zip` into `/mnt/SDCARD/Tools/<platform>/N64Bench.pak/`.
2. Copy your N64 ROMs into `N64Bench.pak/roms/` (or edit `config/scenarios.json` to point directly at `/mnt/SDCARD/Roms/...`).
3. Place matching ReARMed savestates (`M64+SAVE` v1.6 — compatible with both ReARMed and ParaLLEl-N64) in `N64Bench.pak/states/`.
   - Any scenario whose ROM or savestate is missing is skipped automatically.
4. Launch **N64Bench** from NextUI's **Tools** menu.
   - Hold **MENU** during any run to abort cleanly.
5. Results are saved to `N64Bench.pak/results/<platform>_<timestamp>/`:
   - `summary.json` — aggregate metrics + device, thermal, core SHA256, and profile metadata
   - `summary.csv` — flat spreadsheet-ready summary
   - `frames/<run_id>.csv` — per-frame timing deltas and `was_new_frame` flags

## Generating Comparison Graphs (PC)

Copy one or more `results/<platform>_<timestamp>/` folders from any `tg5040`, `tg5050`, or `h700` device to your PC and run:

```bash
python3 tools/report.py results/* -o report/
```

This generates a self-contained interactive HTML dashboard (`report/index.html`) and Markdown summary (`report/summary.md`) with zero third-party Python dependencies.

## Building from Source

```bash
make release
```

Builds `minarch-bench.elf` (from NextUI `32626b02` + `patches/0001-minarch-benchmark.patch`) and bundles both `mupen64plus_rearmed_libretro.so` and `parallel_n64_libretro.so` for `tg5040`, `tg5050`, and `h700`.

## A/B Patch Testing

To compare two builds of a core (for example, ReARMed with vs. without a patch), drop the alternate `.so` into `cores/<platform>/` and add a profile entry in `config/profiles.json` referencing that filename.
