import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('BACKUP_DATABASE_URL', 'postgresql://unused:unused@localhost/unused')

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest
import main
from models import Snapshot


@compiles(JSONB, 'sqlite')
def jsonb_sqlite(element, compiler, **kw):
    return 'JSON'


@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    def database():
        with sessions() as session:
            yield session
    main.app.dependency_overrides[main.get_db] = database
    monkeypatch.setattr(main, 'SYNC_TOKEN', 'test-sync')
    monkeypatch.setattr(main, 'RESTORE_TOKEN', 'test-restore')
    monkeypatch.setattr(main, '_initialize_database', lambda: None)
    monkeypatch.setattr(main, 'start_snapshot_scheduler', lambda: None)
    with TestClient(main.app) as client:
        yield client
    main.app.dependency_overrides.clear()
    engine.dispose()


def payload():
    tables = ['users', 'executive_orders', 'appointments', 'honours', 'events',
              'visit_requests', 'petitions', 'state_visits', 'press_statements',
              'hr_codes', 'staff_profiles', 'audit_log']
    records = [{'source': 'UNG-PRESIDENT', 'entity_type': table, 'entity_id': 'full-table',
                'data': {'rows': []}, 'is_deleted': False, 'source_updated_at': None}
               for table in tables]
    return {'records': records, 'checksum': main._checksum(records)}


def test_complete_snapshot_roundtrip_and_bad_checksum(client):
    body = payload()
    body['records'][0]['data']['rows'] = [{'id': 1, 'username': 'example'}]
    body['checksum'] = main._checksum(body['records'])
    headers = {'x-backup-token': 'test-sync'}
    assert client.post('/president/snapshot', json=body).status_code in (401, 422)
    response = client.post('/president/snapshot', json=body, headers=headers)
    assert response.status_code == 200, response.text
    saved = client.get('/snapshot/' + str(response.json()['id']),
                       headers={'x-backup-restore-token': 'test-restore'})
    assert saved.json()['data'] == body['records']
    assert saved.json()['integrity'] == 'ok'
    body['checksum'] = '0' * 64
    assert client.post('/president/snapshot', json=body, headers=headers).status_code == 422


def test_incomplete_snapshot_rejected(client):
    body = payload()
    body['records'].pop()
    body['checksum'] = main._checksum(body['records'])
    assert client.post('/president/snapshot', json=body,
                       headers={'x-backup-token': 'test-sync'}).status_code == 422


def test_existing_mirror_still_works_and_snapshot_reads_require_auth(client):
    response = client.post('/sync', headers={'x-backup-token': 'test-sync'}, json={
        'source': 'UGASHIP', 'entity_type': 'shipments', 'entity_id': 'example',
        'action': 'update', 'data': {'id': 'example', 'status': 'delivered'},
    })
    assert response.status_code == 200
    rows = client.get('/records?source=UGASHIP', headers={'x-backup-restore-token': 'test-restore'})
    assert rows.json()[0]['data']['status'] == 'delivered'
    saved = client.post('/president/snapshot', json=payload(), headers={'x-backup-token': 'test-sync'})
    assert client.get('/snapshot/' + str(saved.json()['id'])).status_code == 422
    listing = client.get('/president/snapshots', headers={'x-backup-restore-token': 'test-restore'})
    assert len(listing.json()) == 1
