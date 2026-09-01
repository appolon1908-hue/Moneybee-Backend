#!/usr/bin/env python3
"""Populate the 0022a compatibility column from an approved ID/reference map.

This is an explicit write operation for an isolated rehearsal or an approved
change window. The mapping contains references only, never credential values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def stage(database_url: str, mapping_path: Path) -> None:
    raw = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise SystemExit("mapping must be a non-empty object of row UUID to secret:// reference")
    mapping: dict[str, str] = {}
    for row_id, reference in raw.items():
        uuid.UUID(row_id)
        if not isinstance(reference, str) or not reference.startswith("secret://"):
            raise SystemExit(f"{row_id}: reference must use the secret:// scheme")
        mapping[row_id] = reference

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "20260901_0022a":
                raise RuntimeError("database must be stopped at Alembic 20260901_0022a")
            for row_id, reference in mapping.items():
                result = await connection.execute(
                    text(
                        "UPDATE bank_provider_states SET credential_reference=:reference "
                        "WHERE id=:row_id AND credential_reference IS NULL"
                    ),
                    {"row_id": row_id, "reference": reference},
                )
                if result.rowcount != 1:
                    raise RuntimeError(f"{row_id}: expected exactly one legacy row")
            unresolved = await connection.scalar(
                text(
                    "SELECT count(*) FROM bank_provider_states "
                    "WHERE credential_reference IS NULL "
                    "OR trim(credential_reference) NOT LIKE 'secret://%'"
                )
            )
            if unresolved:
                raise RuntimeError(f"{unresolved} credential rows remain unresolved")
    finally:
        await engine.dispose()
    print(f"staged and verified {len(mapping)} external credential references")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--mapping", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(stage(args.database_url, args.mapping))


if __name__ == "__main__":
    main()
