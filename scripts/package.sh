#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/dist/leafwise-fullstack.zip}"
mkdir -p "$(dirname "$DEST")"
python3 - "$ROOT" "$DEST" <<'PY'
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import json
import sys

root = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
apk = root / "android/app/build/outputs/apk/debug/app-debug.apk"
labels = json.loads((root / "shared/class_names.json").read_text(encoding="utf-8"))
advice = json.loads((root / "shared/treatment_advice.json").read_text(encoding="utf-8"))
if len(labels) != 38 or len(set(labels)) != 38 or set(advice) != set(labels):
    raise SystemExit("The shared classifier labels and treatment guide do not match all 38 classes.")
excluded_parts = {".git", ".venv", "__pycache__", ".pytest_cache", ".gradle", ".kotlin", "node_modules", "dist", "build"}
excluded_names = {"local.properties"}
excluded_suffixes = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3"}

def allowed(path: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in excluded_parts for part in rel.parts):
        return False
    if rel.name in excluded_names or path.suffix in excluded_suffixes:
        return False
    if rel.name == ".env" or rel.name.startswith(".env."):
        return False
    if rel.suffix.lower() == ".apk":
        return False
    return True

if apk.is_file():
    with ZipFile(apk) as android_apk:
        apk_names = set(android_apk.namelist())
        required_assets = {
            "assets/crop_disease.onnx",
            "assets/class_names.json",
            "assets/treatment_advice.json",
            "assets/index.html",
            "assets/app.js",
            "assets/styles.css",
        }
        missing_assets = sorted(required_assets - apk_names)
        if missing_assets:
            raise SystemExit(f"The Android APK is missing required assets: {missing_assets}")
        for filename in ("crop_disease.onnx", "class_names.json", "treatment_advice.json"):
            if android_apk.read(f"assets/{filename}") != (root / "shared" / filename).read_bytes():
                raise SystemExit(f"The APK's {filename} does not match the shared source asset.")
        if not any(name.startswith("lib/") and name.endswith(".so") and "onnxruntime" in name for name in apk_names):
            raise SystemExit("The Android APK is missing ONNX Runtime native libraries.")

with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=7) as archive:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.resolve() == destination or not allowed(path):
            continue
        archive.write(path, path.relative_to(root).as_posix())
    if apk.is_file():
        archive.write(apk, "artifacts/leafwise-debug.apk")
    bad = archive.testzip()
    if bad:
        raise SystemExit(f"ZIP CRC verification failed: {bad}")
print(f"Created {destination}")
print("Included debug APK" if apk.is_file() else "APK not included (Android build has not produced one)")
PY
