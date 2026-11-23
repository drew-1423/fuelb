from datetime import date
import json

import httpx
import pytest

from lebanon_fuel.ingestion.http import Fetch
from lebanon_fuel.market.collectors import (collect_cboe_ovx, collect_fred_ovx,
    collect_options_chain, fred_ovx_rows, parse_occ_option_symbol)
from lebanon_fuel.market.cli import main as market_main
from lebanon_fuel.market.store import MarketStore


@pytest.fixture
def store(tmp_path):
    db = MarketStore(tmp_path)
    yield db
    db.close()


def test_occ_symbol():
    assert parse_occ_option_symbol("USO   261218C00075500") == (date(2026, 12, 18), "call", 75.5)
    with pytest.raises(ValueError):
        parse_occ_option_symbol("USO261218X00075500")


def test_ovx_close_and_capture_clocks(store):
    class Client:
        def fetch(self, url):
            raw = b"DATE,OPEN,HIGH,LOW,CLOSE\n11/11/2026,38,39,37,38.42\n2026-11-12,39,40,38,39.75\n"
            response = httpx.Response(200, content=raw, request=httpx.Request("GET", url))
            capture = store.capture("market_cboe", url, raw, "text/csv", http_status=200,
                                    retrieved_at="2026-11-12T19:00:00+00:00")
            return Fetch(response, capture)

    result = collect_cboe_ovx(store, Client())
    assert result["rows_ingested"] == 1
    assert collect_cboe_ovx(store, Client())["new_observations"] == 0
    assert store.history("cboe_ovx", "2026-11-11T23:59:58+00:00", "as_of_close") == []
    row, = store.history("cboe_ovx", "2026-11-11T23:59:59+00:00", "as_of_close")
    assert (row["available_at"], row["value"], row["unit"]) == (
        "2026-11-11T23:59:59+00:00", 38.42, "percent_annualized")
    assert store.history("cboe_ovx", "2026-11-11T23:59:59+00:00") == []


def test_network_failure_preserves_rows(store):
    cap = store.capture("market_eia", "https://example.com", b"existing", "text/plain")
    store.ingest_market(cap, "brent_spot", [dict(date="2025-01-01", value=75, row_key="1")])
    def snapshot():
        return [store.db.execute(f"SELECT * FROM {table}").fetchall()
                for table in ("captures", "market_observations", "market_sightings")]
    before = snapshot()
    class Offline:
        def fetch(self, url):
            raise httpx.ConnectError("offline")
    assert collect_cboe_ovx(store, Offline())["status"] == "error"
    assert snapshot() == before


@pytest.mark.parametrize("header", ["observation_date,OVXCLS", "DATE,OVXCLS"])
def test_fred_ovx_csv_skips_missing_rows_and_uses_daily_close(header):
    raw = f"{header}\n2026-11-10,31.25\n2026-11-11,.\n2026-11-12,\n".encode()
    rows = fred_ovx_rows(raw, __import__('datetime').datetime.fromisoformat("2026-11-13T12:00:00+00:00"))
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-11-10"
    assert rows[0]["raw"]["assumed_close_utc"] == "2026-11-10T23:59:59+00:00"


@pytest.mark.parametrize("payload,expected_format", [
    (b"Date,Open,High,Low,Close\n11/10/2026,30,32,29,31.5\n", "cboe"),
    (b"observation_date,OVXCLS\n2026-11-10,31.5\n2026-11-11,.\n", "fred"),
])
def test_cli_cboe_input_imports_detected_csv(store, tmp_path, capsys, payload, expected_format):
    source = tmp_path / "ovx.csv"
    source.write_bytes(payload)
    assert market_main(["--root", str(tmp_path), "collect", "--source", "cboe", "--input", str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok"
    assert result["format"] == expected_format
    expected_source = "market_fred_ovx" if expected_format == "fred" else "market_cboe"
    assert result["source_id"] == expected_source
    capture = store.db.execute("SELECT * FROM captures WHERE id=?", (result["capture_id"],)).fetchone()
    assert capture["source_id"] == expected_source
    metadata = json.loads(capture["metadata_json"])
    assert metadata["status"] == "ok"
    assert metadata["local_path"] == str(source.resolve())
    assert metadata["input_sha256"] == capture["sha256"]
    assert store.db.execute("SELECT count(*) FROM market_observations WHERE series_id='cboe_ovx'").fetchone()[0] == 1


def test_cli_cboe_input_missing_file_is_json_error_and_non_destructive(tmp_path, capsys):
    db = MarketStore(tmp_path)
    try:
        before = db.db.execute("SELECT count(*) FROM captures").fetchone()[0]
        code = market_main(["--root", str(tmp_path), "collect", "--source", "cboe", "--input", str(tmp_path / "missing.csv")])
        result = json.loads(capsys.readouterr().out)
        assert code == 1
        assert result["status"] == "error"
        assert result["error"].startswith("FileNotFoundError:")
        assert result["capture_id"] is None
        assert db.db.execute("SELECT count(*) FROM captures").fetchone()[0] == before
    finally:
        db.close()


def test_cli_fred_collect_uses_public_client_and_ingests(store, tmp_path, monkeypatch, capsys):
    import lebanon_fuel.market.collectors as collectors

    class MockPublicClient:
        def __init__(self, db, source, run):
            self.db, self.source, self.run = db, source, run

        def fetch(self, url):
            raw = b"observation_date,OVXCLS\n2026-11-10,31.25\n2026-11-11,.\n"
            capture = self.db.capture(self.source, url, raw, "text/csv", self.run,
                200, retrieved_at="2026-11-13T10:00:00+00:00")
            return Fetch(httpx.Response(200, content=raw, request=httpx.Request("GET", url)), capture)

        def close(self):
            pass

    monkeypatch.setattr(collectors, "PublicClient", MockPublicClient)
    assert market_main(["--root", str(store.root), "collect", "--source", "fred"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok"
    assert result["source_id"] == "market_fred_ovx"
    assert result["fred_series_id"] == "OVXCLS"
    assert result["rows_ingested"] == 1
    assert result["source_url"] == "https://fred.stlouisfed.org/graph/fredgraph.csv?id=OVXCLS"
    cap = store.db.execute("SELECT source_id FROM captures WHERE id=?", (result["capture_id"],)).fetchone()
    assert cap["source_id"] == "market_fred_ovx"
    assert store.history("cboe_ovx", "2026-11-10T23:59:58+00:00", "as_of_close") == []
    close_row, = store.history("cboe_ovx", "2026-11-10T23:59:59+00:00", "as_of_close")
    assert close_row["available_at"] == "2026-11-10T23:59:59+00:00"
    assert store.history("cboe_ovx", "2026-11-10T23:59:59+00:00", "strict") == []


def test_cli_cboe_input_invalid_headers_does_not_create_capture(tmp_path, capsys):
    db = MarketStore(tmp_path)
    try:
        source = tmp_path / "invalid.csv"
        source.write_text("day,close_value\n2026-11-10,31\n")
        before = db.db.execute("SELECT count(*) FROM captures").fetchone()[0]
        assert market_main(["--root", str(tmp_path), "collect", "--source", "cboe", "--input", str(source)]) == 1
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "error"
        assert "headers" in result["error"]
        assert db.db.execute("SELECT count(*) FROM captures").fetchone()[0] == before
    finally:
        db.close()


def test_options_export_and_failed_import_preserves_previous_file(store, tmp_path):
    source = tmp_path / "chain.json"
    def quote(contract, iv=.41, bid=2, oi=10):
        return dict(option="USO" + contract, iv=iv, bid=bid, ask=3, open_interest=oi)
    source.write_text(json.dumps({"data": {"current_price": 75, "options": [
        quote("261218C00075000"), quote("261218P00072000", oi=0),
        quote("261116C00075000"), quote("270219C00075000"),
        quote("261218P00070000", bid=0, oi=0), quote("261218C00080000", iv=0),
    ]}}))
    result = collect_options_chain(store, input_path=source, as_of_date=date(2026, 11, 13))
    assert result["contracts_filtered"] == 2
    assert result["atm_30d_iv"] == .41
    target = tmp_path / "data/exports/options_chain_latest.json"
    assert json.loads(target.read_text()) == result
    previous = target.read_bytes()
    source.write_text("{bad json")
    assert collect_options_chain(store, input_path=source)["status"] == "error"
    assert target.read_bytes() == previous
    assert list(target.parent.iterdir()) == [target]
