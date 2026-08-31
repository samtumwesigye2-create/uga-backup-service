"""Automatic daily snapshots for the independent backup database."""
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone

from database import SessionLocal
from models import BackupRecord, Snapshot, SyncLog

SNAPSHOT_INTERVAL_SECONDS=max(3600,int(os.environ.get("SNAPSHOT_INTERVAL_SECONDS","86400")))
_started=False
_lock=threading.Lock()


def _create_snapshot_for(source):
    db=SessionLocal()
    try:
        q=db.query(BackupRecord)
        if source:q=q.filter(BackupRecord.source==source)
        records=q.order_by(BackupRecord.source,BackupRecord.entity_type,BackupRecord.entity_id).all()
        dump=[{"source":r.source,"entity_type":r.entity_type,"entity_id":r.entity_id,"data":r.data,"is_deleted":bool(r.is_deleted),"source_updated_at":r.source_updated_at.isoformat() if r.source_updated_at else None} for r in records]
        canonical=json.dumps(dump,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
        checksum=hashlib.sha256(canonical).hexdigest()
        latest=db.query(Snapshot).filter(Snapshot.source==source).order_by(Snapshot.created_at.desc()).first()
        if latest and latest.checksum==checksum:
            db.add(SyncLog(action="snapshot_skipped",source=source,detail="No data changes since previous snapshot"));db.commit();return
        label=datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        db.add(Snapshot(label=label,source=source,checksum=checksum,data=dump))
        db.add(SyncLog(action="snapshot_auto",source=source,detail=f"{label}: {len(dump)} records sha256={checksum}"))
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            db.add(SyncLog(action="snapshot_failed",source=source,detail=f"{type(exc).__name__}: {exc}"[:1000]));db.commit()
        except Exception:pass
    finally:db.close()


def _worker():
    time.sleep(60)
    while True:
        _create_snapshot_for("UGAMAP")
        _create_snapshot_for("UGASHIP")
        time.sleep(SNAPSHOT_INTERVAL_SECONDS)


def start_snapshot_scheduler():
    global _started
    with _lock:
        if _started:return
        _started=True
        threading.Thread(target=_worker,name="uga-backup-snapshot",daemon=True).start()
