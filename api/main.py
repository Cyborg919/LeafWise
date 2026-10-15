"""Leafwise self-hosted API. Predictions use the bundled ONNX model, never an external AI API."""
from __future__ import annotations

import io
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from . import database, storage
from .guidance import class_details
from .inference import ROOT, classifier, display_label

WEB_DIR = ROOT / "web"
SHARED_DIR = ROOT / "shared"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
TOKEN_RE = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}
RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 60
_rate_state: dict[str, list[float]] = {}
_rate_lock = Lock()
logger = logging.getLogger("leafwise")
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def _client_hash(token: str | None) -> str:
    if not token or not TOKEN_RE.fullmatch(token):
        raise HTTPException(status_code=401, detail="A valid per-device history token is required for saved records.")
    return database.owner_hash(token)


def _rate_check(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
        calls = [stamp for stamp in _rate_state.get(ip, []) if now - stamp < RATE_WINDOW_SECONDS]
        if len(calls) >= RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Too many image requests. Please wait a minute and try again.")
        calls.append(now)
        _rate_state[ip] = calls
        if len(_rate_state) > 1000:
            for old_ip in list(_rate_state)[:200]:
                _rate_state.pop(old_ip, None)


def _decode_image(raw: bytes) -> tuple[Image.Image, str]:
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            image_format = (opened.format or "").upper()
            if image_format not in ALLOWED_FORMATS:
                raise HTTPException(status_code=415, detail="Use a JPEG, PNG, WebP, or BMP leaf photo.")
            if opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="This image is too large to process safely.")
            opened.verify()
        with Image.open(io.BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened)
            if image is None:
                raise HTTPException(status_code=400, detail="The photo orientation could not be read.")
            image = image.convert("RGB")
            image.load()
        return image, image_format
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(status_code=400, detail="The file is not a valid, readable photo.") from exc


def _jpeg_for_storage(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=88, optimize=True)
    return output.getvalue()


def _prediction_payload(raw_predictions: list[tuple[str, float]]) -> list[dict[str, Any]]:
    results = []
    for label, score in raw_predictions:
        crop, _, disease = label.partition("___")
        parts = class_details(label)
        results.append({
            "label": label,
            "crop": crop.replace("_", " "),
            "disease": disease.replace("_", " ").strip(),
            "display_name": display_label(label),
            "score": score,
            "healthy": parts["healthy"],
        })
    return results


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await run_in_threadpool(database.ensure_schema)
        app.state.history_ready = True
    except Exception:
        # Prediction still works even if an optional database is unavailable.
        logger.warning("Diagnosis history is unavailable; image prediction remains enabled.")
        app.state.history_ready = False
    yield


app = FastAPI(
    title="Leafwise Plant Health API",
    description=(
        "Free, self-hostable API for the bundled 38-class ONNX plant model. "
        "No paid third-party inference API is used. Uploads are processed in memory unless save_to_history is enabled. "
        "Managed photo removal hides the history record; the managed runtime storage API does not erase objects."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.middleware("http")
async def prevent_private_api_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/api/predict" or request.url.path.startswith("/api/history"):
        response.headers["Cache-Control"] = "private, no-store"
    return response


app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/manus-routes.json", include_in_schema=False)
def route_manifest() -> FileResponse:
    return FileResponse(WEB_DIR / "manus-routes.json", media_type="application/json")


@app.get("/_app/health", include_in_schema=False)
@app.get("/api/health", tags=["system"])
def health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "model_ready": True,
        "class_count": len(classifier.labels),
        "history_ready": bool(getattr(request.app.state, "history_ready", False)),
        "managed_image_storage": storage.is_managed(),
        "prediction_api": "self-hosted ONNX Runtime; no third-party inference API",
    }


@app.get("/api/model", tags=["model"])
def model_info() -> dict[str, Any]:
    try:
        metrics = json.loads((SHARED_DIR / "model_metrics.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metrics = {}
    return {
        "name": "Leafwise 38-class PlantVillage ONNX classifier",
        "runtime": "ONNX Runtime CPU",
        "classes": len(classifier.labels),
        "metrics": metrics,
        "limitations": [
            "Closed-set classifier: it always ranks one of its 38 supported labels.",
            "Not a general plant-species identifier and not a confirmed diagnosis.",
            "Real field photos may differ from the images used to validate the model.",
            "The original training and validation images are not included in this project."
        ],
    }


@app.get("/api/classes", tags=["model"])
def classes() -> dict[str, Any]:
    return {"count": len(classifier.labels), "classes": [class_details(label) for label in classifier.labels]}


@app.get("/api/care/{label}", tags=["care"])
def care_for_class(label: str) -> dict[str, Any]:
    if label not in classifier.labels:
        raise HTTPException(status_code=404, detail="This label is not supported by the bundled model.")
    return class_details(label)


@app.post("/api/predict", tags=["inference"])
async def predict(
    request: Request,
    image: UploadFile = File(..., description="A clear JPEG, PNG, WebP, or BMP leaf photo (10 MiB maximum)."),
    top_k: int = Form(3, ge=1, le=5),
    save_to_history: bool = Form(False),
    x_client_token: str | None = Header(default=None, alias="X-Client-Token"),
) -> dict[str, Any]:
    _rate_check(request)
    raw = await image.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="Choose a photo before analyzing.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Photo must be 10 MiB or smaller.")
    photo, _ = _decode_image(raw)
    raw_predictions = await run_in_threadpool(classifier.predict, photo, top_k)
    predictions = _prediction_payload(raw_predictions)
    primary = predictions[0]
    care = class_details(primary["label"])
    response: dict[str, Any] = {
        "primary": primary,
        "predictions": predictions,
        "care": care,
        "saved": False,
        "history_id": None,
        "image_saved": False,
        "notice": "Model scores rank the supported classes; they are not probabilities or a confirmed diagnosis.",
    }
    if save_to_history:
        if not getattr(request.app.state, "history_ready", False):
            raise HTTPException(status_code=503, detail="History storage is temporarily unavailable. The photo was not saved.")
        token_hash = _client_hash(x_client_token)
        record_id = str(uuid.uuid4())
        image_key = storage.new_image_key(token_hash)
        try:
            photo_bytes = await run_in_threadpool(_jpeg_for_storage, photo)
            await run_in_threadpool(
                database.create_record,
                record_id,
                token_hash,
                primary["label"],
                primary["score"],
                predictions,
                image_key,
            )
        except Exception as exc:
            logger.warning("Could not save optional diagnosis history.")
            raise HTTPException(status_code=503, detail="Could not create the saved report. The photo was not uploaded.") from exc
        try:
            await run_in_threadpool(storage.save_image, photo_bytes, image_key)
        except Exception as exc:
            if storage.is_managed():
                await run_in_threadpool(database.soft_remove_record, token_hash, record_id)
                detail = "The project-storage upload could not be confirmed. No report is visible, but a photo object may remain in project storage and require owner cleanup."
            else:
                try:
                    await run_in_threadpool(storage.delete_image, image_key)
                    await run_in_threadpool(database.remove_record, token_hash, record_id)
                except Exception:
                    logger.warning("Could not clean up a failed local photo save.")
                detail = "Could not save the photo locally; the report was not added to history."
            logger.warning("Could not complete optional photo storage.")
            raise HTTPException(status_code=503, detail=detail) from exc
        response.update({"saved": True, "history_id": record_id, "image_saved": True})
    return response


def _history_response(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "created_at": item["created_at"],
        "label": item["label"],
        "display_name": display_label(item["label"]),
        "score": item["score"],
        "predictions": item["predictions"],
        "care": class_details(item["label"]),
        "image_available": bool(item.get("image_key")),
    }


@app.get("/api/history", tags=["history"])
async def get_history(request: Request, x_client_token: str | None = Header(default=None, alias="X-Client-Token")) -> dict[str, Any]:
    if not getattr(request.app.state, "history_ready", False):
        raise HTTPException(status_code=503, detail="History storage is not configured.")
    token_hash = _client_hash(x_client_token)
    items = await run_in_threadpool(database.list_records, token_hash, 30)
    return {"items": [_history_response(item) for item in items]}


@app.get("/api/history/{record_id}/image", tags=["history"], response_class=Response)
async def get_history_image(
    request: Request,
    record_id: str,
    x_client_token: str | None = Header(default=None, alias="X-Client-Token"),
) -> Response:
    if not getattr(request.app.state, "history_ready", False):
        raise HTTPException(status_code=503, detail="History storage is not configured.")
    token_hash = _client_hash(x_client_token)
    item = await run_in_threadpool(database.get_record, token_hash, record_id)
    if item is None or not item.get("image_key"):
        raise HTTPException(status_code=404, detail="Saved photo not found.")
    try:
        data = await run_in_threadpool(storage.read_image, item["image_key"])
    except storage.StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@app.delete("/api/history/{record_id}", tags=["history"])
async def delete_history(
    request: Request,
    record_id: str,
    x_client_token: str | None = Header(default=None, alias="X-Client-Token"),
) -> dict[str, bool]:
    if not getattr(request.app.state, "history_ready", False):
        raise HTTPException(status_code=503, detail="History storage is not configured.")
    token_hash = _client_hash(x_client_token)
    item = await run_in_threadpool(database.get_record, token_hash, record_id)
    if item is None:
        raise HTTPException(status_code=404, detail="History entry not found.")
    if item.get("image_key") and storage.is_managed():
        removed = await run_in_threadpool(database.soft_remove_record, token_hash, record_id)
        if not removed:
            raise HTTPException(status_code=404, detail="History entry not found.")
        return {"deleted": True, "history_hidden": True, "photo_removed": False}
    if item.get("image_key"):
        try:
            await run_in_threadpool(storage.delete_image, item["image_key"])
        except storage.StorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    removed = await run_in_threadpool(database.remove_record, token_hash, record_id)
    if not removed:
        raise HTTPException(status_code=404, detail="History entry not found.")
    return {"deleted": True, "history_hidden": True, "photo_removed": True}
