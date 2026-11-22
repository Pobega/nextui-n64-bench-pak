#!/usr/bin/env python3
"""
Ingest, verify, and organize N64Bench result archives (.tar.gz, .tgz, .zip) or directories.
Zero third-party dependencies (Python 3 standard library only).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


CANONICAL_NO_INTRO_SHA256: Dict[str, str] = {
    "sm64-bobomb": "17ce077343c6133f8c9f2d6d6d9a4ab62c8cd2aa57c40aea1f490b4c8bb21d91",
    "oot-hyrule": "c916ab315fbe82a22169bff13d6b866e9fddc907461eb6b0a227b82acdf5b506",
    "fzerox-race": "2be0f861c30752bbdfa727753a454108bc973c27ad814744f191b1278c1f482d",
    "mk64-race": "d6b8538dd63f0132ecb2856e7d32816ed3c30e3e479aecd23cf83fb6ba17a5da",
    "goldeneye-dam": "2cdcec8a9f0cb6e36337f3ee39d8ad105dc8afa6ba1c02d466e8f5b771f9a162",
}

SUPPORTED_SCHEMAS = (1, 2)
MAX_ARCHIVE_MEMBERS = 4096


def sanitize_slug(raw: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (raw or "").strip()).strip("-.")
    return cleaned or fallback


def is_safe_member_path(member_name: str, dest_root: Path) -> bool:
    if not member_name:
        return False
    norm = member_name.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        return False
    parts = Path(norm).parts
    if any(part == ".." for part in parts):
        return False
    resolved = (dest_root / norm).resolve()
    root_resolved = dest_root.resolve()
    return resolved == root_resolved or root_resolved in resolved.parents


def safe_extract_tar(archive_path: Path, dest_dir: Path) -> None:
    with tarfile.open(archive_path, "r:*") as tf:
        members = tf.getmembers()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError(f"Archive exceeds {MAX_ARCHIVE_MEMBERS} entries")
        for member in members:
            if not is_safe_member_path(member.name, dest_dir):
                raise ValueError(f"Unsafe archive path rejected: {member.name}")
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ValueError(f"Unsupported special file in archive: {member.name}")
        for member in members:
            target = dest_dir / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                src_fp = tf.extractfile(member)
                if src_fp is None:
                    continue
                with src_fp, target.open("wb") as out_fp:
                    shutil.copyfileobj(src_fp, out_fp)


def safe_extract_zip(archive_path: Path, dest_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            raise ValueError(f"Archive exceeds {MAX_ARCHIVE_MEMBERS} entries")
        for info in infos:
            if not is_safe_member_path(info.filename, dest_dir):
                raise ValueError(f"Unsafe zip path rejected: {info.filename}")
        for info in infos:
            target = dest_dir / info.filename
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src_fp, target.open("wb") as out_fp:
                    shutil.copyfileobj(src_fp, out_fp)


def locate_summary_dirs(root: Path) -> List[Path]:
    if (root / "summary.json").is_file():
        return [root]
    found: List[Path] = []
    for sfile in sorted(root.rglob("summary.json")):
        if sfile.is_file():
            found.append(sfile.parent)
    return found


def format_run_timestamp(data: Dict[str, Any], source_dir: Path) -> str:
    ts_utc = str(data.get("timestamp_utc", "")).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z?$", ts_utc)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}-{m.group(4)}{m.group(5)}{m.group(6)}"
    m_dir = re.search(r"(\d{8}-\d{6})$", source_dir.name)
    if m_dir:
        return m_dir.group(1)
    return "unknown-time"


def evaluate_submission(summary_path: Path) -> Dict[str, Any]:
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    schema = data.get("schema_version")
    if schema not in SUPPORTED_SCHEMAS:
        raise ValueError(f"Unsupported schema_version: {schema}")

    runs = data.get("runs", [])
    if not isinstance(runs, list) or not runs:
        raise ValueError("summary.json contains no runs")

    ok_count = sum(1 for r in runs if r.get("status") == "ok")
    state_fail_count = sum(1 for r in runs if r.get("status") == "state_failed")
    other_err_count = len(runs) - ok_count - state_fail_count

    temps = [
        float(r[k])
        for r in runs
        for k in ("soc_temp_start_c", "soc_temp_end_c")
        if isinstance(r.get(k), (int, float)) and float(r[k]) > 0
    ]
    peak_temp = max(temps) if temps else -1.0

    rom_hashes_present = 0
    rom_hashes_matched = 0
    rom_hashes_mismatched = 0
    for r in runs:
        r_hash = str(r.get("rom_sha256", "")).strip().lower()
        sid = str(r.get("scenario_id", ""))
        if not r_hash or r_hash in ("unknown", "none"):
            continue
        rom_hashes_present += 1
        expected = CANONICAL_NO_INTRO_SHA256.get(sid)
        if expected and r_hash == expected:
            rom_hashes_matched += 1
        elif expected:
            rom_hashes_mismatched += 1

    if rom_hashes_present == 0:
        hash_status = "unverified (schema v1)" if schema == 1 else "unverified (no rom_sha256)"
        is_hash_mismatch = False
    elif rom_hashes_mismatched > 0:
        hash_status = f"mismatch ({rom_hashes_matched}/{rom_hashes_present} canonical)"
        is_hash_mismatch = True
    else:
        hash_status = f"verified ({rom_hashes_matched}/{rom_hashes_present})"
        is_hash_mismatch = False

    return {
        "data": data,
        "schema": schema,
        "platform": str(data.get("platform", "unknown")),
        "device": str(data.get("device", data.get("platform", "unknown"))),
        "total_runs": len(runs),
        "ok_runs": ok_count,
        "state_failures": state_fail_count,
        "other_errors": other_err_count,
        "peak_temp_c": peak_temp,
        "hash_status": hash_status,
        "is_hash_mismatch": is_hash_mismatch,
        "timestamp": format_run_timestamp(data, summary_path.parent),
    }


def unique_dest_dir(dest_root: Path, base_name: str) -> Path:
    candidate = dest_root / base_name
    if not candidate.exists():
        return candidate
    idx = 2
    while (dest_root / f"{base_name}_{idx}").exists():
        idx += 1
    return dest_root / f"{base_name}_{idx}"


def ingest_one_dir(
    src_dir: Path,
    source_label: str,
    dest_root: Path,
    allow_unverified: bool,
) -> Optional[Dict[str, Any]]:
    summary_path = src_dir / "summary.json"
    info = evaluate_submission(summary_path)

    if info["is_hash_mismatch"]:
        print(
            f"Warning [{source_label}]: ROM SHA-256 {info['hash_status']} "
            f"(may be compressed .zip or non-No-Intro ROM).",
            file=sys.stderr,
        )
        if not allow_unverified:
            print(
                f"Skipped [{source_label}]: pass --allow-unverified to ingest mismatched ROM hashes.",
                file=sys.stderr,
            )
            return None

    plat = sanitize_slug(info["platform"])
    dev = sanitize_slug(info["device"])
    ts = sanitize_slug(info["timestamp"])
    target_dir = unique_dest_dir(dest_root, f"{plat}_{dev}_{ts}")
    shutil.copytree(src_dir, target_dir)
    info["dest_dir"] = target_dir
    info["source"] = source_label
    return info


def process_input_path(
    raw_path: Path,
    dest_root: Path,
    allow_unverified: bool,
) -> List[Dict[str, Any]]:
    ingested: List[Dict[str, Any]] = []
    if raw_path.is_dir():
        run_dirs = locate_summary_dirs(raw_path)
        if not run_dirs:
            print(f"Warning: no summary.json found in directory {raw_path}", file=sys.stderr)
            return ingested
        for rdir in run_dirs:
            try:
                res = ingest_one_dir(rdir, str(raw_path), dest_root, allow_unverified)
                if res:
                    ingested.append(res)
            except Exception as exc:
                print(f"Error processing {rdir}: {exc}", file=sys.stderr)
        return ingested

    if not raw_path.is_file():
        print(f"Warning: input not found: {raw_path}", file=sys.stderr)
        return ingested

    lower = raw_path.name.lower()
    with tempfile.TemporaryDirectory(prefix="n64bench-ingest-") as tmp:
        tmp_path = Path(tmp)
        try:
            if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
                safe_extract_tar(raw_path, tmp_path)
            elif lower.endswith(".zip"):
                safe_extract_zip(raw_path, tmp_path)
            else:
                print(f"Warning: unsupported archive format: {raw_path}", file=sys.stderr)
                return ingested
        except Exception as exc:
            print(f"Error extracting {raw_path}: {exc}", file=sys.stderr)
            return ingested

        run_dirs = locate_summary_dirs(tmp_path)
        if not run_dirs:
            print(f"Warning: no summary.json found inside {raw_path}", file=sys.stderr)
            return ingested
        for rdir in run_dirs:
            try:
                res = ingest_one_dir(rdir, raw_path.name, dest_root, allow_unverified)
                if res:
                    ingested.append(res)
            except Exception as exc:
                print(f"Error validating {raw_path.name} ({rdir.name}): {exc}", file=sys.stderr)
    return ingested


def print_summary_table(records: List[Dict[str, Any]]) -> None:
    if not records:
        print("No submissions ingested.")
        return
    print("")
    print(f"{'Destination':<34} {'Platform/Dev':<16} {'Sch':>3} {'OK/Tot':>8} {'Peak':>7}  {'Verification'}")
    print("-" * 96)
    for rec in records:
        dest_name = rec["dest_dir"].name
        pdev = f"{rec['platform']}/{rec['device']}"
        ok_tot = f"{rec['ok_runs']}/{rec['total_runs']}"
        peak = f"{rec['peak_temp_c']:.1f}C" if rec["peak_temp_c"] > 0 else "—"
        err_note = ""
        if rec["state_failures"] or rec["other_errors"]:
            err_note = f" [err:{rec['state_failures'] + rec['other_errors']}]"
        print(f"{dest_name:<34} {pdev:<16} v{rec['schema']:<2} {ok_tot:>8} {peak:>7}  {rec['hash_status']}{err_note}")
    print("")


def find_valid_run_dirs(dest_root: Path) -> List[Path]:
    return sorted(
        d for d in dest_root.iterdir()
        if d.is_dir() and (d / "summary.json").is_file()
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Ingest, verify, and organize N64Bench result archives or directories."
    )
    ap.add_argument("inputs", nargs="+", help="Archives (.tar.gz, .tgz, .zip) or result directories")
    ap.add_argument("-o", "--out", required=True, help="Destination directory for verified runs")
    ap.add_argument("--report", help="Optional output directory to generate HTML/Markdown report via report.py")
    ap.add_argument("--charts", help="Optional output directory to generate comparison PNGs via generate_charts.py")
    ap.add_argument(
        "--allow-unverified",
        action="store_true",
        help="Allow ingesting schema v2 submissions whose rom_sha256 does not match canonical No-Intro hashes",
    )
    args = ap.parse_args()

    dest_root = Path(args.out)
    dest_root.mkdir(parents=True, exist_ok=True)

    all_ingested: List[Dict[str, Any]] = []
    for raw in args.inputs:
        all_ingested.extend(process_input_path(Path(raw), dest_root, args.allow_unverified))

    print_summary_table(all_ingested)

    valid_dirs = find_valid_run_dirs(dest_root)
    if not valid_dirs:
        print("Error: no valid result directories in destination.", file=sys.stderr)
        return 1

    tools_dir = Path(__file__).resolve().parent

    if args.report:
        cmd = [sys.executable, str(tools_dir / "report.py"), *[str(d) for d in valid_dirs], "-o", args.report]
        subprocess.run(cmd, check=True)

    if args.charts:
        cmd = [sys.executable, str(tools_dir / "generate_charts.py"), *[str(d) for d in valid_dirs], "-o", args.charts]
        subprocess.run(cmd, check=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
