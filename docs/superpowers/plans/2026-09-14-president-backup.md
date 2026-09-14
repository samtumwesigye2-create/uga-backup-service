# UNG-PRESIDENT Backup Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend UGA Backup Service to accept, snapshot, audit, list, and dry-run restore UNG-PRESIDENT records, then add a non-destructive export/sync path from the hardened UNG-PRESIDENT application.

**Architecture:** Keep the existing push-based backup model. UNG-PRESIDENT exports rows from its own database and sends them to UGA Backup Service `/sync/bulk`; UGA Backup Service stores them as `BackupRecord` rows and includes `UNG-PRESIDENT` in integrity-checked scheduled snapshots and restore tooling. Production data is never altered during backup verification; restore is tested in dry-run mode first.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy/PostgreSQL, httpx, pytest.

**Spec:** User-approved existing UGA Backup Service extension for UNG-PRESIDENT.

## Global Constraints

- Preserve existing UGAMAP, UGASHIP, and WAREHOUSE backup behavior.
- Do not mutate or delete UNG-PRESIDENT live data during backup verification.
- Do not enable a live restore target until a dry-run snapshot integrity test succeeds.
- Do not merge UNG-PRESIDENT's PostgreSQL hardening PR solely because backup code exists; backup evidence must be verified separately.

---

### Task 1: Add UNG-PRESIDENT as a supported backup source

**Files:**
- Modify: `schemas.py`
- Modify: `main.py`
- Modify: `snapshot_scheduler.py`
- Create: `tests/test_president_source.py`

**Interfaces:**
- Consumes: existing `/sync`, `/sync/bulk`, `/records`, `/snapshot/*`, `/restore` endpoints.
- Produces: `UNG-PRESIDENT` accepted anywhere a backup source is validated, included in health counts and scheduled snapshot iteration.

- [ ] **Step 1: Write the failing test**

```python
from pydantic import ValidationError
from schemas import BulkSyncPayload, RestoreRequest, SyncEvent


def test_president_is_supported_across_backup_payloads():
    assert SyncEvent(source="UNG-PRESIDENT", entity_type="users", entity_id="1", data={"id": 1}).source == "UNG-PRESIDENT"
    assert BulkSyncPayload(source="UNG-PRESIDENT", entity_type="users", records=[{"id": 1}]).source == "UNG-PRESIDENT"
    assert RestoreRequest(source="UNG-PRESIDENT", dry_run=True).source == "UNG-PRESIDENT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest -q tests/test_president_source.py`
Expected: FAIL because `UNG-PRESIDENT` is not accepted by the current Literals.

- [ ] **Step 3: Write minimal implementation**

Add `UNG-PRESIDENT` to the Pydantic source Literals, endpoint query regexes, health counts, restore target configuration, and scheduled snapshot source list.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest -q tests/test_president_source.py`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: support UNG-PRESIDENT backup source`

### Task 2: Add UNG-PRESIDENT backup exporter

**Files:**
- Create in UNG-PRESIDENT: `president_backup.py`
- Modify in UNG-PRESIDENT: `ung_president.py`
- Modify in UNG-PRESIDENT: `requirements.txt`
- Create in UNG-PRESIDENT: `tests/test_backup_export.py`

**Interfaces:**
- Consumes: `BACKUP_SERVICE_URL`, `BACKUP_SYNC_TOKEN`, UNG-PRESIDENT `db_cursor()`.
- Produces: `export_backup_records()` and `sync_backup_snapshot()` that send each supported table to `/sync/bulk` with `source="UNG-PRESIDENT"`.

- [ ] **Step 1: Write the failing test**

Test that exporter serializes database rows into deterministic dictionaries by table and that missing backup configuration causes a safe no-op rather than blocking the application.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_backup_export.py`
Expected: FAIL because exporter does not exist.

- [ ] **Step 3: Write minimal implementation**

Export the existing application tables through read-only SELECTs and push them to `/sync/bulk` using the existing UGA Backup Service token header. No DELETE/UPDATE is performed against the PRESIDENT database.

- [ ] **Step 4: Run tests**

Run: `pytest -q`
Expected: all UNG-PRESIDENT tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: export UNG-PRESIDENT records to backup service`

### Task 3: Verify recoverability without changing production data

**Files:**
- No source changes unless verification reveals a bug.

**Interfaces:**
- Consumes: live UGA Backup Service records and snapshot endpoints.
- Produces: evidence that UNG-PRESIDENT records exist, a checksum-valid snapshot exists, and `/restore` dry-run returns those records.

- [ ] **Step 1: Deploy backup-service support after tests pass**
- [ ] **Step 2: Configure UNG-PRESIDENT with backup service URL/token without changing its database connection**
- [ ] **Step 3: Trigger one read-only export**
- [ ] **Step 4: Create an `UNG-PRESIDENT` snapshot**
- [ ] **Step 5: Fetch snapshot and require `integrity == "ok"`**
- [ ] **Step 6: Run `/restore` with `dry_run=true` and confirm record counts/types**
- [ ] **Step 7: Only after the above evidence, mark PRESIDENT backup coverage verified**
