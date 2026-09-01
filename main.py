import hashlib,json,os
from datetime import datetime,timezone
from urllib.parse import urlparse
import httpx
from fastapi import Depends,FastAPI,Header,HTTPException,Query
from sqlalchemy import and_,text
from sqlalchemy.orm import Session
from database import Base,engine,get_db,SessionLocal
from models import BackupRecord,Snapshot,SyncLog
from schemas import BulkSyncPayload,RestoreRequest,SyncEvent
from snapshot_scheduler import start_snapshot_scheduler
app=FastAPI(title="UGA Backup Service",version="1.5")
SYNC_TOKEN=os.environ.get("BACKUP_SYNC_TOKEN","").strip();RESTORE_TOKEN=os.environ.get("BACKUP_RESTORE_TOKEN","").strip();RESTORE_TARGET_URLS={"UGAMAP":os.environ.get("UGAMAP_RESTORE_URL"),"UGASHIP":os.environ.get("UGASHIP_RESTORE_URL")};DB_READY=False;DB_ERROR=None
def _now_iso():return datetime.now(timezone.utc).isoformat()
def _checksum(data):return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def _initialize_database():
 global DB_READY,DB_ERROR
 try:
  Base.metadata.create_all(bind=engine)
  with engine.connect() as c:c.execute(text("SELECT 1"))
  DB_READY=True;DB_ERROR=None
 except Exception as e:DB_READY=False;DB_ERROR=f"{type(e).__name__}: {e}"
@app.on_event("startup")
def startup_database_check():
 _initialize_database();start_snapshot_scheduler()
def _require(v,n):
 if not v:raise HTTPException(503,f"{n} is not configured")
def verify_sync_token(x_backup_token:str=Header(...)):
 _require(SYNC_TOKEN,"BACKUP_SYNC_TOKEN")
 if x_backup_token!=SYNC_TOKEN:raise HTTPException(401,"Invalid backup sync token")
def verify_restore_token(x_backup_restore_token:str=Header(...)):
 _require(RESTORE_TOKEN,"BACKUP_RESTORE_TOKEN")
 if x_backup_restore_token!=RESTORE_TOKEN:raise HTTPException(401,"Invalid backup restore token")
def _target(source,override):
 configured=RESTORE_TARGET_URLS.get(source)
 if override and (not configured or override.rstrip("/")!=configured.rstrip("/")):raise HTTPException(400,"Restore target must match the configured destination")
 target=override or configured
 if not target:return None
 p=urlparse(target)
 if p.scheme!="https" or not p.netloc:raise HTTPException(400,"Restore target must use HTTPS")
 return target
@app.get("/health")
def health():
 _initialize_database();r={"status":"ok" if DB_READY else "degraded","service":"UGA Backup Service","database":"connected" if DB_READY else "unreachable","time":_now_iso()}
 if not DB_READY:
  if DB_ERROR:r["database_error"]=DB_ERROR[:500]
  return r
 db=SessionLocal()
 try:r["records"]={"UGAMAP":db.query(BackupRecord).filter(BackupRecord.source=="UGAMAP",BackupRecord.is_deleted==0).count(),"UGASHIP":db.query(BackupRecord).filter(BackupRecord.source=="UGASHIP",BackupRecord.is_deleted==0).count(),"deleted":db.query(BackupRecord).filter(BackupRecord.is_deleted!=0).count(),"snapshots":db.query(Snapshot).count()};last=db.query(SyncLog).order_by(SyncLog.created_at.desc()).first();r["last_activity"]=last.created_at.isoformat() if last and last.created_at else None
 except Exception as e:r["stats_error"]=f"{type(e).__name__}: {e}"[:300]
 finally:db.close()
 return r
@app.get("/audit",dependencies=[Depends(verify_restore_token)])
def audit(source:str|None=Query(None,pattern="^(UGAMAP|UGASHIP)$"),limit:int=Query(100,ge=1,le=500),db:Session=Depends(get_db)):
 q=db.query(SyncLog)
 if source:q=q.filter(SyncLog.source==source)
 rows=q.order_by(SyncLog.created_at.desc(),SyncLog.id.desc()).limit(limit).all();return {"source":source,"count":len(rows),"events":[{"id":x.id,"action":x.action,"source":x.source,"detail":x.detail,"created_at":x.created_at} for x in rows]}
@app.post("/sync",dependencies=[Depends(verify_sync_token)])
def sync_event(e:SyncEvent,db:Session=Depends(get_db)):
 x=db.query(BackupRecord).filter(and_(BackupRecord.source==e.source,BackupRecord.entity_type==e.entity_type,BackupRecord.entity_id==e.entity_id)).first()
 if x and e.source_updated_at and x.source_updated_at and e.source_updated_at<x.source_updated_at:return {"status":"ignored_stale","entity_id":e.entity_id}
 if e.action=="delete":
  if x:x.is_deleted=1;x.source_updated_at=e.source_updated_at
  else:db.add(BackupRecord(source=e.source,entity_type=e.entity_type,entity_id=e.entity_id,data=e.data,is_deleted=1,source_updated_at=e.source_updated_at))
  db.add(SyncLog(action="delete",source=e.source,detail=f"{e.entity_type}:{e.entity_id}"));db.commit();return {"status":"deleted","entity_id":e.entity_id}
 if x:x.data=e.data;x.is_deleted=0;x.source_updated_at=e.source_updated_at
 else:db.add(BackupRecord(source=e.source,entity_type=e.entity_type,entity_id=e.entity_id,data=e.data,source_updated_at=e.source_updated_at))
 db.add(SyncLog(action="sync",source=e.source,detail=f"{e.entity_type}:{e.entity_id}"));db.commit();return {"status":"synced","entity_id":e.entity_id}
@app.post("/sync/bulk",dependencies=[Depends(verify_sync_token)])
def sync_bulk(p:BulkSyncPayload,db:Session=Depends(get_db)):
 synced=0;skipped=0
 for record in p.records:
  raw=record.get("id",record.get("entity_id"))
  if raw is None:skipped+=1;continue
  eid=str(raw).strip()
  if not eid:skipped+=1;continue
  x=db.query(BackupRecord).filter(and_(BackupRecord.source==p.source,BackupRecord.entity_type==p.entity_type,BackupRecord.entity_id==eid)).first()
  if x:x.data=record;x.is_deleted=0
  else:db.add(BackupRecord(source=p.source,entity_type=p.entity_type,entity_id=eid,data=record))
  synced+=1
 db.add(SyncLog(action="bulk_sync",source=p.source,detail=f"{p.entity_type}: {synced} records, {skipped} skipped"));db.commit();return {"status":"ok","synced":synced,"skipped":skipped}
@app.get("/records",dependencies=[Depends(verify_restore_token)])
def records(source:str=Query(...,pattern="^(UGAMAP|UGASHIP)$"),entity_type:str|None=None,include_deleted:bool=False,db:Session=Depends(get_db)):
 q=db.query(BackupRecord).filter(BackupRecord.source==source)
 if not include_deleted:q=q.filter(BackupRecord.is_deleted==0)
 if entity_type:q=q.filter(BackupRecord.entity_type==entity_type)
 return [{"entity_type":r.entity_type,"entity_id":r.entity_id,"data":r.data,"is_deleted":bool(r.is_deleted),"source_updated_at":r.source_updated_at,"synced_at":r.synced_at} for r in q.all()]
@app.post("/snapshot/create",dependencies=[Depends(verify_restore_token)])
def create_snapshot(source:str|None=Query(None,pattern="^(UGAMAP|UGASHIP)$"),db:Session=Depends(get_db)):
 q=db.query(BackupRecord)
 if source:q=q.filter(BackupRecord.source==source)
 rows=q.order_by(BackupRecord.source,BackupRecord.entity_type,BackupRecord.entity_id).all();dump=[{"source":r.source,"entity_type":r.entity_type,"entity_id":r.entity_id,"data":r.data,"is_deleted":bool(r.is_deleted),"source_updated_at":r.source_updated_at.isoformat() if r.source_updated_at else None} for r in rows];checksum=_checksum(dump);label=datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S");s=Snapshot(label=label,source=source,checksum=checksum,data=dump);db.add(s);db.add(SyncLog(action="snapshot",source=source,detail=f"{label}: {len(dump)} records sha256={checksum}"));db.commit();db.refresh(s);return {"status":"ok","id":s.id,"label":label,"record_count":len(dump),"checksum":checksum}
@app.get("/snapshot/list",dependencies=[Depends(verify_restore_token)])
def list_snapshots(source:str|None=Query(None,pattern="^(UGAMAP|UGASHIP)$"),db:Session=Depends(get_db)):
 q=db.query(Snapshot)
 if source:q=q.filter(Snapshot.source==source)
 return [{"id":s.id,"label":s.label,"source":s.source,"checksum":s.checksum,"created_at":s.created_at} for s in q.order_by(Snapshot.created_at.desc()).limit(100).all()]
@app.get("/snapshot/{snapshot_id}",dependencies=[Depends(verify_restore_token)])
def get_snapshot(snapshot_id:int,db:Session=Depends(get_db)):
 s=db.get(Snapshot,snapshot_id)
 if not s:raise HTTPException(404,"Snapshot not found")
 actual=_checksum(s.data);return {"id":s.id,"label":s.label,"source":s.source,"checksum":s.checksum,"integrity":"ok" if actual==s.checksum else "failed","created_at":s.created_at,"data":s.data}
@app.post("/restore",dependencies=[Depends(verify_restore_token)])
async def restore(req:RestoreRequest,db:Session=Depends(get_db)):
 target=_target(req.source,req.target_url)
 if req.snapshot_id is not None:
  s=db.get(Snapshot,req.snapshot_id)
  if not s:raise HTTPException(404,"Snapshot not found")
  actual=_checksum(s.data)
  if actual!=s.checksum:db.add(SyncLog(action="restore_blocked_integrity",source=req.source,detail=f"snapshot={s.id} expected={s.checksum} actual={actual}"));db.commit();raise HTTPException(409,"Snapshot integrity verification failed; restore blocked")
  selected=[i for i in s.data if i.get("source")==req.source and (not req.entity_type or i.get("entity_type")==req.entity_type)];out=[i.get("data",{}) for i in selected if not i.get("is_deleted")];desc=f"snapshot:{req.snapshot_id}"
 else:
  q=db.query(BackupRecord).filter(BackupRecord.source==req.source,BackupRecord.is_deleted==0)
  if req.entity_type:q=q.filter(BackupRecord.entity_type==req.entity_type)
  out=[r.data for r in q.all()];desc="live_backup"
 db.add(SyncLog(action="restore_prepare",source=req.source,detail=f"{desc}/{req.entity_type or 'all'}: {len(out)} records -> {target or 'manual'}"));db.commit()
 if not target or req.dry_run:return {"status":"dry_run" if req.dry_run else "no_target_configured","source":req.source,"record_count":len(out),"records":out}
 token=os.environ.get(f"{req.source}_RESTORE_PUSH_TOKEN","").strip()
 if not token:raise HTTPException(503,f"{req.source}_RESTORE_PUSH_TOKEN is not configured")
 async with httpx.AsyncClient(timeout=60) as client:
  try:r=await client.post(target,json={"source":req.source,"entity_type":req.entity_type,"records":out},headers={"x-backup-restore-token":token});r.raise_for_status()
  except httpx.HTTPError as e:db.add(SyncLog(action="restore_failed",source=req.source,detail=str(e)[:1000]));db.commit();raise HTTPException(502,"Restore push failed") from e
 db.add(SyncLog(action="restore_complete",source=req.source,detail=f"{len(out)} records -> {target}"));db.commit();return {"status":"restored","record_count":len(out),"target":target}
