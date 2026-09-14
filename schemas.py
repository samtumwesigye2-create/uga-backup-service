from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

BackupSource = Literal["UGAMAP", "UGASHIP", "WAREHOUSE", "UNG-PRESIDENT"]


class SyncEvent(BaseModel):
    source: BackupSource
    entity_type: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=255)
    action: Literal["create", "update", "delete"] = "update"
    data: dict[str, Any]
    source_updated_at: datetime | None = None


class BulkSyncPayload(BaseModel):
    source: BackupSource
    entity_type: str = Field(min_length=1, max_length=128)
    records: list[dict[str, Any]]


class RestoreRequest(BaseModel):
    source: BackupSource
    entity_type: str | None = Field(default=None, max_length=128)
    target_url: str | None = None
    snapshot_id: int | None = Field(default=None, ge=1)
    dry_run: bool = True
