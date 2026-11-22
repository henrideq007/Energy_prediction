"""Share the data cache between the laptop, GitHub Actions and the cloud agents.

The fetchers cache every downloaded chunk in data/raw (ENTSO-E, JAO, Elia, weather, TTF cache)
and manual inputs live in data/external. With that cache restored, `energy-forecast fetch` only
re-downloads the recent chunks, so the weekly GitHub job stays short.

    python scripts/publish_data.py publish      # laptop or CI: upload dataset + cache to release data-latest
    python scripts/publish_data.py restore      # CI or agent: download + unpack the cache and the dataset
    python scripts/publish_data.py publish --dry-run

Needs the GitHub CLI (`gh`, authenticated: `gh auth login`) on the laptop. In GitHub Actions the
workflow token is used (GH_TOKEN).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = "data-latest"
CACHE_DIRS = ["data/raw", "data/external"]
ARCHIVE = ROOT / "data" / "processed" / "raw-cache.tar.gz"
DATASET_FILES = ["data/processed/dataset.parquet", "data/processed/dataset_clean.parquet",
                 "reports/validation_report.md", "reports/data_coverage.md"]
MAX_ASSET_BYTES = 2 * 1024**3  # GitHub release asset limit
NOTES = ("Data cache shared by the laptop, GitHub Actions (fetch-data.yml) and the cloud agents. "
         "Sources: ENTSO-E Transparency Platform, Open-Meteo, Elia Open Data, JAO, THE, EEX, Yahoo Finance. "
         "Regenerable with `energy-forecast fetch`.")


# Not republished in the PUBLIC release: EEX terms do not clearly allow redistributing its raw
# auction reports. The fetch re-downloads them from eex.com automatically (commodities._ensure_eex_reports).
EXCLUDE_DIRS = ("data/raw/eex",)


def _skip(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if info.name.endswith(".gitkeep"):
        return None
    if any(info.name == d or info.name.startswith(d + "/") for d in EXCLUDE_DIRS):
        return None
    return info


def build_archive(root: Path = ROOT, archive: Path = ARCHIVE) -> Path:
    """Pack data/raw and data/external into one .tar.gz (paths relative to the repo root)."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        for d in CACHE_DIRS:
            if (root / d).exists():
                tar.add(root / d, arcname=d, filter=_skip)
    return archive


def extract_archive(archive: Path, root: Path = ROOT) -> None:
    """Unpack the cache archive into the repo, refusing paths outside data/."""
    with tarfile.open(archive, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.name.startswith("data/") and ".." not in Path(m.name).parts]
        try:
            tar.extractall(root, members=members, filter="data")
        except TypeError:  # Python without tarfile filters
            tar.extractall(root, members=members)


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    if shutil.which("gh") is None:
        sys.exit("GitHub CLI `gh` not found — install it (winget install GitHub.cli) and run `gh auth login`.")
    return subprocess.run(["gh", *args], cwd=ROOT, check=check, text=True, capture_output=not check)


def publish(dry_run: bool = False) -> None:
    files = [ROOT / f for f in DATASET_FILES if (ROOT / f).exists()]
    if not (ROOT / DATASET_FILES[0]).exists():
        sys.exit(f"{DATASET_FILES[0]} not found — run `python -m energy_forecast fetch` first.")
    archive = build_archive()
    files.append(archive)
    for f in files:
        size = f.stat().st_size
        print(f"{f.relative_to(ROOT)}: {size / 1024**2:,.1f} MB")
        if size > MAX_ASSET_BYTES:
            sys.exit(f"{f.name} is larger than the 2 GB GitHub release limit.")
    if dry_run:
        print("Dry run — nothing uploaded.")
        return
    if _gh("release", "view", TAG, check=False).returncode != 0:
        _gh("release", "create", TAG, "--prerelease", "--title", "Data (latest)", "--notes", NOTES)
    _gh("release", "upload", TAG, *[str(f) for f in files], "--clobber")
    print(f"Uploaded {len(files)} files to release {TAG}.")


def restore(require: bool = False) -> None:
    dest = ROOT / "data" / "processed"
    dest.mkdir(parents=True, exist_ok=True)
    r = _gh("release", "download", TAG, "-D", str(dest), "--clobber",
            "-p", ARCHIVE.name, "-p", "dataset.parquet", "-p", "dataset_clean.parquet", check=False)
    if r.returncode != 0 or not ARCHIVE.exists():
        msg = (f"Release {TAG} or its cache archive is missing — bootstrap it from the laptop with "
               "`python scripts/publish_data.py publish`.")
        if require:
            sys.exit(msg)
        print(msg)
        return
    extract_archive(ARCHIVE)
    print(f"Restored {', '.join(CACHE_DIRS)} and the dataset from release {TAG}.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("publish"); s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("restore"); s.add_argument("--require", action="store_true", help="fail if the release is missing")
    a = p.parse_args()
    publish(a.dry_run) if a.cmd == "publish" else restore(a.require)


if __name__ == "__main__":
    main()
