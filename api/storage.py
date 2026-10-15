"""Opt-in diagnosis image storage: documented managed presigned objects or removable local files."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from urllib.parse import urljoin

import requests

KEY_PATTERN = re.compile(r"^leafwise/[a-f0-9]{20}/[a-f0-9-]{36}\.jpg$")


class StorageError(RuntimeError):
    pass


def _managed_config() -> tuple[str, str] | None:
    base, key = os.getenv("MANUS_API_URL"), os.getenv("MANUS_API_KEY")
    return (base.rstrip("/"), key) if base and key else None


def is_managed() -> bool:
    return _managed_config() is not None


def new_image_key(owner_hash: str) -> str:
    return f"leafwise/{owner_hash[:20]}/{uuid.uuid4()}.jpg"


def _local_root() -> Path:
    root = Path(os.getenv("LEAFWISE_DATA_DIR", Path.home() / ".leafwise")) / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validate_key(key: str) -> None:
    if not KEY_PATTERN.fullmatch(key):
        raise StorageError("Invalid stored-image reference.")


def _presign(method: str, key: str) -> str:
    if method not in {"put", "get"}:
        raise StorageError("Unsupported storage operation.")
    config = _managed_config()
    if not config:
        raise StorageError("Managed file storage is not configured.")
    base, api_key = config
    try:
        response = requests.get(
            urljoin(base + "/", f"v1/storage/presign/{method}"),
            params={"path": key},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        url = payload.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise StorageError("The managed file-storage service returned no usable signed URL.")
        return url
    except (requests.RequestException, ValueError) as exc:
        raise StorageError("Managed file storage is temporarily unavailable.") from exc


def save_image(image_bytes: bytes, key: str) -> None:
    """Save bytes using a server-created key; never incorporate a client filename."""
    _validate_key(key)
    config = _managed_config()
    if config:
        signed = _presign("put", key)
        try:
            response = requests.put(signed, data=image_bytes, headers={"Content-Type": "image/jpeg"}, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise StorageError("Could not save the photo to project storage.") from exc
        return
    path = (_local_root() / key).resolve()
    if not path.is_relative_to(_local_root().resolve()):
        raise StorageError("Invalid local photo reference.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(image_bytes)
    except OSError as exc:
        raise StorageError("Could not save the photo to local storage.") from exc


def read_image(key: str) -> bytes:
    _validate_key(key)
    if is_managed():
        signed = _presign("get", key)
        try:
            response = requests.get(signed, timeout=30)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            raise StorageError("Could not retrieve the saved photo.") from exc
    root = _local_root().resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise StorageError("Invalid local photo reference.")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise StorageError("The saved photo is unavailable.") from exc


def delete_image(key: str) -> None:
    """Physically delete only local uploads; managed runtime storage has no delete API."""
    if not key:
        return
    _validate_key(key)
    if is_managed():
        raise StorageError("Project storage does not provide a runtime delete operation.")
    root = _local_root().resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise StorageError("Invalid local photo reference.")
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise StorageError("Could not remove the saved photo; the history entry was kept.") from exc
