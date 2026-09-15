import importlib


def test_private_backup_database_url_has_highest_priority(monkeypatch):
    monkeypatch.setenv("BACKUP_DATABASE_PRIVATE_URL", "postgresql://private-user:private-pass@postgres.railway.internal:5432/uga_backup")
    monkeypatch.setenv("BACKUP_DATABASE_PUBLIC_URL", "")
    monkeypatch.setenv("DATABASE_PUBLIC_URL", "")
    monkeypatch.setenv("BACKUP_DATABASE_URL", "postgresql://legacy:legacy@thomas.proxy.rlwy.net:25687/uga_backup")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import database
    importlib.reload(database)

    assert database.DATABASE_URL == "postgresql://private-user:private-pass@postgres.railway.internal:5432/uga_backup"
