"""Offline, source-linked treatment guidance."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .inference import LABELS_PATH, SHARED

GUIDE_PATH = SHARED / "treatment_advice.json"


@lru_cache(maxsize=1)
def load_guide() -> dict[str, dict[str, Any]]:
    try:
        guide = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
        labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not load the bundled model labels or care guide.") from exc
    if set(guide) != set(labels):
        raise RuntimeError("Treatment guidance does not match the model's 38 classes.")
    for label, entry in guide.items():
        required = ("summary", "one_method", "immediate_steps", "prevention", "caution", "references")
        if any(key not in entry for key in required) or not entry["one_method"].strip():
            raise RuntimeError(f"Care guidance is incomplete for {label}.")
    return guide


def class_details(label: str) -> dict[str, Any]:
    from .inference import display_label, split_label

    crop, disease = split_label(label)
    entry = load_guide()[label]
    return {
        "label": label,
        "crop": crop,
        "disease": disease,
        "display_name": display_label(label),
        "healthy": disease.lower() == "healthy",
        "summary": entry["summary"],
        "one_method": entry["one_method"],
        "immediate_steps": entry["immediate_steps"],
        "prevention": entry["prevention"],
        "caution": entry["caution"],
        "references": entry["references"],
    }
