import os
from pathlib import Path

import psycopg


def get_migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations"


def load_migrations(migrations_dir: Path) -> list[Path]:
    return sorted(path for path in migrations_dir.glob("*.sql"))


def ensure_schema_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def migration_applied(conn: psycopg.Connection, filename: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM schema_migrations WHERE filename = %s",
            (filename,),
        )
        return cur.fetchone() is not None


def record_migration(conn: psycopg.Connection, filename: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO schema_migrations (filename) VALUES (%s)",
            (filename,),
        )


def apply_migration(conn: psycopg.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL environment variable is required")

    migrations_dir = get_migrations_dir()
    if not migrations_dir.exists():
        raise SystemExit(f"Migrations directory not found: {migrations_dir}")

    migrations = load_migrations(migrations_dir)
    if not migrations:
        raise SystemExit(f"No migrations found in {migrations_dir}")

    with psycopg.connect(database_url) as conn:
        ensure_schema_table(conn)
        for migration in migrations:
            if migration_applied(conn, migration.name):
                continue
            apply_migration(conn, migration)
            record_migration(conn, migration.name)


if __name__ == "__main__":
    main()
