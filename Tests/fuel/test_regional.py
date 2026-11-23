"""Unit tests for regional Mediterranean benchmark proxy support and evaluation."""
from pathlib import Path
from contextlib import closing
import json
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]

from lebanon_fuel.market.regional import (
    extract_mediterranean_series,
    med_crack_spread,
    evaluate_regional_benchmarks,
    generate_regional_evaluation_report,
)


class MockStore:
    def __init__(self, it_rows=None, gr_rows=None, fx_rows=None, brent_rows=None, nyh_rows=None, ledger_rows=None):
        self.it_rows = it_rows or []
        self.gr_rows = gr_rows or []
        self.fx_rows = fx_rows or []
        self.brent_rows = brent_rows or []
        self.nyh_rows = nyh_rows or []
        self.ledger_rows = ledger_rows or []

    def history(self, series_id, as_of, mode="research"):
        if series_id == "italy_gasoline_ex_tax":
            return self.it_rows
        elif series_id == "greece_gasoline_ex_tax":
            return self.gr_rows
        elif series_id == "eurusd":
            return self.fx_rows
        elif series_id == "brent_spot":
            return self.brent_rows
        elif series_id == "nyh_gasoline":
            return self.nyh_rows
        return []

    def ledger(self):
        return self.ledger_rows


def test_extract_mediterranean_series_empty():
    store = MockStore()
    df = extract_mediterranean_series(store)
    assert df.empty


def test_extract_mediterranean_series_math_and_conversions():
    # 1 EUR/L, EUR/USD = 1.10
    # Expected USD/1000L = 1.0 * 1.10 * 1000 = 1100.0
    # Expected USD/bbl = 1100.0 * 158.987295 / 1000 = 174.8860245
    it_rows = [{"observation_date": "2026-01-05", "value": 1.0}]
    gr_rows = [{"observation_date": "2026-01-05", "value": 1.2}]
    fx_rows = [{"observation_date": "2026-01-05", "value": 1.10}]

    store = MockStore(it_rows=it_rows, gr_rows=gr_rows, fx_rows=fx_rows)
    df = extract_mediterranean_series(store)

    assert len(df) == 1
    assert df.iloc[0]["it_eur_l"] == 1.0
    assert df.iloc[0]["gr_eur_l"] == 1.2
    assert df.iloc[0]["med_eur_l"] == pytest.approx(1.10)  # average of 1.0 and 1.2
    assert df.iloc[0]["eurusd"] == 1.10

    # Conversions
    assert df.iloc[0]["it_usd_1000l"] == pytest.approx(1100.0)
    assert df.iloc[0]["gr_usd_1000l"] == pytest.approx(1320.0)
    assert df.iloc[0]["med_usd_1000l"] == pytest.approx(1210.0)

    barrel_factor = 158.987295 / 1000.0
    assert df.iloc[0]["med_usd_bbl"] == pytest.approx(1210.0 * barrel_factor)
    assert df.iloc[0]["med_usd_20l"] == pytest.approx(1210.0 * 0.02)


def test_extract_mediterranean_series_single_country_fallback():
    # Only Greece is present
    gr_rows = [{"observation_date": "2026-01-05", "value": 1.05}]
    fx_rows = [{"observation_date": "2026-01-05", "value": 1.08}]

    store = MockStore(gr_rows=gr_rows, fx_rows=fx_rows)
    df = extract_mediterranean_series(store)

    assert len(df) == 1
    assert np.isnan(df.iloc[0]["it_eur_l"])
    assert df.iloc[0]["gr_eur_l"] == 1.05
    assert df.iloc[0]["med_eur_l"] == pytest.approx(1.05)
    assert df.iloc[0]["med_usd_1000l"] == pytest.approx(1.05 * 1.08 * 1000.0)


def test_med_crack_spread():
    med_bbl = pd.Series([120.0, 130.0, 110.0])
    brent_bbl = pd.Series([80.0, 85.0, 75.0])
    spread = med_crack_spread(med_bbl, brent_bbl)
    np.testing.assert_allclose(spread, [40.0, 45.0, 35.0])


def test_evaluate_regional_benchmarks_live_store():
    from lebanon_fuel.market.store import MarketStore
    store = MarketStore(ROOT, readonly=True)
    try:
        report = evaluate_regional_benchmarks(store, start_date="2023-05-12")
        assert report["status"] == "evaluated"
        assert report["observations_matched"] > 50
        assert "med_composite_usd_bbl" in report["benchmarks"]
        assert "brent_crude_usd_bbl" in report["benchmarks"]
        assert "nyh_gasoline_usd_bbl" in report["benchmarks"]

        med_bm = report["benchmarks"]["med_composite_usd_bbl"]
        assert med_bm["level_pearson_correlation"] > 0.80
        assert med_bm["diff_pearson_correlation"] > 0.10

        # Mediterranean ranking should outperform transatlantic NYH
        ranking = report["performance_ranking_by_diff_correlation"]
        assert "med_composite_usd_bbl" in ranking
        med_idx = ranking.index("med_composite_usd_bbl")
        nyh_idx = ranking.index("nyh_gasoline_usd_bbl")
        assert med_idx < nyh_idx  # Higher ranking

        # Mediterranean crack spread summary
        cs = report["mediterranean_crack_spread"]
        assert cs is not None
        assert cs["sample_size"] > 50
        assert cs["mean_usd_bbl"] > 0
    finally:
        store.close()


def test_generate_regional_evaluation_report(tmp_path):
    from lebanon_fuel.market.store import MarketStore
    store = MarketStore(ROOT, readonly=True)
    try:
        report_path = generate_regional_evaluation_report(tmp_path, store=store)
        assert report_path.exists()
        payload = json.loads(report_path.read_text())
        assert payload["status"] == "evaluated"
        assert "benchmarks" in payload
    finally:
        store.close()


@pytest.mark.parametrize('damage', ['missing', 'checksum'])
def test_operations_audit_rejects_missing_or_modified_capture(tmp_path, damage):
    from lebanon_fuel.market.store import MarketStore
    from lebanon_fuel.automation.maintenance import audit

    with closing(MarketStore(tmp_path)) as store:
        capture_id = store.capture('ipt', 'https://example.org/test-capture', b'original evidence', 'text/html')
        raw = store.db.execute('SELECT raw_path FROM captures WHERE id=?', (capture_id,)).fetchone()[0]
    path = tmp_path / raw
    if damage == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'changed evidence')
    settings = {'storage': {'database': 'data/lebanon_fuel.sqlite'},
                'validation': {'forecast_ledger': 'data/forecast_ledger.sqlite'}}
    with pytest.raises(ValueError, match='Raw capture checksum mismatch'):
        audit(tmp_path, settings)
