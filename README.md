# NextUI N64 Benchmark Tool Pak (`N64Bench.pak`)

Automated Nintendo 64 performance benchmark suite for NextUI (`tg5040`, `tg5050`, `h700`).

Measures real gameplay performance (Paced / VSync ON) and raw headroom (Uncapped / VSync OFF) through NextUI's actual MinArch GLES/HWR pipeline, allowing apples-to-apples comparisons between **Mupen64Plus-ReARMed** and **ParaLLEl-N64** across renderers (`gles2n64`, `Rice`, `Glide64`), resolutions (`320x240`, `640x480`), and frameskip settings.

## Installing

### Option A: NextUI Pak Store
Install **N64Bench** directly from the NextUI Pak Store (`N64Bench.pak.zip`, root-level archive layout matching `pak.json`).

### Option B: Manual SD Card Install
1. Download `N64Bench-manual.zip` from Releases.
2. Extract it directly into `/mnt/SDCARD/Tools/<platform>/` so the launcher sits at:
   `/mnt/SDCARD/Tools/<platform>/N64Bench.pak/launch.sh`
   (`tg5040` for TrimUI Brick / Smart Pro, `tg5050` for TrimUI TG5050, `h700` for Anbernic H700 devices).

## Setting Up ROMs & Reference Savestates

### ROMs (Auto-Discovery)
N64Bench automatically looks for your ROMs in:
1. The path configured in `config/scenarios.json` (`N64Bench.pak/roms/...`)
2. `N64Bench.pak/roms/` (case-insensitive stem match across `.zip`, `.z64`, `.n64`, `.v64`)
3. Any `/mnt/SDCARD/Roms/` subfolder containing `N64` or `Nintendo 64` (case-insensitive)

If your N64 ROMs are already on your SD card under `/mnt/SDCARD/Roms/N64/` or `/mnt/SDCARD/Roms/Nintendo 64 (N64)/`, you do not need to duplicate them.

Savestates are region- and revision-sensitive. Use the following uncompressed No-Intro USA (`.z64`) ROMs (or zipped copies of them):

| Scenario ID | Expected Filename | Size | CRC32 | MD5 | SHA-1 | SHA-256 |
| --- | --- | ---: | --- | --- | --- | --- |
| `sm64-demo` | `Super Mario 64 (USA).z64` | 8 MiB | `3ce60709` | `20b854b239203baf6c961b850a4a51a2` | `9bef1128717f958171a4afac3ed78ee2bb4e86ce` | `17ce077343c6133f8c9f2d6d6d9a4ab62c8cd2aa57c40aea1f490b4c8bb21d91` |
| `oot-demo` | `Legend of Zelda, The - Ocarina of Time (USA).z64` | 32 MiB | `cd16c529` | `5bd1fe107bf8106b2ab6650abecd54d6` | `ad69c91157f6705e8ab06c79fe08aad47bb57ba7` | `c916ab315fbe82a22169bff13d6b866e9fddc907461eb6b0a227b82acdf5b506` |
| `fzerox-demo` | `F-Zero X (USA).z64` | 16 MiB | `0b561fba` | `753437d0d8ada1d12f3f9cf0f0a5171f` | `5f658e88ffa9de23cba6986a8fd3d3a90d7b4340` | `2be0f861c30752bbdfa727753a454108bc973c27ad814744f191b1278c1f482d` |
| `mk64-demo` | `Mario Kart 64 (USA).z64` | 12 MiB | `434389c1` | `3a67d9986f54eb282924fca4cd5f6dff` | `579c48e211ae952530ffc8738709f078d5dd215e` | `d6b8538dd63f0132ecb2856e7d32816ed3c30e3e479aecd23cf83fb6ba17a5da` |
| `goldeneye-demo` | `GoldenEye 007 (USA).z64` | 12 MiB | `b6330846` | `70c525880240c1e838b8b1be35666c3b` | `abe01e4aeb033b6c0836819f549c791b26cfde83` | `2cdcec8a9f0cb6e36337f3ee39d8ad105dc8afa6ba1c02d466e8f5b771f9a162` |
| `conker-demo` | `Conker's Bad Fur Day (USA).z64` | 64 MiB | `ce8cc172` | `00e2920665f2329b95797a7eaabc2390` | `4cbadd3c4e0729dec46af64ad018050eada4f47a` | `32e6a8b970ec12ac5f782344945aa0c98a193832eefb687529d03bab6948714b` |

### Reference Savestates
The reference suite uses **zero-input built-in in-game attract demos**, ensuring Mupen64Plus-ReARMed and ParaLLEl-N64 render identical moving 3D gameplay with zero input drift between cores or frameskip modes.

Place the matching ReARMed savestates (`M64+SAVE` v1.6 — compatible with both ReARMed and ParaLLEl-N64) in `N64Bench.pak/states/`:
- **Automatic Savestate Generation (`capture_frame`)**: Run **Generate Missing Savestates (Auto)** (or accept the pre-benchmark prompt) to deterministically cold-boot missing scenarios with the bundled ReARMed core (`320x240`, Rice, `frameskip = disabled`) up to each scenario's configured `capture_frame` and save uncompressed `states/<id>.st0`.
- **Capture State / Find Frame**: Select any scenario interactively, **Hold R1** to fast-forward past logos/intros, **Tap A** once the attract demo begins to save `states/<id>.st0` and record the exact frame number to `states/capture_frames.txt`, or **Hold MENU** to cancel.
- If you receive `n64bench-states.tar.gz`, extract it inside `N64Bench.pak/` (`tar -xzf n64bench-states.tar.gz`), or drop `.st0.gz` files into `N64Bench.pak/states/` — `launch.sh` automatically decompresses any `.st0.gz` files on startup.
- Any scenario whose ROM or savestate is missing is skipped automatically.

## Running Benchmarks On-Device

1. Launch **N64Bench** from NextUI's **Tools** menu.
2. Run **Check Setup / Preflight** to confirm ROMs found, savestates found, SoC model, NextUI version, and battery level.
3. Select **Run Benchmark Tier (Recommended)** -> **Community Standard (10 Profiles, 240p+480p)** for standardized cross-device submissions (compares all 5 renderer/core profiles at both `320x240` and `640x480` in `paced` and `uncapped` modes).
   - Keep your handheld plugged in or above 50% battery before starting.
   - Hold **MENU** during any run to abort cleanly.

## Submitting Results

Every completed run automatically writes a self-contained single-file archive (including `summary.json`, `summary.csv`, `summary.txt`, `runs/`, `frames/`, and `bench.log`):
- `/mnt/SDCARD/N64Bench-Submissions/N64Bench_<platform>_<device>_<timestamp>.tar.gz`
- `N64Bench.pak/results/N64Bench_<platform>_<device>_<timestamp>.tar.gz`

You can also use **Bundle Last Result** from the main menu to re-package your most recent run.

To submit results:
- Open a GitHub issue using the **Submit N64 Benchmark Results** form and drag-and-drop your `N64Bench_*.tar.gz` file, or share that single `.tar.gz` file in Discord.

## PC Analysis & Chart Generation

### Ingest & Verify Submissions
`tools/ingest.py` uses Python 3 standard library only to safely extract `.tar.gz`/`.tgz`/`.zip` archives or folders, verify `schema_version` and No-Intro `rom_sha256` hashes, and optionally generate reports and charts in one command:

```bash
python3 tools/ingest.py ~/Downloads/N64Bench_*.tar.gz -o results/ --report report/ --charts report/charts/
```

Pass `--allow-unverified` if ingesting schema v2 bundles whose `rom_sha256` was hashed from compressed `.zip` ROMs rather than uncompressed `.z64` files.

### Generate Interactive Report (`report.py`)
Zero third-party dependencies (Python 3 standard library only):

```bash
python3 tools/report.py results/* -o report/
```

Generates `report/index.html` (interactive dashboard with device environment cards and frame-time spike viewer) and `report/summary.md`.

### Generate High-DPI Comparison PNGs (`generate_charts.py`)
Uses Pillow (`PIL`) to render 4 dark-theme comparison PNGs for 1 to N devices:

```bash
python3 tools/generate_charts.py results/h700_* results/tg5040_* -o report/charts/
```

## Building from Source

```bash
make release      # Builds minarch-bench.elf, benchctl, UI tools, cores, and dist zips + SHA256SUMS.txt
make states-pack  # Packs local states/*.st0 into dist/n64bench-states.tar.gz (if present)
```

Builds `minarch-bench.elf` (from NextUI `32626b02` + `patches/0001-minarch-benchmark.patch`) and bundles both `mupen64plus_rearmed_libretro.so` and `parallel_n64_libretro.so` for `tg5040`, `tg5050`, and `h700`.

## A/B Patch Testing

To compare two builds of a core (for example, ReARMed with vs. without a patch), drop the alternate `.so` into `cores/<platform>/` and add a profile entry in `config/profiles.json` referencing that filename.
