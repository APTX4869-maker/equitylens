class _Store:
    def __init__(self):
        self.source_rows = []

    def connect(self):
        return self

    def init_schema(self):
        pass

    def replace_insider_transactions(self, company_id, rows):
        pass

    def upsert_source_documents(self, rows):
        self.source_rows.extend(rows)

    def replace_proxy(self, company_id, source_document_id, exec_rows, comp_rows, board_rows):
        pass


def test_management_offline_replay_reads_selected_raw_store(monkeypatch, tmp_path):
    from equitylens.ingestion.sec import management

    calls = []

    def list_docs(ticker, *, forms, limit_per_form, raw_dir):
        calls.append((ticker, forms, limit_per_form, raw_dir))
        return []

    class Client:
        def close(self):
            pass

    monkeypatch.setattr(management, "list_filing_docs", list_docs)
    monkeypatch.setattr(management, "SECClient", Client)

    selected = tmp_path / "copied-raw"
    management.sync_management("AAPL", fetch=False, store=_Store(), raw_dir=selected)

    assert calls == [
        ("AAPL", ("DEF 14A",), 1, selected),
        ("AAPL", ("4",), 12, selected),
    ]


def test_management_offline_replay_preserves_snapshot_fetch_time(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from equitylens.ingestion.sec import management
    from equitylens.storage.raw_store import save_snapshot

    accession = "0000320193-26-000001"
    raw = tmp_path / "raw"
    directory = raw / "sec" / "0000320193" / "filing_docs" / accession
    expected_path, _ = save_snapshot(
        directory,
        "proxy.html",
        b"proxy",
        metadata={"fetched_at": "2024-05-06T07:08:09+00:00"},
    )

    def list_docs(ticker, *, forms, limit_per_form, raw_dir):
        if forms == ("DEF 14A",):
            return [{
                "accessionNumber": accession,
                "primaryDocument": "proxy.htm",
                "filingDate": "2024-05-01",
            }]
        return []

    monkeypatch.setattr(management, "list_filing_docs", list_docs)
    monkeypatch.setattr(
        management,
        "parse_proxy",
        lambda content: SimpleNamespace(executives=[], directors=[], warnings=[]),
    )
    store = _Store()

    management.sync_management("AAPL", fetch=False, store=store, raw_dir=raw)

    assert len(store.source_rows) == 1
    assert store.source_rows[0]["fetched_at"] == "2024-05-06T07:08:09+00:00"
    assert store.source_rows[0]["local_path"] == str(expected_path)


def test_refresh_releases_locks_when_identity_precheck_fails(monkeypatch, tmp_path, db):
    from equitylens.refresh import service

    stable = {module: None for module in service.MODULES}
    calls = 0

    def identity_snapshot(store, company_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("identity query failed")
        return stable

    monkeypatch.setattr(service, "_identity_snapshot", identity_snapshot)
    monkeypatch.setattr(service, "_run_module", lambda *args, **kwargs: {})

    with __import__("pytest").raises(RuntimeError, match="identity query failed"):
        service.refresh_company(db, "AAPL", modules=["financials"], raw_dir=tmp_path / "raw")

    result = service.refresh_company(
        db, "AAPL", modules=["financials"], raw_dir=tmp_path / "raw"
    )
    assert result["status"] == "ok"
