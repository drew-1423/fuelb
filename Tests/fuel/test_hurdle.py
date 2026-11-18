"""Comprehensive unit tests for the Two-Stage Hurdle Model architecture."""
from datetime import date, timedelta
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest

from lebanon_fuel.forecasting.hurdle import (
    HazardClassifier,
    MagnitudeRegressor,
    HurdleModel,
    forward_window_decree_days,
    forward_window_weekend_days,
    hazard_features,
    magnitude_features,
)
from lebanon_fuel.forecasting.models import fit_model, Model

ROOT = Path(__file__).parents[2]
CONFIG = json.loads((ROOT / "config/forecasting_research.json").read_text())


def synthetic_frame(n=100, horizon="day_1"):
    """Generate synthetic design data with realistic decree and price patterns."""
    days = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    weekdays = days.day_of_week.to_numpy()
    h_days = int(horizon.split("_")[1])

    # Decrees typically occur on Tue (1), Wed (2), Fri (4)
    decree_prob = np.where(np.isin(weekdays, [1, 2, 4]), 0.6, 0.05)
    if h_days >= 7:
        decree_prob = np.clip(decree_prob + 0.35, 0.0, 1.0)
    rng = np.random.default_rng(42)
    decree = rng.binomial(1, decree_prob)

    # Days since source date: cycles from 1 to 7
    days_since = (np.arange(n) % 7) + 1
    # Base price: ~1,500,000 LBP
    base_price = 1500000.0

    # International market signals
    structural_delta = rng.normal(15000.0, 8000.0, size=n)
    cost_gap = rng.normal(1.5, 0.8, size=n)
    brent_ret = rng.normal(0.02, 0.03, size=n)
    nyh_ret = rng.normal(0.02, 0.04, size=n)
    dom_lag = np.r_[0.0, structural_delta[:-1]]

    # Target price change: exactly 0 if no decree, otherwise proportional to structural delta
    target_change = np.where(decree == 1, 0.8 * structural_delta + 0.2 * dom_lag + rng.normal(0, 1000, n), 0.0)

    return pd.DataFrame({
        "origin": days.astype(str),
        "label_end": (days + pd.Timedelta(days=h_days)).astype(str),
        "horizon": horizon,
        "base_revision_id": np.arange(n) // 4,
        "base_price_lbp_20l": base_price,
        "target_change_lbp_20l": np.round(target_change, -2),
        "observed_updates": decree,
        "x_weekday": weekdays,
        "x_days_since_source_date": days_since,
        "x_interval_median": np.full(n, 7.0),
        "x_structural_cost_gap": cost_gap,
        "x_structural_delta_lbp_20l": structural_delta,
        "x_brent_spot_return7": brent_ret,
        "x_nyh_gasoline_return7": nyh_ret,
        "x_domestic_change_lag1": dom_lag,
        "x_fiscal_shock_lag1": np.zeros(n),
    })


def test_forward_window_decree_days():
    # Monday is 0, Tuesday is 1, Friday is 4
    # Day 1 horizon:
    # From Monday (0), day +1 is Tuesday (1) -> 1 decree day
    assert forward_window_decree_days(0, 1) == 1
    # From Friday (4), day +1 is Saturday (5) -> 0 decree days
    assert forward_window_decree_days(4, 1) == 0
    # From Saturday (5), day +1 is Sunday (6) -> 0 decree days
    assert forward_window_decree_days(5, 1) == 0

    # Day 3 horizon:
    # From Monday (0): Tue(1), Wed(2), Thu(3) -> 2 decree days (Tue, Wed)
    assert forward_window_decree_days(0, 3) == 2
    # From Thursday (3): Fri(4), Sat(5), Sun(6) -> 1 decree day (Fri)
    assert forward_window_decree_days(3, 3) == 1
    # From Friday (4): Sat(5), Sun(6), Mon(0) -> 0 decree days
    assert forward_window_decree_days(4, 3) == 0

    # Day 7 horizon:
    # Full week always contains Tue(1), Wed(2), Fri(4) -> 3 decree days
    for w in range(7):
        assert forward_window_decree_days(w, 7) == 3


def test_hazard_features_shape_and_names():
    frame = synthetic_frame(50, "day_1")
    X, names = hazard_features(frame, horizon_days=1)
    assert X.shape == (50, len(names))
    assert "decree_days_in_window" in names
    assert "is_tuesday" in names
    assert "is_friday" in names
    assert "days_since_source_date" in names
    assert "structural_delta_lbp" in names
    assert np.isfinite(X).all()


def test_hazard_classifier_probability_calibration_and_patterns():
    frame = synthetic_frame(120, "day_1")
    target = frame.observed_updates.to_numpy()

    clf = HazardClassifier(horizon_days=1).fit(frame, target)
    probs = clf.predict_proba(frame)

    assert len(probs) == len(frame)
    assert ((probs >= 0.0) & (probs <= 1.0)).all()

    # Decrees should have higher mean probability than silent days
    p_decree = probs[target == 1]
    p_silent = probs[target == 0]
    assert np.mean(p_decree) > np.mean(p_silent)

    # Feature weights inspection
    assert len(clf.feature_weights) > 0


def test_hazard_classifier_single_class_edge_cases():
    frame = synthetic_frame(40, "day_14")

    # Edge case 1: All ones (decree guaranteed, e.g. day 14)
    clf_all_ones = HazardClassifier(horizon_days=14).fit(frame, np.ones(len(frame)))
    probs_ones = clf_all_ones.predict_proba(frame)
    assert clf_all_ones.degenerate_prob == 1.0
    np.testing.assert_allclose(probs_ones, 1.0)

    # Edge case 2: All zeros (silent period)
    clf_all_zeros = HazardClassifier(horizon_days=1).fit(frame, np.zeros(len(frame)))
    probs_zeros = clf_all_zeros.predict_proba(frame)
    assert clf_all_zeros.degenerate_prob == 0.0
    np.testing.assert_allclose(probs_zeros, 0.0)


def test_hazard_classifier_monotonic_elapsed_days():
    # Construct rows on the same weekday with increasing days_since_source_date
    frame = pd.DataFrame({
        "x_weekday": [1, 1, 1, 1],  # Tuesday
        "x_days_since_source_date": [1.0, 3.0, 7.0, 10.0],
        "x_interval_median": [7.0, 7.0, 7.0, 7.0],
        "x_structural_cost_gap": [1.0, 1.0, 1.0, 1.0],
        "x_structural_delta_lbp_20l": [10000.0, 10000.0, 10000.0, 10000.0],
        "x_brent_spot_return7": [0.02, 0.02, 0.02, 0.02],
        "x_nyh_gasoline_return7": [0.02, 0.02, 0.02, 0.02],
        "x_domestic_change_lag1": [5000.0, 5000.0, 5000.0, 5000.0],
        "x_fiscal_shock_lag1": [0.0, 0.0, 0.0, 0.0],
        "observed_updates": [0, 0, 1, 1],
    })
    clf = HazardClassifier(horizon_days=1).fit(frame, frame.observed_updates.to_numpy())
    probs = clf.predict_proba(frame)
    # Probability should be higher when elapsed days is 7 or 10 than when it is 1
    assert probs[-1] >= probs[0]


def test_magnitude_regressor_conditioned_on_decree():
    frame = synthetic_frame(80, "day_1")
    target = frame.target_change_lbp_20l.to_numpy()
    mask = (frame.observed_updates == 1)

    reg = MagnitudeRegressor().fit(frame[mask], target[mask])
    preds = reg.predict(frame)

    assert len(preds) == len(frame)
    assert np.isfinite(preds).all()
    # Magnitude predictions should correlate with target on decree days
    corr = np.corrcoef(preds[mask], target[mask])[0, 1]
    assert corr > 0.40


def test_magnitude_regressor_scarce_fallback():
    # Only 2 observations
    frame = synthetic_frame(2, "day_1")
    target = np.array([12000.0, 14000.0])
    reg = MagnitudeRegressor().fit(frame, target)
    preds = reg.predict(frame)
    assert len(preds) == 2
    np.testing.assert_allclose(preds, 13000.0)


def test_hurdle_model_combined_forecast_and_thresholding():
    frame = synthetic_frame(120, "day_1")
    hurdle = HurdleModel(horizon="day_1", prob_threshold=0.45, change_threshold_lbp=3000.0)
    hurdle.fit(frame)

    assert hurdle.extra["train_rows"] == 120
    assert hurdle.extra["decree_rows"] > 0
    assert hurdle.extra["prob_threshold"] == 0.45

    probs = hurdle.predict_hazard(frame)
    mags = hurdle.predict_magnitude(frame)
    preds = hurdle.predict(frame)

    # Verification of hurdle formula:
    # Where p < threshold OR |p * mag| < change_threshold: forecast MUST be 0.0
    for i in range(len(frame)):
        p_i = probs[i]
        mag_i = mags[i]
        expected_raw = p_i * mag_i
        if p_i < 0.45 or abs(expected_raw) < 3000.0:
            assert preds[i] == 0.0
        else:
            assert preds[i] == pytest.approx(expected_raw)


def test_hurdle_model_prediction_intervals():
    frame = synthetic_frame(50, "day_1")
    hurdle = HurdleModel(horizon="day_1").fit(frame)
    low, high = hurdle.quantiles(frame)

    assert len(low) == len(frame)
    assert len(high) == len(frame)
    assert (low <= high).all()
    # Interval widths should be non-negative
    widths = high - low
    assert (widths >= hurdle.change_threshold_lbp).all()


def test_hurdle_model_integration_with_models_py():
    frame = synthetic_frame(100, "day_1")
    model = fit_model("I_hurdle", frame, CONFIG)

    assert isinstance(model, Model)
    assert model.family == "I_hurdle"
    assert isinstance(model.fitted, HurdleModel)

    test_frame = frame.tail(10).copy()
    preds = model.predict(test_frame)
    assert len(preds) == 10
    assert np.isfinite(preds).all()

    low, high = model.quantiles(test_frame)
    assert len(low) == 10
    assert (low <= high).all()


@pytest.mark.parametrize("horizon", ["day_1", "day_3", "day_7", "day_14"])
def test_hurdle_model_calendar_horizons(horizon):
    frame = synthetic_frame(100, horizon=horizon)
    hurdle = HurdleModel(horizon=horizon).fit(frame)
    preds = hurdle.predict(frame)
    assert len(preds) == len(frame)
    assert np.isfinite(preds).all()

    # On shorter calendar horizons (day_1, day_3), silent days predominate
    if horizon in {"day_1", "day_3"}:
        silent = frame.observed_updates == 0
        if silent.any():
            silent_preds = preds[silent]
            assert (silent_preds == 0.0).mean() >= 0.50
    else:
        # On longer calendar horizons (day_7, day_14), decrees are expected within the window
        assert (preds != 0.0).mean() >= 0.50


def test_hurdle_model_real_development_data():
    """Verify HurdleModel on actual project development design data across calendar horizons."""
    design_path = ROOT / "data/exports/forecasting/development_design.csv"
    if not design_path.exists():
        pytest.skip("development_design.csv not present")
    df = pd.read_csv(design_path)

    for horizon in ["day_1", "day_3", "day_7", "day_14"]:
        sub = df[df.horizon == horizon].sort_values("origin").copy()
        if len(sub) < 50:
            continue
        # Split chronologically
        n_train = int(len(sub) * 0.7)
        train = sub.iloc[:n_train].copy()
        test = sub.iloc[n_train:].copy()

        model = fit_model("I_hurdle", train, CONFIG)
        preds = model.predict(test)

        assert len(preds) == len(test)
        assert np.isfinite(preds).all()

        y_test = test.target_change_lbp_20l.to_numpy(float)
        baseline_mae = float(np.mean(np.abs(y_test)))
        hurdle_mae = float(np.mean(np.abs(preds - y_test)))

        # On day_1 and day_3, verify that Hurdle zero-threshold maintains low error on silent days
        silent = (test.target_change_lbp_20l == 0.0)
        if silent.any():
            silent_mae = float(np.mean(np.abs(preds[silent])))
            assert silent_mae <= 5000.0, f"Expected low silent-day MAE on {horizon}, got {silent_mae}"

