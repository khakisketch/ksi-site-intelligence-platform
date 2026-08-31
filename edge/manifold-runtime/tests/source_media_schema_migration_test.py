#!/usr/bin/env python3
"""Exercise the real native migration against a pre-selection source-media DB."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: source_media_schema_migration_test.py <edge_runtime_tests>")
    binary = Path(sys.argv[1]).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="ksi-source-media-legacy-") as directory:
        database = Path(directory) / "legacy.sqlite"
        with sqlite3.connect(database) as connection:
            connection.executescript(
                """
                CREATE TABLE source_media_missions (
                  mission_id TEXT PRIMARY KEY,
                  edge_device_id TEXT NOT NULL,
                  discovered_count INTEGER,
                  sealed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE source_media_items (
                  mission_id TEXT NOT NULL,
                  media_id TEXT NOT NULL,
                  camera_file_name TEXT NOT NULL,
                  announced_bytes INTEGER NOT NULL,
                  state TEXT NOT NULL,
                  quarantine_reason TEXT,
                  artifact_id TEXT,
                  local_path TEXT,
                  content_digest TEXT,
                  byte_count INTEGER,
                  width INTEGER,
                  height INTEGER,
                  content_type TEXT,
                  PRIMARY KEY(mission_id, media_id)
                );
                INSERT INTO source_media_missions
                  (mission_id, edge_device_id, discovered_count, sealed)
                  VALUES ('legacy-mission', 'legacy-edge', 1, 0);
                INSERT INTO source_media_items
                  (mission_id, media_id, camera_file_name, announced_bytes, state)
                  VALUES ('legacy-mission', 'DJI_OLD', 'DJI_OLD.JPG', 123, 'DISCOVERED');
                """
            )

        completed = subprocess.run(
            [str(binary), "--inspect-legacy-source-media", str(database)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            sys.stderr.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            return completed.returncode
        expected = "context=LEGACY_EMPTY selection=LEGACY_EMPTY index=-1 replay=CONFLICT"
        if expected not in completed.stdout:
            raise AssertionError(completed.stdout)

        with sqlite3.connect(database) as connection:
            mission_columns = {
                row[1]: row
                for row in connection.execute("PRAGMA table_info(source_media_missions)")
            }
            item_columns = {
                row[1]: row for row in connection.execute("PRAGMA table_info(source_media_items)")
            }
            legacy_mission = connection.execute(
                "SELECT selection_context_digest, selected_files_digest "
                "FROM source_media_missions WHERE mission_id='legacy-mission'"
            ).fetchone()
            legacy_item = connection.execute(
                "SELECT source_file_index FROM source_media_items "
                "WHERE mission_id='legacy-mission' AND media_id='DJI_OLD'"
            ).fetchone()
        assert "selection_context_digest" in mission_columns
        assert "selected_files_digest" in mission_columns
        assert "source_file_index" in item_columns
        assert legacy_mission == ("", "")
        assert legacy_item == (-1,)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
