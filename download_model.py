"""
One-time downloader for the Vosk English speech model.

Downloads vosk-model-small-en-us-0.15 (~40 MB) and extracts it into ./models/.
Uses only the Python standard library. Safe to re-run: it skips the download if
the model folder is already present.
"""

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
MODEL_DIR = MODELS_DIR / MODEL_NAME
ZIP_PATH = MODELS_DIR / f"{MODEL_NAME}.zip"


def _progress(count: int, block_size: int, total_size: int) -> None:
    if total_size <= 0:
        return
    done = min(count * block_size, total_size)
    pct = done * 100 // total_size
    mb = done / (1024 * 1024)
    total_mb = total_size / (1024 * 1024)
    sys.stdout.write(f"\r  downloading... {pct:3d}%  ({mb:5.1f} / {total_mb:.1f} MB)")
    sys.stdout.flush()


def main() -> None:
    if MODEL_DIR.exists():
        print(f"[ok] Model already present: {MODEL_DIR}")
        return

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[download] {MODEL_URL}")
    try:
        urllib.request.urlretrieve(MODEL_URL, ZIP_PATH, _progress)
        print()
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"\n[error] Download failed: {exc}")

    print("[extract] unpacking...")
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        zf.extractall(MODELS_DIR)

    ZIP_PATH.unlink(missing_ok=True)

    if MODEL_DIR.exists():
        print(f"[done] Model ready: {MODEL_DIR}")
    else:
        # Some archives may extract under a different top folder; report what we got.
        extracted = [p.name for p in MODELS_DIR.iterdir() if p.is_dir()]
        print(f"[warn] Expected {MODEL_NAME} but found: {extracted}")
        print("       Update 'model_path' in config.json to match.")


if __name__ == "__main__":
    main()
