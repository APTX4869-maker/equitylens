from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from equitylens.storage.duckdb_store import DuckDBStore


def test_store_connection_uses_utc_when_process_timezone_is_local(tmp_path):
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()
    store = None
    try:
        store = DuckDBStore(tmp_path / "utc.duckdb").connect()
        assert store._conn.execute(
            "SELECT current_setting('TimeZone')"
        ).fetchone()[0] == "UTC"
        store._conn.execute("CREATE TABLE clock_sample(recorded_at TIMESTAMP)")
        store._conn.execute("INSERT INTO clock_sample VALUES (now())")
        stored = store._conn.execute("SELECT recorded_at FROM clock_sample").fetchone()[0]
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((stored - utc_now).total_seconds()) < 5
    finally:
        if store is not None:
            store.close()
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()
