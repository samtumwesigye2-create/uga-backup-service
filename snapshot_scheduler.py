"""Automatic daily snapshots with retention and integrity verification."""
import hashlib,json,os,threading,time
from datetime import datetime,timezone
from database import SessionLocal
from models import BackupRecord,Snapshot,SyncLog
SNAPSHOT_INTERVAL_SECONDS=max(3600,int(os.environ.get("SNAPSHOT_INTERVAL_SECONDS","86400")))
SNAPSHOT_RETENTION=max(7,int(os.environ.get("SNAPSHOT_RETENTION","30")))
_started=False;_lock=threading.Lock()
def _checksum(data):return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def _prune(db,source):
 old=db.query(Snapshot).filter(Snapshot.source==source).order_by(Snapshot.created_at.desc()).offset(SNAPSHOT_RETENTION).all()
 for s in old:db.delete(s)
 if old:db.add(SyncLog(action="snapshot_prune",source=source,detail=f"Removed {len(old)} old snapshots; retention={SNAPSHOT_RETENTION}"))
def _verify_latest(db,source):
 snap=db.query(Snapshot).filter(Snapshot.source==source).order_by(Snapshot.created_at.desc()).first()
 if not snap:return True
 actual=_checksum(snap.data)
 if actual!=snap.checksum:
  db.add(SyncLog(action="snapshot_integrity_failed",source=source,detail=f"snapshot={snap.id} expected={snap.checksum} actual={actual}"));return False
 db.add(SyncLog(action="snapshot_integrity_ok",source=source,detail=f"snapshot={snap.id} checksum={actual}"));return True
def _create_snapshot_for(source):
 db=SessionLocal()
 try:
  records=db.query(BackupRecord).filter(BackupRecord.source==source).order_by(BackupRecord.source,BackupRecord.entity_type,BackupRecord.entity_id).all()
  dump=[{"source":r.source,"entity_type":r.entity_type,"entity_id":r.entity_id,"data":r.data,"is_deleted":bool(r.is_deleted),"source_updated_at":r.source_updated_at.isoformat() if r.source_updated_at else None} for r in records]
  checksum=_checksum(dump);latest=db.query(Snapshot).filter(Snapshot.source==source).order_by(Snapshot.created_at.desc()).first()
  if latest and latest.checksum==checksum:
   _verify_latest(db,source);_prune(db,source);db.add(SyncLog(action="snapshot_skipped",source=source,detail="No data changes since previous snapshot"));db.commit();return
  label=datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S");snap=Snapshot(label=label,source=source,checksum=checksum,data=dump);db.add(snap);db.flush();_verify_latest(db,source);_prune(db,source);db.add(SyncLog(action="snapshot_auto",source=source,detail=f"{label}: {len(dump)} records sha256={checksum}"));db.commit()
 except Exception as exc:
  db.rollback()
  try:db.add(SyncLog(action="snapshot_failed",source=source,detail=f"{type(exc).__name__}: {exc}"[:1000]));db.commit()
  except Exception:pass
 finally:db.close()
def _worker():
 time.sleep(60)
 while True:
  _create_snapshot_for("UGAMAP");_create_snapshot_for("UGASHIP");time.sleep(SNAPSHOT_INTERVAL_SECONDS)
def start_snapshot_scheduler():
 global _started
 with _lock:
  if _started:return
  _started=True;threading.Thread(target=_worker,name="uga-backup-snapshot",daemon=True).start()
