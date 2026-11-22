"""The data-cache archive must round-trip and never write outside data/."""

import importlib.util
import tarfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "publish_data", Path(__file__).resolve().parents[1] / "scripts" / "publish_data.py")
publish_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish_data)


def test_archive_round_trip(tmp_path):
    src = tmp_path / "src"
    (src / "data" / "raw" / "entsoe").mkdir(parents=True)
    (src / "data" / "raw" / "entsoe" / "price_BE.parquet").write_bytes(b"x")
    (src / "data" / "raw" / ".gitkeep").write_text("")
    (src / "data" / "external").mkdir(parents=True)
    (src / "data" / "external" / "eua_prices.csv").write_text("date,price\n")

    archive = publish_data.build_archive(src, tmp_path / "cache.tar.gz")
    names = tarfile.open(archive).getnames()
    assert "data/raw/entsoe/price_BE.parquet" in names
    assert not any(n.endswith(".gitkeep") for n in names)

    dst = tmp_path / "dst"
    publish_data.extract_archive(archive, dst)
    assert (dst / "data" / "raw" / "entsoe" / "price_BE.parquet").read_bytes() == b"x"
    assert (dst / "data" / "external" / "eua_prices.csv").exists()


def test_extract_ignores_paths_outside_data(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("pwned")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(payload, arcname="src/energy_forecast/evil.py")
        tar.add(payload, arcname="data/raw/ok.txt")
    dst = tmp_path / "dst"
    publish_data.extract_archive(evil, dst)
    assert (dst / "data" / "raw" / "ok.txt").exists()
    assert not (dst / "src").exists()
