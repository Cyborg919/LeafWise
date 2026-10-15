"""Shared ONNX inference using the original validated PlantVillage preprocessing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
MODEL_PATH = SHARED / "crop_disease.onnx"
LABELS_PATH = SHARED / "class_names.json"
IMAGE_SIZE = 96
RESIZE_SHORT_EDGE = 112
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def preprocess_image(image: Image.Image) -> np.ndarray:
    """Apply EXIF orientation and the exact train-time 112-resize/96-crop transform."""
    if not isinstance(image, Image.Image):
        raise TypeError("Expected a decoded image.")
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    if width < 1 or height < 1:
        raise ValueError("Image has invalid dimensions.")
    if width <= height:
        resized = (RESIZE_SHORT_EDGE, max(RESIZE_SHORT_EDGE, int(RESIZE_SHORT_EDGE * height / width)))
    else:
        resized = (max(RESIZE_SHORT_EDGE, int(RESIZE_SHORT_EDGE * width / height)), RESIZE_SHORT_EDGE)
    image = image.resize(resized, resample=Image.Resampling.BILINEAR)
    left, top = (resized[0] - IMAGE_SIZE) // 2, (resized[1] - IMAGE_SIZE) // 2
    image = image.crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE))
    array = np.asarray(image, dtype=np.float32) / 255.0
    array = (array - MEAN) / STD
    return np.ascontiguousarray(array.transpose(2, 0, 1)[None], dtype=np.float32)


def split_label(label: str) -> tuple[str, str]:
    crop, separator, disease = label.partition("___")
    if not separator:
        return label.replace("_", " "), ""
    return crop.replace("_", " "), disease.replace("_", " ").strip()


def display_label(label: str) -> str:
    crop, disease = split_label(label)
    return f"{crop} — {disease}" if disease else crop


class PlantDiseaseClassifier:
    """Run the bundled ONNX model on CPU and return ranked (label, score) pairs."""

    def __init__(self, model_path: str | Path = MODEL_PATH, labels_path: str | Path = LABELS_PATH, session: Any | None = None):
        try:
            labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not load model labels from {labels_path}") from exc
        if not isinstance(labels, list) or len(labels) != 38 or len(set(labels)) != len(labels):
            raise RuntimeError("The model requires the exact 38 unique labels in class_names.json.")
        self.labels: list[str] = labels
        if session is None:
            try:
                import onnxruntime as ort
            except ImportError as exc:
                raise RuntimeError("Install ONNX Runtime with pip install onnxruntime.") from exc
            if not Path(model_path).is_file():
                raise FileNotFoundError(f"Bundled ONNX model is missing: {model_path}")
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        inputs, outputs = session.get_inputs(), session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise RuntimeError("Expected one model input and one output.")
        if len(inputs[0].shape) != 4 or inputs[0].shape[1:] != [3, IMAGE_SIZE, IMAGE_SIZE]:
            raise RuntimeError(f"Unexpected ONNX input shape: {inputs[0].shape}")
        if len(outputs[0].shape) != 2 or outputs[0].shape[-1] != len(self.labels):
            raise RuntimeError("The ONNX output count does not match the 38 class labels.")
        self.session = session
        self.input_name = inputs[0].name
        self.output_name = outputs[0].name

    def predict(self, image: Image.Image, top_k: int = 3) -> list[tuple[str, float]]:
        if not 1 <= top_k <= 5:
            raise ValueError("top_k must be between 1 and 5.")
        tensor = preprocess_image(image)
        logits = np.asarray(self.session.run([self.output_name], {self.input_name: tensor})[0])
        if logits.shape != (1, len(self.labels)) or not np.isfinite(logits).all():
            raise RuntimeError("The model returned invalid scores.")
        values = logits[0].astype(np.float64)
        values -= values.max()
        probabilities = np.exp(values)
        probabilities /= probabilities.sum()
        indices = np.argsort(probabilities)[::-1][:top_k]
        return [(self.labels[int(i)], float(probabilities[int(i)])) for i in indices]


classifier = PlantDiseaseClassifier()
