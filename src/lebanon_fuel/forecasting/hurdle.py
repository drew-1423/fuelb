"""Two-Stage Hurdle Model architecture for calendar horizons.

Stage 1 (Hazard / Announcement Classifier):
Estimates P(Decree Issued on Day t | X) based on day-of-week (Tuesday/Wednesday/Friday
announcement patterns), elapsed days since last decree, and cumulative international
market moves.

Stage 2 (Magnitude Regressor):
Models the conditional expected change E[Delta P_t | Decree_t = 1] given that a decree occurs.

Combined Hurdle Forecast:
E[Delta P_t] = P(Decree_t = 1) * E[Delta P_t | Decree_t = 1], with a zero-change threshold
to maintain 0.0 LBP error on silent days so models beat persistence on calendar horizons.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

def weights(frame):
    if "base_revision_id" not in frame or frame.empty:
        return np.ones(len(frame), dtype=float)
    counts = frame.groupby("base_revision_id").base_revision_id.transform("size")
    return 1.0 / np.maximum(counts.to_numpy(float), 1.0)


# Key decree issuance weekdays in Lebanon:
# Tuesday (1) and Friday (4) are standard announcement days.
# Wednesday (2) is common effective date when signed Tuesday evening.
DECREE_WEEKDAYS = {1, 2, 4}
WEEKEND_WEEKDAYS = {5, 6}


def forward_window_decree_days(weekday: int, horizon_days: int) -> int:
    """Count how many potential decree weekdays fall within the forward calendar window."""
    return sum(1 for step in range(1, horizon_days + 1) if (weekday + step) % 7 in DECREE_WEEKDAYS)


def forward_window_weekend_days(weekday: int, horizon_days: int) -> int:
    """Count how many weekend days fall within the forward calendar window."""
    return sum(1 for step in range(1, horizon_days + 1) if (weekday + step) % 7 in WEEKEND_WEEKDAYS)


def hazard_features(frame: pd.DataFrame, horizon_days: int = 1) -> Tuple[np.ndarray, List[str]]:
    """Construct leak-free Stage 1 features for decree hazard estimation."""
    names = [
        "decree_days_in_window",
        "weekend_days_in_window",
        "is_decree_day",
        "is_weekend",
        "is_tuesday",
        "is_wednesday",
        "is_friday",
        "weekday_sin",
        "weekday_cos",
        "days_since_source_date",
        "days_since_ratio",
        "days_since_sq",
        "structural_cost_gap",
        "abs_cost_gap",
        "structural_delta_lbp",
        "abs_structural_delta",
        "brent_return7",
        "abs_brent_return7",
        "nyh_return7",
        "domestic_change_lag1",
        "abs_domestic_lag1",
        "fiscal_shock_lag1",
    ]

    w = frame.x_weekday.to_numpy(int) if "x_weekday" in frame else np.zeros(len(frame), int)
    days_since = frame.x_days_since_source_date.fillna(1.0).to_numpy(float) if "x_days_since_source_date" in frame else np.ones(len(frame), float)
    median_int = frame.x_interval_median.fillna(7.0).to_numpy(float) if "x_interval_median" in frame else np.full(len(frame), 7.0)

    decree_window = np.array([forward_window_decree_days(int(day_w), horizon_days) for day_w in w], dtype=float)
    weekend_window = np.array([forward_window_weekend_days(int(day_w), horizon_days) for day_w in w], dtype=float)

    is_dec = np.isin(w, list(DECREE_WEEKDAYS)).astype(float)
    is_wnd = np.isin(w, list(WEEKEND_WEEKDAYS)).astype(float)
    is_tue = (w == 1).astype(float)
    is_wed = (w == 2).astype(float)
    is_fri = (w == 4).astype(float)
    w_sin = np.sin(2 * np.pi * w / 7.0)
    w_cos = np.cos(2 * np.pi * w / 7.0)

    ratio = days_since / np.maximum(median_int, 1.0)
    sq = (days_since ** 2) / 100.0

    cost_gap = frame.x_structural_cost_gap.fillna(0.0).to_numpy(float) if "x_structural_cost_gap" in frame else np.zeros(len(frame), float)
    delta = frame.x_structural_delta_lbp_20l.fillna(0.0).to_numpy(float) if "x_structural_delta_lbp_20l" in frame else np.zeros(len(frame), float)
    brent = frame.x_brent_spot_return7.fillna(0.0).to_numpy(float) if "x_brent_spot_return7" in frame else np.zeros(len(frame), float)
    nyh = frame.x_nyh_gasoline_return7.fillna(0.0).to_numpy(float) if "x_nyh_gasoline_return7" in frame else np.zeros(len(frame), float)
    lag1 = frame.x_domestic_change_lag1.fillna(0.0).to_numpy(float) if "x_domestic_change_lag1" in frame else np.zeros(len(frame), float)
    shock = frame.x_fiscal_shock_lag1.fillna(0.0).to_numpy(float) if "x_fiscal_shock_lag1" in frame else np.zeros(len(frame), float)

    matrix = np.column_stack([
        decree_window,
        weekend_window,
        is_dec,
        is_wnd,
        is_tue,
        is_wed,
        is_fri,
        w_sin,
        w_cos,
        days_since,
        ratio,
        sq,
        cost_gap,
        np.abs(cost_gap),
        delta,
        np.abs(delta),
        brent,
        np.abs(brent),
        nyh,
        lag1,
        np.abs(lag1),
        shock,
    ])
    return matrix, names


def magnitude_features(frame: pd.DataFrame) -> Tuple[np.ndarray, List[str]]:
    """Construct leak-free Stage 2 features for conditional price change magnitude."""
    names = [
        "structural_delta_lbp",
        "structural_cost_gap",
        "domestic_change_lag1",
        "fiscal_shock_lag1",
        "brent_return7",
        "nyh_return7",
        "days_since_source_date",
    ]
    delta = frame.x_structural_delta_lbp_20l.fillna(0.0).to_numpy(float) if "x_structural_delta_lbp_20l" in frame else np.zeros(len(frame), float)
    cost_gap = frame.x_structural_cost_gap.fillna(0.0).to_numpy(float) if "x_structural_cost_gap" in frame else np.zeros(len(frame), float)
    lag1 = frame.x_domestic_change_lag1.fillna(0.0).to_numpy(float) if "x_domestic_change_lag1" in frame else np.zeros(len(frame), float)
    shock = frame.x_fiscal_shock_lag1.fillna(0.0).to_numpy(float) if "x_fiscal_shock_lag1" in frame else np.zeros(len(frame), float)
    brent = frame.x_brent_spot_return7.fillna(0.0).to_numpy(float) if "x_brent_spot_return7" in frame else np.zeros(len(frame), float)
    nyh = frame.x_nyh_gasoline_return7.fillna(0.0).to_numpy(float) if "x_nyh_gasoline_return7" in frame else np.zeros(len(frame), float)
    days_since = frame.x_days_since_source_date.fillna(1.0).to_numpy(float) if "x_days_since_source_date" in frame else np.ones(len(frame), float)

    matrix = np.column_stack([
        delta,
        cost_gap,
        lag1,
        shock,
        brent,
        nyh,
        days_since,
    ])
    return matrix, names


@dataclass
class HazardClassifier:
    """Stage 1: Announcement Classifier / Hazard Model."""
    horizon_days: int = 1
    scaler: StandardScaler = field(default_factory=StandardScaler)
    model: Optional[LogisticRegression] = None
    degenerate_prob: Optional[float] = None
    feature_names: List[str] = field(default_factory=list)
    feature_weights: Dict[str, float] = field(default_factory=dict)

    def fit(self, frame: pd.DataFrame, target: np.ndarray, sample_weight: Optional[np.ndarray] = None):
        X, names = hazard_features(frame, self.horizon_days)
        self.feature_names = names
        unique_classes = np.unique(target)

        # Single class edge cases (e.g. 100% decree on day_14, or 0% decree on short windows)
        if len(unique_classes) <= 1:
            self.degenerate_prob = float(unique_classes[0]) if len(unique_classes) == 1 else 0.5
            self.model = None
            return self

        # Insufficient positive or negative samples
        pos_count = int(np.sum(target == 1))
        neg_count = int(np.sum(target == 0))
        if pos_count < 3 or neg_count < 3:
            self.degenerate_prob = float(pos_count / max(1, len(target)))
            self.model = None
            return self

        self.degenerate_prob = None
        X_scaled = self.scaler.fit_transform(X)
        self.model = LogisticRegression(C=1.0, max_iter=500, random_state=42)
        self.model.fit(X_scaled, target, sample_weight=sample_weight)

        if hasattr(self.model, "coef_"):
            self.feature_weights = {
                name: float(w) for name, w in zip(self.feature_names, self.model.coef_[0])
            }
        return self

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        if self.degenerate_prob is not None:
            return np.full(len(frame), self.degenerate_prob, dtype=float)
        X, _ = hazard_features(frame, self.horizon_days)
        X_scaled = self.scaler.transform(X)
        probs = self.model.predict_proba(X_scaled)[:, 1]
        return np.clip(probs, 0.0, 1.0)


@dataclass
class MagnitudeRegressor:
    """Stage 2: Conditional Magnitude Regressor for E[Delta P | Decree = 1]."""
    scaler: StandardScaler = field(default_factory=StandardScaler)
    model: Optional[Ridge] = None
    fallback_mean: float = 0.0
    feature_names: List[str] = field(default_factory=list)
    feature_weights: Dict[str, float] = field(default_factory=dict)

    def fit(self, frame: pd.DataFrame, target: np.ndarray, sample_weight: Optional[np.ndarray] = None, alpha: float = 50.0):
        X, names = magnitude_features(frame)
        self.feature_names = names

        if len(frame) < 5 or not np.isfinite(target).any():
            self.fallback_mean = float(np.nanmean(target)) if len(target) and np.isfinite(target).any() else 0.0
            self.model = None
            return self

        self.fallback_mean = float(np.average(target, weights=sample_weight)) if sample_weight is not None else float(np.mean(target))
        X_scaled = self.scaler.fit_transform(X)
        self.model = Ridge(alpha=alpha, random_state=42)
        self.model.fit(X_scaled, target, sample_weight=sample_weight)

        if hasattr(self.model, "coef_"):
            self.feature_weights = {
                name: float(w) for name, w in zip(self.feature_names, self.model.coef_)
            }
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            return np.full(len(frame), self.fallback_mean, dtype=float)
        X, _ = magnitude_features(frame)
        X_scaled = self.scaler.transform(X)
        return np.asarray(self.model.predict(X_scaled), float)


@dataclass
class HurdleModel:
    """Combined Two-Stage Hurdle Model.

    Combined hurdle forecast:
        E[Delta P_t] = P(Decree_t = 1) * E[Delta P_t | Decree_t = 1]

    With zero-change thresholding:
        If P(Decree_t = 1) < prob_threshold OR |E[Delta P_t]| < change_threshold_lbp:
            Forecast = 0.0 LBP
    """
    family: str = "I_hurdle"
    horizon: str = "day_1"
    horizon_days: int = 1
    prob_threshold: Optional[float] = None
    change_threshold_lbp: float = 3000.0
    hazard: HazardClassifier = field(default_factory=HazardClassifier)
    magnitude: MagnitudeRegressor = field(default_factory=MagnitudeRegressor)
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if "_" in self.horizon:
            kind, n = self.horizon.split("_", 1)
            if kind == "day":
                self.horizon_days = max(1, int(n))
        self.hazard.horizon_days = self.horizon_days

    def fit(self, frame: pd.DataFrame, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        horizon = str(frame.horizon.iloc[0]) if "horizon" in frame and not frame.empty else self.horizon
        self.horizon = horizon
        if "_" in horizon:
            kind, n = horizon.split("_", 1)
            self.horizon_days = int(n) if kind == "day" else 1
        self.hazard.horizon_days = self.horizon_days

        # Horizon-specific default thresholds:
        # Day 1: higher threshold (0.50) because 85% of days are silent
        # Day 3: threshold 0.45
        # Day 7 & 14: threshold 0.20-0.25 because decrees occur within almost all windows
        threshold_map = {"day_1": 0.50, "day_3": 0.45, "day_7": 0.25, "day_14": 0.15}
        configured_tau = cfg.get("hurdle", {}).get("prob_threshold")
        if configured_tau is not None:
            self.prob_threshold = configured_tau
        elif self.prob_threshold is None:
            self.prob_threshold = threshold_map.get(self.horizon, 0.40)
        self.change_threshold_lbp = cfg.get("hurdle", {}).get("change_threshold_lbp", self.change_threshold_lbp)

        # Target and decree indicator
        y = frame.target_change_lbp_20l.to_numpy(float)
        w = weights(frame)

        # Decree indicator: observed update or non-zero price move
        has_updates = "observed_updates" in frame
        decree = ((frame.observed_updates > 0) | (y != 0.0)).astype(int).to_numpy() if has_updates else (y != 0.0).astype(int)

        # Fit Stage 1: Hazard Classifier
        self.hazard.fit(frame, decree, sample_weight=w)

        # Fit Stage 2: Conditional Magnitude Regressor
        mask = (decree == 1)
        if mask.sum() >= 8:
            frame_decree = frame[mask].copy()
            y_decree = y[mask]
            w_decree = w[mask]
            self.magnitude.fit(frame_decree, y_decree, sample_weight=w_decree)
        else:
            # Fallback to unconditional fit if decree samples are scarce
            self.magnitude.fit(frame, y, sample_weight=w, alpha=200.0)

        self.extra = {
            "family": self.family,
            "horizon": self.horizon,
            "horizon_days": self.horizon_days,
            "prob_threshold": self.prob_threshold,
            "change_threshold_lbp": self.change_threshold_lbp,
            "train_rows": len(frame),
            "decree_rows": int(mask.sum()),
            "silent_rows": int((decree == 0).sum()),
            "decree_prior": float(np.mean(decree)),
            "hazard_features": self.hazard.feature_names,
            "hazard_weights": self.hazard.feature_weights,
            "magnitude_features": self.magnitude.feature_names,
            "magnitude_weights": self.magnitude.feature_weights,
            "maximum_training_label_end": frame.label_end.max() if "label_end" in frame else None,
            "first_training_origin": frame.origin.min() if "origin" in frame else None,
            "last_training_origin": frame.origin.max() if "origin" in frame else None,
        }
        return self

    def predict_hazard(self, frame: pd.DataFrame) -> np.ndarray:
        """Estimate P(Decree Issued on Day t | X)."""
        return self.hazard.predict_proba(frame)

    def predict_magnitude(self, frame: pd.DataFrame) -> np.ndarray:
        """Estimate conditional change E[Delta P_t | Decree_t = 1]."""
        return self.magnitude.predict(frame)

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        """Compute the combined Hurdle forecast with zero-change thresholding."""
        p = self.predict_hazard(frame)
        mag = self.predict_magnitude(frame)
        expected = p * mag

        # Zero-change threshold:
        # If probability is below hurdle OR expected change is below deadband:
        # maintain exact 0.0 LBP forecast to eliminate errors on silent days.
        silent_mask = (p < self.prob_threshold) | (np.abs(expected) < self.change_threshold_lbp)
        forecast = np.where(silent_mask, 0.0, expected)
        return forecast

    def quantiles(self, frame: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Produce asymmetric/conformal prediction intervals conditioned on hurdle status."""
        p = self.predict_hazard(frame)
        point = self.predict(frame)
        floor = self.change_threshold_lbp

        # On silent days (p < prob_threshold), interval is tight around 0
        # On decree days, interval expands with expected magnitude uncertainty
        half_width = np.where(p < self.prob_threshold, floor, np.maximum(floor * 2, np.abs(point) * 0.5 + floor))
        return point - half_width, point + half_width
