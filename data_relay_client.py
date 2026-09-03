from __future__ import annotations
import os
import threading
import time
import httpx

DRS_URL=os.getenv("DRS_URL","https://web-production-750da.up.railway.app").rstrip("/")
DRS_SERVICE_ID=os.getenv("DRS_SERVICE_ID","backup").strip() or "backup"
DRS_SERVICE_KEY=os.getenv("DRS_SERVICE_KEY","").strip()
_started=False
_lock=threading.Lock()


def emit(category:str,severity:str="info",**fields)->bool:
    if not DRS_SERVICE_KEY:
        return False
    payload={
        "category":category,
        "source":"backup",
        "severity":severity,
        "actor":fields.pop("actor","uga-backup-service"),
        "action":fields.pop("action","backup_status"),
        "resource":fields.pop("resource","uga-backup-service"),
        "status":fields.pop("status","ok"),
        "payload":fields,
    }
    try:
        r=httpx.post(
            DRS_URL+"/events",
            json=payload,
            headers={"x-service-id":DRS_SERVICE_ID,"x-service-key":DRS_SERVICE_KEY,"Accept":"application/json"},
            timeout=5.0,
        )
        return 200 <= r.status_code < 300
    except Exception:
        return False


def _heartbeat_worker():
    time.sleep(10)
    while True:
        emit("system_metric",action="backup_heartbeat",status="online",component="backup",heartbeat=True)
        time.sleep(60)


def start_relay_heartbeat():
    global _started
    with _lock:
        if _started:return
        _started=True
        threading.Thread(target=_heartbeat_worker,name="backup-relay-heartbeat",daemon=True).start()
