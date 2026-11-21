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

## Expected Benchmark ROMs (No-Intro `.z64`)

Savestates are region- and revision-sensitive. To match the reference benchmark savestates, use the following uncompressed No-Intro USA (`.z64`) ROMs (either placed directly or zipped inside `N64Bench.pak/roms/`):

| Scenario ID | Expected Filename | Size | CRC32 | MD5 | SHA-1 |
| --- | --- | ---: | --- | --- | --- |
| `sm64-bobomb` | `Super Mario 64 (USA).z64` | 8 MiB | `3ce60709` | `20b854b239203baf6c961b850a4a51a2` | `9bef1128717f958171a4afac3ed78ee2bb4e86ce` |
| `oot-hyrule` | `Legend of Zelda, The - Ocarina of Time (USA).z64` | 32 MiB | `cd16c529` | `5bd1fe107bf8106b2ab6650abecd54d6` | `ad69c91157f6705e8ab06c79fe08aad47bb57ba7` |
| `fzerox-race` | `F-Zero X (USA).z64` | 16 MiB | `0b561fba` | `753437d0d8ada1d12f3f9cf0f0a5171f` | `5f658e88ffa9de23cba6986a8fd3d3a90d7b4340` |
| `mk64-race` | `Mario Kart 64 (USA).z64` | 12 MiB | `434389c1` | `3a67d9986f54eb282924fca4cd5f6dff` | `579c48e211ae952530ffc8738709f078d5dd215e` |
| `goldeneye-dam` | `GoldenEye 007 (USA).z64` | 12 MiB | `b6330846` | `70c525880240c1e838b8b1be35666c3b` | `abe01e4aeb033b6c0836819f549c791b26cfde83` |

*(SHA-256 hashes: SM64 `17ce077343c6133f8c9f2d6d6d9a4ab62c8cd2aa57c40aea1f490b4c8bb21d91`, OoT `c916ab315fbe82a22169bff13d6b866e9fddc907461eb6b0a227b82acdf5b506`, F-Zero X `2be0f861c30752bbdfa727753a454108bc973c27ad814744f191b1278c1f482d`, MK64 `d6b8538dd63f0132ecb2856e7d32816ed3c30e3e479aecd23cf83fb6ba17a5da`, GoldenEye `2cdcec8a9f0cb6e36337f3ee39d8ad105dc8afa6ba1c02d466e8f5b771f9a162`.)*

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
