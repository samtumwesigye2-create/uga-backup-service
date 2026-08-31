import hashlib
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import and_
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import BackupRecord, Snapshot, SyncLog
from schemas import BulkSyncPayload, RestoreRequest, SyncEvent

Base.metadata.create_all(bind=engine)

app = FastAPI(title="UGA Backup Service", version="1.0")

SYNC_TOKEN = os.environ.get("BACKUP_SYNC_TOKEN", "").strip()
RESTORE_TOKEN = os.environ.get("BACKUP_RESTORE_TOKEN", "").strip()
RESTORE_TARGET_URLS = {
    "UGAMAP": os.environ.get("UGAMAP_RESTORE_URL"),
    "UGASHIP": os.environ.get("UGASHIP_RESTORE_URL"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_configured_token(value: str, name: str):
    if not value:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")


def verify_sync_token(x_backup_token: str = Header(...)):
    _require_configured_token(SYNC_TOKEN, "BACKUP_SYNC_TOKEN")
    if x_backup_token != SYNC_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid backup sync token")


def verify_restore_token(x_backup_restore_token: str = Header(...)):
    _require_configured_token(RESTORE_TOKEN, "BACKUP_RESTORE_TOKEN")
    if x_backup_restore_token != RESTORE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid backup restore token")


def _normalize_target(source: str, override: str | None) -> str | None:
    configured = RESTORE_TARGET_URLS.get(source)
    if override:
        if not configured or override.rstrip("/") != configured.rstrip("/"):
            raise HTTPException(status_code=400, detail="Restore target must match the configured destination")
    target = override or configured
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Restore target must use HTTPS")
    return target


@app.get("/health")
def health():
    return {"status": "ok", "service": "UGA Backup Service", "time": _now_iso()}


@app.post("/sync", dependencies=[Depends(verify_sync_token)])
def sync_event(event: SyncEvent, db: Session = Depends(get_db)):
    existing = db.query(BackupRecord).filter(
        and_(
            BackupRecord.source == event.source,
            BackupRecord.entity_type == event.entity_type,
            BackupRecord.entity_id == event.entity_id,
        )
    ).first()

    if existing and event.source_updated_at and existing.source_updated_at:
        if event.source_updated_at < existing.source_updated_at:
            return {"status": "ignored_stale", "entity_id": event.entity_id}

    if event.action == "delete":
        if existing:
            existing.is_deleted = 1
            existing.source_updated_at = event.source_updated_at
        else:
            db.add(BackupRecord(
                source=event.source,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                data=event.data,
                is_deleted=1,
                source_updated_at=event.source_updated_at,
            ))
        db.add(SyncLog(action="delete", source=event.source, detail=f"{event.entity_type}:{event.entity_id}"))
        db.commit()
        return {"status": "deleted", "entity_id": event.entity_id}

    if existing:
        existing.data = event.data
        existing.is_deleted = 0
        existing.source_updated_at = event.source_updated_at
    else:
        db.add(BackupRecord(
            source=event.source,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            data=event.data,
            source_updated_at=event.source_updated_at,
        ))

    db.add(SyncLog(action="sync", source=event.source, detail=f"{event.entity_type}:{event.entity_id}"))
    db.commit()
    return {"status": "synced", "entity_id": event.entity_id}


@app.post("/sync/bulk", dependencies=[Depends(verify_sync_token)])
def sync_bulk(payload: BulkSyncPayload, db: Session = Depends(get_db)):
    synced = 0
    skipped = 0
    for record in payload.records:
        raw_id = record.get("id", record.get("entity_id"))
        if raw_id is None:
            skipped += 1
            continue
        entity_id = str(raw_id).strip()
        if not entity_id:
            skipped += 1
            continue

        existing = db.query(BackupRecord).filter(
            and_(
                BackupRecord.source == payload.source,
                BackupRecord.entity_type == payload.entity_type,
                BackupRecord.entity_id == entity_id,
            )
        ).first()
        if existing:
            existing.data = record
            existing.is_deleted = 0
        else:
            db.add(BackupRecord(
                source=payload.source,
                entity_type=payload.entity_type,
                entity_id=entity_id,
                data=record,
            ))
        synced += 1

    db.add(SyncLog(
        action="bulk_sync",
        source=payload.source,
        detail=f"{payload.entity_type}: {synced} records, {skipped} skipped",
    ))
    db.commit()
    return {"status": "ok", "synced": synced, "skipped": skipped}


@app.get("/records", dependencies=[Depends(verify_restore_token)])
def list_records(
    source: str = Query(..., pattern="^(UGAMAP|UGASHIP)$"),
    entity_type: str | None = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(BackupRecord).filter(BackupRecord.source == source)
    if not include_deleted:
        q = q.filter(BackupRecord.is_deleted == 0)
    if entity_type:
        q = q.filter(BackupRecord.entity_type == entity_type)
    return [
        {
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "data": r.data,
            "is_deleted": bool(r.is_deleted),
            "source_updated_at": r.source_updated_at,
            "synced_at": r.synced_at,
        }
        for r in q.all()
    ]


@app.post("/snapshot/create", dependencies=[Depends(verify_restore_token)])
def create_snapshot(source: str | None = Query(default=None, pattern="^(UGAMAP|UGASHIP)$"), db: Session = Depends(get_db)):
    q = db.query(BackupRecord)
    if source:
        q = q.filter(BackupRecord.source == source)
    records = q.order_by(BackupRecord.source, BackupRecord.entity_type, BackupRecord.entity_id).all()
    dump = [
        {
            "source": r.source,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "data": r.data,
            "is_deleted": bool(r.is_deleted),
            "source_updated_at": r.source_updated_at.isoformat() if r.source_updated_at else None,
        }
        for r in records
    ]
    canonical = json.dumps(dump, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    checksum = hashlib.sha256(canonical).hexdigest()
    label = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    snap = Snapshot(label=label, source=source, checksum=checksum, data=dump)
    db.add(snap)
    db.add(SyncLog(action="snapshot", source=source, detail=f"{label}: {len(dump)} records sha256={checksum}"))
    db.commit()
    db.refresh(snap)
    return {"status": "ok", "id": snap.id, "label": label, "record_count": len(dump), "checksum": checksum}


@app.get("/snapshot/list", dependencies=[Depends(verify_restore_token)])
def list_snapshots(source: str | None = Query(default=None, pattern="^(UGAMAP|UGASHIP)$"), db: Session = Depends(get_db)):
    q = db.query(Snapshot)
    if source:
        q = q.filter(Snapshot.source == source)
    snaps = q.order_by(Snapshot.created_at.desc()).limit(100).all()
    return [
        {"id": s.id, "label": s.label, "source": s.source, "checksum": s.checksum, "created_at": s.created_at}
        for s in snaps
    ]


@app.get("/snapshot/{snapshot_id}", dependencies=[Depends(verify_restore_token)])
def get_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    snap = db.get(Snapshot, snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {
        "id": snap.id,
        "label": snap.label,
        "source": snap.source,
        "checksum": snap.checksum,
        "created_at": snap.created_at,
        "data": snap.data,
    }


@app.post("/restore", dependencies=[Depends(verify_restore_token)])
async def restore(req: RestoreRequest, db: Session = Depends(get_db)):
    target = _normalize_target(req.source, req.target_url)

    if req.snapshot_id is not None:
        snap = db.get(Snapshot, req.snapshot_id)
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        snapshot_records = snap.data
        selected = [
            item for item in snapshot_records
            if item.get("source") == req.source
            and (not req.entity_type or item.get("entity_type") == req.entity_type)
        ]
        records = [item.get("data", {}) for item in selected if not item.get("is_deleted")]
        source_desc = f"snapshot:{req.snapshot_id}"
    else:
        q = db.query(BackupRecord).filter(BackupRecord.source == req.source, BackupRecord.is_deleted == 0)
        if req.entity_type:
            q = q.filter(BackupRecord.entity_type == req.entity_type)
        records = [r.data for r in q.all()]
        source_desc = "live_backup"

    db.add(SyncLog(
        action="restore_prepare",
        source=req.source,
        detail=f"{source_desc}/{req.entity_type or 'all'}: {len(records)} records -> {target or 'manual'}",
    ))
    db.commit()

    if not target or req.dry_run:
        return {
            "status": "dry_run" if req.dry_run else "no_target_configured",
            "source": req.source,
            "record_count": len(records),
            "records": records,
        }

    restore_push_token = os.environ.get(f"{req.source}_RESTORE_PUSH_TOKEN", "").strip()
    if not restore_push_token:
        raise HTTPException(status_code=503, detail=f"{req.source}_RESTORE_PUSH_TOKEN is not configured")

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                target,
                json={"source": req.source, "entity_type": req.entity_type, "records": records},
                headers={"x-backup-restore-token": restore_push_token},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            db.add(SyncLog(action="restore_failed", source=req.source, detail=str(exc)[:1000]))
            db.commit()
            raise HTTPException(status_code=502, detail="Restore push failed") from exc

    db.add(SyncLog(action="restore_complete", source=req.source, detail=f"{len(records)} records -> {target}"))
    db.commit()
    return {"status": "restored", "record_count": len(records), "target": target}
