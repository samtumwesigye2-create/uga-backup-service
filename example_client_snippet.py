import os
from datetime import datetime, timezone

import httpx

BACKUP_URL = os.environ.get("BACKUP_SERVICE_URL", "").rstrip("/")
BACKUP_TOKEN = os.environ.get("BACKUP_SYNC_TOKEN", "")
SOURCE_NAME = os.environ.get("SOURCE_NAME", "UGASHIP")


async def backup_sync(entity_type: str, entity_id: str, data: dict, action: str = "update"):
    if not BACKUP_URL or not BACKUP_TOKEN:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{BACKUP_URL}/sync",
                json={
                    "source": SOURCE_NAME,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "action": action,
                    "data": data,
                    "source_updated_at": datetime.now(timezone.utc).isoformat(),
                },
                headers={"x-backup-token": BACKUP_TOKEN},
            )
    except Exception:
        pass
