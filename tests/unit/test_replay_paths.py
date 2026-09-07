class _Store:
    def connect(self):
        return self

    def init_schema(self):
        pass

    def replace_insider_transactions(self, company_id, rows):
        pass

    def upsert_source_documents(self, rows):
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
