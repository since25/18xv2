from __future__ import annotations

import argparse
from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

DEFAULT_SQLITE_URL = "sqlite:///./data/storage_organizer.db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将 SQLite 数据库迁移到 PostgreSQL")
    parser.add_argument("--sqlite-url", default=DEFAULT_SQLITE_URL, help="源 SQLite URL")
    parser.add_argument("--postgres-url", required=True, help="目标 PostgreSQL URL")
    parser.add_argument("--batch-size", type=int, default=1000, help="每批复制的行数")
    parser.add_argument(
        "--truncate-target",
        action="store_true",
        help="迁移前清空目标 PostgreSQL 中的已有业务表（默认拒绝覆盖非空库）",
    )
    return parser.parse_args()


def reflect_metadata(engine: Engine) -> MetaData:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return metadata


def read_batches(source_engine: Engine, source_table: Table, batch_size: int) -> Iterator[list[dict[str, object]]]:
    with source_engine.connect() as source_conn:
        cursor = source_conn.execute(select(source_table)).mappings()
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield [dict(row) for row in rows]


def quote_table_name(table_name: str) -> str:
    return '"' + table_name.replace('"', '""') + '"'


def get_reference_values(source_engine: Engine, table: Table, column_name: str) -> set[object]:
    column = table.c[column_name]
    with source_engine.connect() as conn:
        values = conn.execute(select(column).where(column.is_not(None))).scalars().all()
    return set(values)


def sanitize_foreign_keys(
    row: dict[str, object],
    target_table: Table,
    source_metadata: MetaData,
    source_engine: Engine,
    reference_cache: dict[tuple[str, str], set[object]],
    sanitized_counters: dict[tuple[str, str], int],
) -> dict[str, object]:
    sanitized = dict(row)
    for fk in target_table.foreign_key_constraints:
        if len(fk.elements) != 1:
            continue
        element = fk.elements[0]
        local_column = element.parent
        remote_column = element.column
        value = sanitized.get(local_column.name)
        if value is None:
            continue
        remote_table = source_metadata.tables.get(remote_column.table.name)
        if remote_table is None:
            continue
        cache_key = (remote_table.name, remote_column.name)
        valid_values = reference_cache.get(cache_key)
        if valid_values is None:
            valid_values = get_reference_values(source_engine, remote_table, remote_column.name)
            reference_cache[cache_key] = valid_values
        if value in valid_values:
            continue
        if local_column.nullable:
            sanitized[local_column.name] = None
            counter_key = (target_table.name, local_column.name)
            sanitized_counters[counter_key] = sanitized_counters.get(counter_key, 0) + 1
            continue
        raise RuntimeError(
            f"non-nullable foreign key {target_table.name}.{local_column.name} references missing "
            f"{remote_table.name}.{remote_column.name}={value}"
        )
    return sanitized


def copy_table(
    source_table: Table,
    target_table: Table,
    batch_size: int,
    source_engine: Engine,
    target_engine: Engine,
    source_metadata: MetaData,
    reference_cache: dict[tuple[str, str], set[object]],
) -> None:
    copied_rows = 0
    sanitized_counters: dict[tuple[str, str], int] = {}
    with target_engine.begin() as target_conn:
        for batch in read_batches(source_engine, source_table, batch_size):
            if copied_rows == 0:
                print(f"[migrate] start copy table: {target_table.name}")
            sanitized_batch = [
                sanitize_foreign_keys(
                    row,
                    target_table=target_table,
                    source_metadata=source_metadata,
                    source_engine=source_engine,
                    reference_cache=reference_cache,
                    sanitized_counters=sanitized_counters,
                )
                for row in batch
            ]
            target_conn.execute(target_table.insert(), sanitized_batch)
            copied_rows += len(batch)
    if copied_rows == 0:
        print(f"[migrate] skip empty table: {target_table.name}")
        return
    print(f"[migrate] copied {target_table.name}: {copied_rows} rows")
    for (table_name, column_name), count in sorted(sanitized_counters.items()):
        print(f"[migrate] sanitized dangling FK {table_name}.{column_name}: {count} rows -> NULL")


def table_row_count(engine: Engine, table: Table) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


def ensure_target_state(target_engine: Engine, target_metadata: MetaData, truncate_target: bool) -> None:
    with target_engine.begin() as conn:
        if truncate_target:
            for table in reversed(target_metadata.sorted_tables):
                conn.execute(text(f"TRUNCATE TABLE {quote_table_name(table.name)} RESTART IDENTITY CASCADE"))
            return

        non_empty: list[str] = []
        for table in target_metadata.sorted_tables:
            count = int(conn.execute(select(func.count()).select_from(table)).scalar_one())
            if count > 0:
                non_empty.append(f"{table.name}({count})")
        if non_empty:
            joined = ", ".join(non_empty)
            raise RuntimeError(f"target PostgreSQL is not empty: {joined}. Use --truncate-target if you really want to overwrite it.")


def reset_postgres_sequences(target_engine: Engine, target_metadata: MetaData) -> None:
    inspector = inspect(target_engine)
    with target_engine.begin() as conn:
        for table in target_metadata.sorted_tables:
            pk = inspector.get_pk_constraint(table.name)
            columns = pk.get("constrained_columns") or []
            if len(columns) != 1:
                continue
            column_name = columns[0]
            column = table.c.get(column_name)
            if column is None:
                continue
            try:
                python_type = column.type.python_type
            except NotImplementedError:
                continue
            if python_type is not int:
                continue
            sequence_name = conn.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column_name},
            ).scalar_one_or_none()
            if not sequence_name:
                continue
            max_value = conn.execute(select(func.max(column))).scalar_one()
            conn.execute(
                text("SELECT setval(:sequence_name, :next_value, :is_called)"),
                {
                    "sequence_name": sequence_name,
                    "next_value": 1 if max_value is None else int(max_value),
                    "is_called": max_value is not None,
                },
            )


def verify_counts(source_engine: Engine, target_engine: Engine, source_metadata: MetaData, target_metadata: MetaData) -> None:
    mismatches: list[str] = []
    for target_table in target_metadata.sorted_tables:
        source_table = source_metadata.tables.get(target_table.name)
        if source_table is None:
            continue
        source_count = table_row_count(source_engine, source_table)
        target_count = table_row_count(target_engine, target_table)
        if source_count != target_count:
            mismatches.append(f"{target_table.name}: sqlite={source_count}, postgres={target_count}")
    if mismatches:
        raise RuntimeError("row count mismatch after migration: " + "; ".join(mismatches))


def main() -> int:
    args = parse_args()
    source_engine = create_engine(args.sqlite_url, future=True)
    target_engine = create_engine(args.postgres_url, future=True, pool_pre_ping=True)

    source_metadata = reflect_metadata(source_engine)
    target_metadata = reflect_metadata(target_engine)

    missing_tables = [table.name for table in source_metadata.sorted_tables if table.name not in target_metadata.tables]
    if missing_tables:
        raise RuntimeError(f"target PostgreSQL schema is missing tables: {', '.join(missing_tables)}")

    ensure_target_state(target_engine, target_metadata, truncate_target=args.truncate_target)

    reference_cache: dict[tuple[str, str], set[object]] = {}
    for target_table in target_metadata.sorted_tables:
        source_table = source_metadata.tables.get(target_table.name)
        if source_table is None:
            continue
        copy_table(
            source_table,
            target_table,
            args.batch_size,
            source_engine,
            target_engine,
            source_metadata,
            reference_cache,
        )

    reset_postgres_sequences(target_engine, target_metadata)
    verify_counts(source_engine, target_engine, source_metadata, target_metadata)
    print("[migrate] migration completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
