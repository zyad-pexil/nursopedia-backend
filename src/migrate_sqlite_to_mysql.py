"""
One-off migration script: Copy data from SQLite to MySQL.

Usage:
  - Ensure MySQL env vars are set (MYSQLHOST, MYSQLPORT, MYSQLUSER, MYSQLPASSWORD, MYSQLDATABASE)
  - Optional: SOURCE_SQLITE_PATH points to the SQLite file (default: src/database/app.db)
  - Optional: SKIP_TABLES comma-separated list to skip
  - Optional: DRY_RUN=1 to only show what would be done

Run examples:
  python -m src.migrate_sqlite_to_mysql
  SOURCE_SQLITE_PATH="/path/to/app.db" python -m src.migrate_sqlite_to_mysql
"""
from __future__ import annotations
import os
from sqlalchemy import create_engine, MetaData, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


def build_mysql_uri() -> str | None:
    host = os.getenv('MYSQLHOST') or os.getenv('DB_HOST')
    port = os.getenv('MYSQLPORT') or os.getenv('DB_PORT', '3306')
    user = os.getenv('MYSQLUSER') or os.getenv('DB_USER')
    password = os.getenv('MYSQLPASSWORD') or os.getenv('DB_PASSWORD')
    database = os.getenv('MYSQLDATABASE') or os.getenv('DB_NAME')
    if host and user and password and database:
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"
    return None


def default_sqlite_path() -> str:
    here = os.path.dirname(__file__)
    return os.getenv('SOURCE_SQLITE_PATH', os.path.join(here, 'database', 'app.db'))


def reflect_metadata(engine: Engine) -> MetaData:
    md = MetaData()
    md.reflect(bind=engine)
    return md


def table_order(md: MetaData) -> list[str]:
    # Manual order to respect FKs in our schema; fallback to alphabetical for unknown tables
    preferred = [
        'academic_years',
        'subjects',
        'users',
        'subscription_requests',
        'active_subscriptions',
        'lessons',
        'exams',
        'exam_questions',
        'exam_attempts',
        'exam_answers',
        'lesson_progress',
        'notifications',
        'activity_logs',
        'questions',
        'answers',
        'payment_receipts',  # likely empty in SQLite
    ]
    existing = set(md.tables.keys())
    ordered = [t for t in preferred if t in existing]
    rest = sorted(existing - set(ordered))
    return ordered + rest


def intersect_columns(src_cols, dst_cols):
    src_names = {c.name for c in src_cols}
    dst_names = {c.name for c in dst_cols}
    common = [name for name in src_names if name in dst_names]
    # Preserve a stable order: dst order
    dst_ordered = [name for name in [c.name for c in dst_cols] if name in common]
    return dst_ordered


def disable_fk_checks_mysql(engine: Engine, disable: bool):
    try:
        with engine.connect() as conn:
            conn.execute(f"SET FOREIGN_KEY_CHECKS={'0' if disable else '1'}")
    except Exception:
        pass


def copy_table(src_engine: Engine, dst_engine: Engine, src_md: MetaData, dst_md: MetaData, table_name: str, dry_run: bool = False) -> tuple[int, int]:
    if table_name not in src_md.tables or table_name not in dst_md.tables:
        return (0, 0)
    src_t = src_md.tables[table_name]
    dst_t = dst_md.tables[table_name]

    # Skip if destination already has rows (idempotency)
    with dst_engine.connect() as dconn:
        dst_count = dconn.execute(select(dst_t.count())) if hasattr(dst_t, 'count') else dconn.execute(f"SELECT COUNT(*) FROM {table_name}")
        try:
            existing = list(dst_count)[0][0]
        except Exception:
            existing = 0
        if existing > 0:
            return (0, existing)

    cols = intersect_columns(src_t.columns, dst_t.columns)
    if not cols:
        return (0, 0)

    inserted = 0
    with src_engine.connect() as sconn, dst_engine.begin() as dtx:
        try:
            rows = sconn.execute(select(src_t)).fetchall()
            if not rows:
                return (0, 0)
            payload = []
            for r in rows:
                rec = {c: r._mapping.get(c) for c in cols}
                payload.append(rec)
            if dry_run:
                return (len(payload), 0)
            dtx.execute(dst_t.insert(), payload)
            inserted = len(payload)
        except SQLAlchemyError as e:
            raise e
    return (inserted, 0)


def main():
    mysql_uri = build_mysql_uri()
    if not mysql_uri:
        raise SystemExit('MySQL environment variables are missing. Aborting.')

    sqlite_path = default_sqlite_path()
    if not os.path.exists(sqlite_path):
        raise SystemExit(f'SQLite file not found: {sqlite_path}')

    dry_run = os.getenv('DRY_RUN', '0') == '1'
    skip = {s.strip() for s in os.getenv('SKIP_TABLES', '').split(',') if s.strip()}

    src_engine = create_engine(f'sqlite:///{sqlite_path}')
    dst_engine = create_engine(mysql_uri)

    src_md = reflect_metadata(src_engine)
    dst_md = reflect_metadata(dst_engine)

    order = [t for t in table_order(src_md) if t in dst_md.tables and t not in skip]

    print(f"Starting migration from {sqlite_path} -> {mysql_uri}")
    print(f"Tables order: {order}")

    disable_fk_checks_mysql(dst_engine, True)
    summary = {}
    try:
        for t in order:
            try:
                ins, existed = copy_table(src_engine, dst_engine, src_md, dst_md, t, dry_run=dry_run)
                summary[t] = {'inserted': ins, 'skipped_existing_rows': existed}
                print(f"Table {t}: inserted={ins}, skipped_existing_rows={existed}")
            except Exception as e:
                summary[t] = {'error': str(e)}
                print(f"Table {t}: ERROR {e}")
    finally:
        disable_fk_checks_mysql(dst_engine, False)

    print('Migration finished:')
    for t, info in summary.items():
        print(t, '->', info)


if __name__ == '__main__':
    main()