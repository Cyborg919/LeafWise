"""Owner-scoped diagnosis history with SQLite local mode and managed MySQL mode."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import certifi
from sqlalchemy import Boolean, Column, Float, MetaData, String, Table, Text, create_engine, delete, insert, select, update
from sqlalchemy.engine import Engine, make_url

metadata = MetaData()
history = Table(
    "leafwise_history",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("owner_hash", String(64), nullable=False, index=True),
    Column("created_at", String(40), nullable=False),
    Column("label", String(160), nullable=False),
    Column("score", Float, nullable=False),
    Column("predictions_json", Text, nullable=False),
    Column("image_key", String(512), nullable=True),
    Column("is_deleted", Boolean, nullable=False, default=False),
)


def owner_hash(client_token: str) -> str:
    return hashlib.sha256(client_token.encode("utf-8")).hexdigest()


def _database_url_and_options(database_url: str):
    url = make_url(database_url)
    if url.drivername == "mysql":
        url = url.set(drivername="mysql+pymysql")
    connect_args: dict[str, Any] = {}
    if url.drivername == "mysql+pymysql" and "ssl" in url.query:
        query = dict(url.query)
        ssl_json = query.pop("ssl")
        try:
            ssl_config = json.loads(ssl_json) if isinstance(ssl_json, str) else ssl_json
        except (TypeError, ValueError) as exc:
            raise ValueError("Managed database TLS configuration is invalid.") from exc
        if not isinstance(ssl_config, dict):
            raise ValueError("Managed database TLS configuration is invalid.")
        verify = ssl_config.get("rejectUnauthorized", True)
        if not isinstance(verify, bool):
            raise ValueError("Managed database TLS verification setting is invalid.")
        tls: dict[str, Any] = {
            "verify_mode": "required" if verify else "none",
            "check_hostname": verify,
        }
        if verify:
            tls["ca"] = certifi.where()
        connect_args["ssl"] = tls
        url = url.set(query=query)
    return url, connect_args


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    force_local = os.getenv("LEAFWISE_FORCE_SQLITE") == "1"
    database_url = None if force_local else os.getenv("DATABASE_URL")
    if database_url:
        url, connect_args = _database_url_and_options(database_url)
        return create_engine(url, connect_args=connect_args, pool_pre_ping=True, pool_recycle=300, future=True)
    data_dir = Path(os.getenv("LEAFWISE_DATA_DIR", Path.home() / ".leafwise"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{data_dir / 'leafwise.db'}", connect_args={"check_same_thread": False}, future=True)


def ensure_schema() -> None:
    metadata.create_all(get_engine())


def create_record(record_id: str, token_hash: str, label: str, score: float, predictions: list[dict[str, Any]], image_key: str | None) -> dict[str, Any]:
    created = datetime.now(timezone.utc).isoformat()
    with get_engine().begin() as connection:
        connection.execute(insert(history).values(
            id=record_id,
            owner_hash=token_hash,
            created_at=created,
            label=label,
            score=score,
            predictions_json=json.dumps(predictions, ensure_ascii=False, separators=(",", ":")),
            image_key=image_key,
            is_deleted=False,
        ))
    return {"id": record_id, "created_at": created, "label": label, "score": score, "predictions": predictions, "image_key": image_key}


def list_records(token_hash: str, limit: int = 30) -> list[dict[str, Any]]:
    with get_engine().connect() as connection:
        rows = connection.execute(
            select(history)
            .where(history.c.owner_hash == token_hash, history.c.is_deleted.is_(False))
            .order_by(history.c.created_at.desc())
            .limit(limit)
        ).mappings().all()
    return [{
        "id": row["id"],
        "created_at": row["created_at"],
        "label": row["label"],
        "score": row["score"],
        "predictions": json.loads(row["predictions_json"]),
        "image_key": row["image_key"],
    } for row in rows]


def get_record(token_hash: str, record_id: str) -> dict[str, Any] | None:
    with get_engine().connect() as connection:
        row = connection.execute(select(history).where(
            history.c.id == record_id,
            history.c.owner_hash == token_hash,
            history.c.is_deleted.is_(False),
        )).mappings().first()
    return dict(row) if row is not None else None


def soft_remove_record(token_hash: str, record_id: str) -> bool:
    """Hide a row while preserving its key for owner-side managed-object cleanup."""
    with get_engine().begin() as connection:
        result = connection.execute(update(history).where(
            history.c.id == record_id,
            history.c.owner_hash == token_hash,
            history.c.is_deleted.is_(False),
        ).values(is_deleted=True))
    return bool(result.rowcount)


def remove_record(token_hash: str, record_id: str) -> bool:
    """Hard-delete a local history row after its local photo has been deleted."""
    with get_engine().begin() as connection:
        result = connection.execute(delete(history).where(
            history.c.id == record_id,
            history.c.owner_hash == token_hash,
            history.c.is_deleted.is_(False),
        ))
    return bool(result.rowcount)
