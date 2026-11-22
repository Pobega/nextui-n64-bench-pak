# NextUI N64 Benchmark Tool Pak (`N64Bench.pak`)

Automated, repeatable Nintendo 64 performance benchmark suite for **NextUI** (`tg5040`, `tg5050`, `h700`).

## Expected Use Case

`N64Bench` is built for **apples-to-apples N64 performance comparisons** across NextUI handhelds, libretro cores, renderers, and resolutions:

- Compares **Mupen64Plus-ReARMed** and **ParaLLEl-N64** across `gles2n64`, `Rice`, and `Glide64` at both `320x240` and `640x480`.
- Runs through NextUI's real MinArch GLES/HWR video & audio pipeline, measuring both **Paced (VSync ON)** smoothness (`VI/s`, `1% low`, missed VSyncs, frame-time percentiles) and **Uncapped (VSync OFF)** raw headroom (`speed %`).
- Uses **6 zero-input built-in in-game attract demos** with **deterministic frame-accurate on-device savestate generation** — every device cold-boots your ROMs to the exact same emulated N64 frame and produces bit-identical savestates (verified by SHA-256), so **no savestates need to be shared** and there is zero input drift between cores.
- **Time & power:** First-time auto-generation takes ~2 minutes total; the recommended **Community Standard** suite (10 profiles × 6 games × paced/uncapped = 120 runs) runs unattended in **~32–35 minutes**. Plug in a charger or start above 50% battery, and hold **MENU** anytime to abort cleanly.

## Installing

1. Download **`N64Bench.zip`** from [Releases](https://github.com/Pobega/nextui-n64-bench-pak/releases).
2. Extract it into `/mnt/SDCARD/Tools/<platform>/` on your SD card, matching your device platform:
   - `tg5040` — TrimUI Brick / TrimUI Smart Pro
   - `tg5050` — TrimUI Smart Pro S (TG5050)
   - `h700` — Anbernic H700 devices (RG35XX Plus / SP / H / 2024, RG40XX H / V, RGCubeXX)
3. Verify the launcher sits at:
   `/mnt/SDCARD/Tools/<platform>/N64Bench.pak/launch.sh`

## Where ROMs Go & Expected Hashes

### Auto-Discovery Locations
You **do not** need to duplicate ROMs you already have on your SD card. `N64Bench` automatically searches for each game (case-insensitive filename stem match across `.zip`, `.z64`, `.n64`, and `.v64`) in:

1. `N64Bench.pak/roms/` (inside the installed Tool Pak)
2. Any `/mnt/SDCARD/Roms/` subfolder containing `N64` or `Nintendo 64` (for example `/mnt/SDCARD/Roms/N64/` or `/mnt/SDCARD/Roms/Nintendo 64 (N64)/`)

- **Partial sets work:** If you only have some of the 6 ROMs, missing games are skipped automatically and the remaining games still benchmark cleanly.
- **No savestates required:** Missing savestates are generated automatically on the device on first run and saved into `N64Bench.pak/states/`.

### Expected ROMs (No-Intro USA)
Because deterministic savestate generation depends on exact game code and region timing, use clean **No-Intro USA** dumps (either uncompressed `.z64`/`.v64`/`.n64` or zipped `.zip` copies of them). Zipped and byte-swapped copies of these exact dumps work seamlessly and produce verified bit-identical savestates:

| Scenario ID | Expected Filename | Size | CRC32 | MD5 | SHA-1 | SHA-256 (`.z64`) |
| --- | --- | ---: | --- | --- | --- | --- |
| `sm64-demo` | `Super Mario 64 (USA).z64` | 8 MiB | `3ce60709` | `20b854b239203baf6c961b850a4a51a2` | `9bef1128717f958171a4afac3ed78ee2bb4e86ce` | `17ce077343c6133f8c9f2d6d6d9a4ab62c8cd2aa57c40aea1f490b4c8bb21d91` |
| `oot-demo` | `Legend of Zelda, The - Ocarina of Time (USA).z64` | 32 MiB | `cd16c529` | `5bd1fe107bf8106b2ab6650abecd54d6` | `ad69c91157f6705e8ab06c79fe08aad47bb57ba7` | `c916ab315fbe82a22169bff13d6b866e9fddc907461eb6b0a227b82acdf5b506` |
| `fzerox-demo` | `F-Zero X (USA).z64` | 16 MiB | `0b561fba` | `753437d0d8ada1d12f3f9cf0f0a5171f` | `5f658e88ffa9de23cba6986a8fd3d3a90d7b4340` | `2be0f861c30752bbdfa727753a454108bc973c27ad814744f191b1278c1f482d` |
| `mk64-demo` | `Mario Kart 64 (USA).z64` | 12 MiB | `434389c1` | `3a67d9986f54eb282924fca4cd5f6dff` | `579c48e211ae952530ffc8738709f078d5dd215e` | `d6b8538dd63f0132ecb2856e7d32816ed3c30e3e479aecd23cf83fb6ba17a5da` |
| `goldeneye-demo` | `GoldenEye 007 (USA).z64` | 12 MiB | `b6330846` | `70c525880240c1e838b8b1be35666c3b` | `abe01e4aeb033b6c0836819f549c791b26cfde83` | `2cdcec8a9f0cb6e36337f3ee39d8ad105dc8afa6ba1c02d466e8f5b771f9a162` |
| `conker-demo` | `Conker's Bad Fur Day (USA).z64` | 64 MiB | `ce8cc172` | `00e2920665f2329b95797a7eaabc2390` | `4cbadd3c4e0729dec46af64ad018050eada4f47a` | `32e6a8b970ec12ac5f782344945aa0c98a193832eefb687529d03bab6948714b` |

## Running Benchmarks On-Device

1. Open **Tools → N64Bench** in NextUI.
2. *(Optional)* Select **Check Setup** to confirm how many ROMs were detected (`6/6`), your SoC/NextUI version, and battery level. Missing savestates are normal on first launch (`will auto-generate`).
3. Select **Run Community Benchmark (Recommended)** and tap **START** once:
   - Any missing savestates are auto-generated deterministically (~2 min), then the full 120-run benchmark starts automatically — no second confirmation needed.
   - Keep the device plugged in (or >50% battery) and leave it on a flat surface until the **Benchmark Complete!** screen appears.
   - Hold **MENU** anytime if you need to abort early.
4. For smaller/targeted tests, use **Custom Benchmark...** (tiers, single profile, single game, or paced/uncapped mode). Use **Tools & Advanced...** for standalone savestate generation, re-bundling a result, or dev frame capture.

## Getting Benchmark Results Off Your Device

When a benchmark finishes, `N64Bench` automatically packages everything (`summary.json`, `summary.csv`, `summary.txt`, per-run JSONs, per-frame CSVs, and `bench.log`) into **one small ~480 KB archive** in two places:

- **Primary (easy to find):** `/mnt/SDCARD/N64Bench-Submissions/N64Bench_<platform>_<device>_<timestamp>.tar.gz`
- **Backup copy:** `/mnt/SDCARD/Tools/<platform>/N64Bench.pak/results/N64Bench_<platform>_<device>_<timestamp>.tar.gz`

You can grab that `.tar.gz` file off your handheld using whichever method is easiest:

- **SD Card Reader:** Power off the handheld, put the SD card into your computer, open the `N64Bench-Submissions` folder at the root of the SD card, and copy the `N64Bench_*.tar.gz` file.
- **USB / Wi-Fi / SFTP Transfer:** Connect via your normal NextUI file-transfer pak and browse to `/mnt/SDCARD/N64Bench-Submissions/`.
- **ADB (over USB):**
  ```bash
  adb pull /mnt/SDCARD/N64Bench-Submissions/ .
  ```

*(Need to re-create the archive later? Run **Tools & Advanced... → Bundle Last Result** inside N64Bench.)*

### Sharing Your Results
- Open a GitHub issue using the **Submit N64 Benchmark Results** form and attach your single `N64Bench_*.tar.gz` file, or drop that `.tar.gz` file in Discord.

## PC Analysis & Chart Generation

### Ingest & Verify Submissions
`tools/ingest.py` uses Python 3 standard library only to safely extract `.tar.gz`/`.tgz`/`.zip` bundles, verify `schema_version` and canonical deterministic `state_sha256` (or No-Intro `rom_sha256`) hashes, and optionally build the HTML dashboard and comparison PNGs in one command:

```bash
python3 tools/ingest.py ~/Downloads/N64Bench_*.tar.gz -o results/ --report report/ --charts report/charts/
```

Pass `--allow-unverified` only if ingesting custom/non-canonical ROMs or custom savestates.

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
