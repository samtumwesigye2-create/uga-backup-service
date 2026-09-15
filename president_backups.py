"""Immutable full-database snapshots; isolated from existing record mirrors."""
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from models import Snapshot, SyncLog

TABLES = frozenset(('users', 'executive_orders', 'appointments', 'honours', 'events',
                   'visit_requests', 'petitions', 'state_visits', 'press_statements',
                   'hr_codes', 'staff_profiles', 'audit_log'))


class FullSnapshot(BaseModel):
    records: list[dict[str, Any]] = Field(min_length=12, max_length=12)
    checksum: str = Field(pattern=r'^[0-9a-f]{64}$')


def register(app, get_db, verify_sync_token, verify_restore_token):
    @app.post('/president/snapshot', dependencies=[Depends(verify_sync_token)])
    def save_snapshot(payload: FullSnapshot, db: Session = Depends(get_db)):
        seen = set()
        for record in payload.records:
            table = record.get('entity_type')
            data = record.get('data')
            if (record.get('source') != 'UNG-PRESIDENT' or table not in TABLES
                    or table in seen or record.get('entity_id') != 'full-table'
                    or record.get('is_deleted') is not False
                    or not isinstance(data, dict) or not isinstance(data.get('rows'), list)
                    or any(not isinstance(row, dict) for row in data['rows'])):
                raise HTTPException(422, 'Invalid or incomplete database snapshot.')
            seen.add(table)
        digest = hashlib.sha256(json.dumps(payload.records, sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()
        if seen != TABLES or not hmac.compare_digest(digest, payload.checksum):
            raise HTTPException(422, 'Snapshot checksum or table manifest mismatch.')
        snapshot = Snapshot(source='UNG-PRESIDENT', checksum=digest, data=payload.records,
                            label=datetime.now(timezone.utc).strftime('president-%Y%m%d-%H%M%S'))
        db.add(snapshot)
        db.add(SyncLog(action='snapshot', source='UNG-PRESIDENT', detail='Complete database snapshot'))
        db.commit()
        db.refresh(snapshot)
        return {'status': 'ok', 'id': snapshot.id, 'checksum': digest,
                'table_count': len(seen), 'record_count': sum(len(r['data']['rows']) for r in payload.records)}

    @app.get('/president/snapshots', dependencies=[Depends(verify_restore_token)])
    def list_snapshots(db: Session = Depends(get_db)):
        rows = db.query(Snapshot).filter(Snapshot.source == 'UNG-PRESIDENT').order_by(Snapshot.id.desc()).limit(100).all()
        return [{'id': row.id, 'checksum': row.checksum, 'created_at': row.created_at} for row in rows]
