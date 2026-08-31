# UGA Backup Service

Standalone FastAPI + PostgreSQL backup service for UGAMAP and UGASHIP.

It is designed to run independently from both production applications and their primary databases so data can still be recovered after a main-host or database failure.

## Data flow

UGAMAP / UGASHIP -> `POST /sync` -> independent backup PostgreSQL

A scheduled reconciliation job may also export complete datasets from either source and send them to `POST /sync/bulk` to catch missed real-time events.

Daily snapshots provide point-in-time recovery protection against accidental or corrupt syncs.

## Security model

- `BACKUP_SYNC_TOKEN`: low-privilege service-to-service credential used only for incoming sync calls.
- `BACKUP_RESTORE_TOKEN`: separate high-privilege credential required for records, snapshots and restore operations.
- `UGAMAP_RESTORE_PUSH_TOKEN` / `UGASHIP_RESTORE_PUSH_TOKEN`: credentials presented to the corresponding production restore endpoint.
- Restore targets must match the preconfigured HTTPS destination; arbitrary URLs are rejected.
- Restore defaults to `dry_run=true`, so a request returns the candidate records without pushing them until explicitly enabled.
- Real secrets belong only in deployment environment variables. Never commit `.env`.

## Deploy

Recommended: use a PostgreSQL provider or region that is independent from the infrastructure running UGAMAP and UGASHIP.

1. Create a PostgreSQL database.
2. Deploy this repository to Railway or another container host.
3. Set the variables shown in `.env.example` using real secret values.
4. Deploy.
5. Test `GET /health`.
6. Optionally point `backup.ugandagrid.com` at the service.

## Core endpoints

- `GET /health`
- `POST /sync`
- `POST /sync/bulk`
- `GET /records`
- `POST /snapshot/create`
- `GET /snapshot/list`
- `GET /snapshot/{snapshot_id}`
- `POST /restore`

## Real-time integration

Use `example_client_snippet.py` inside UGAMAP and UGASHIP. Set `SOURCE_NAME=UGAMAP` in UGAMAP and `SOURCE_NAME=UGASHIP` in UGASHIP.

Call the helper after successful create/update/delete operations. Backup calls are best-effort and must never break the live user request if the backup service is temporarily unavailable.

## Reconciliation

Every 15-30 minutes, export current source records and send them to `/sync/bulk`. This closes gaps caused by missed real-time events.

## Snapshots

Call `/snapshot/create` daily using the restore/admin credential. Each snapshot stores the complete generic record set and a SHA-256 checksum.

Snapshots include soft-deleted records so historical state is preserved.

## Restore

`POST /restore` defaults to a dry run. You can restore from either the current backup state or a specific snapshot using `snapshot_id`.

A live push requires:

1. `dry_run=false`
2. A configured approved restore target
3. The corresponding restore push token
4. A protected `/admin/restore` endpoint in UGAMAP or UGASHIP that validates the push token and performs safe upserts

Do not enable live restore until the receiving production endpoint has been implemented and tested.
