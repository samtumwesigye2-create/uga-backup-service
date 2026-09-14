from schemas import BulkSyncPayload, RestoreRequest, SyncEvent


def test_president_is_supported_across_backup_payloads():
    assert SyncEvent(
        source="UNG-PRESIDENT",
        entity_type="users",
        entity_id="1",
        data={"id": 1},
    ).source == "UNG-PRESIDENT"
    assert BulkSyncPayload(
        source="UNG-PRESIDENT",
        entity_type="users",
        records=[{"id": 1}],
    ).source == "UNG-PRESIDENT"
    assert RestoreRequest(source="UNG-PRESIDENT", dry_run=True).source == "UNG-PRESIDENT"
