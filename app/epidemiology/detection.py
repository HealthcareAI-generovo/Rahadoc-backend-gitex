"""
Multi-layer anomaly detection for epidemiological surveillance.

Layer 1: Z-score statistical analysis (always available)
Layer 2: Isolation Forest machine learning (requires sufficient data)

Each layer operates independently and results are merged by the service.
"""
import logging
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import List, Dict, Tuple, Optional

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.epidemiology.aggregation import get_weekly_disease_counts
from app.epidemiology.geo import get_region_key
from app.epidemiology.schemas import (
    DetectedAnomaly,
    DetectionSource,
    AnomalySeverity,
    ScanConfig,
)

logger = logging.getLogger(__name__)

# Lazy import sklearn to avoid startup cost when ML is disabled
_isolation_forest_class = None


def _get_isolation_forest():
    """Lazy-load IsolationForest to avoid import cost on every request."""
    global _isolation_forest_class
    if _isolation_forest_class is None:
        try:
            from sklearn.ensemble import IsolationForest
            _isolation_forest_class = IsolationForest
        except ImportError:
            logger.warning("scikit-learn not installed — ML detection disabled")
            return None
    return _isolation_forest_class


# ──────────────────────────────────────────────
# Data grouping (shared by both layers)
# ──────────────────────────────────────────────

class RegionData:
    """Aggregated time-series data for a (region, disease) pair."""
    __slots__ = ("region", "h3_index", "disease", "weekly_counts")

    def __init__(self, region: str, h3_index: Optional[str], disease: str):
        self.region = region
        self.h3_index = h3_index
        self.disease = disease
        self.weekly_counts: Dict[date, int] = {}


def group_rows_by_region_disease(rows: List[Dict]) -> Dict[Tuple[str, str], RegionData]:
    """
    Group raw query rows into RegionData objects keyed by (region, disease).

    Uses H3 index for grouping when coordinates are available,
    otherwise falls back to ville.
    """
    grouped: Dict[Tuple[str, str], RegionData] = {}

    for row in rows:
        ville = row["ville"]
        lat = row.get("latitude")
        lng = row.get("longitude")
        disease = row["disease"]
        week_start = row["week_start"]
        count = row["case_count"]

        # Determine region key (ville name + optional H3)
        region_display, h3_index = get_region_key(ville, lat, lng)

        # Group key: use H3 if available for precision, else ville
        group_key = (h3_index or region_display, disease)

        if group_key not in grouped:
            grouped[group_key] = RegionData(
                region=region_display,
                h3_index=h3_index,
                disease=disease,
            )

        # Normalize week_start to date
        if isinstance(week_start, datetime):
            week_start = week_start.date()

        # Accumulate counts (multiple cabinets in same region)
        rd = grouped[group_key]
        rd.weekly_counts[week_start] = rd.weekly_counts.get(week_start, 0) + count

    return grouped


def _get_current_week_start() -> date:
    """Get the Monday of the current ISO week."""
    today = date.today()
    return today - timedelta(days=today.weekday())


# ──────────────────────────────────────────────
# Layer 1: Z-score detection
# ──────────────────────────────────────────────

def detect_zscore(
    grouped: Dict[Tuple[str, str], RegionData],
    config: ScanConfig,
) -> List[DetectedAnomaly]:
    """
    Z-score statistical anomaly detection.

    For each (region, disease) pair, compares the current week's count
    against a rolling historical baseline.
    """
    current_week = _get_current_week_start()
    anomalies = []
    min_weeks = 4

    for (_, _), rd in grouped.items():
        current_count = rd.weekly_counts.get(current_week, 0)
        if current_count == 0:
            continue

        # Separate historical data
        historical = [
            count for week, count in rd.weekly_counts.items()
            if week != current_week
        ]

        if len(historical) < min_weeks:
            continue

        mean = float(np.mean(historical))
        std = float(np.std(historical))

        # Handle zero variance
        if std == 0:
            if mean > 0 and current_count > mean * 2:
                z_score = 99.0  # Sentinel for "infinite" z-score
                severity = AnomalySeverity.HIGH
            else:
                continue
        else:
            z_score = (current_count - mean) / std
            if z_score >= config.zscore_critical:
                severity = AnomalySeverity.HIGH
            elif z_score >= config.zscore_warning:
                severity = AnomalySeverity.MEDIUM
            else:
                continue

        anomalies.append(DetectedAnomaly(
            region=rd.region,
            h3_index=rd.h3_index,
            disease=rd.disease,
            current_count=current_count,
            baseline=round(mean, 2),
            score=round(z_score, 2),
            source=DetectionSource.Z_SCORE,
            severity=severity,
            week_start=current_week.isoformat(),
            details={
                "historical_std": round(std, 2),
                "historical_weeks": len(historical),
                "threshold_warning": config.zscore_warning,
                "threshold_critical": config.zscore_critical,
            },
        ))

    logger.info(f"Z-score layer: {len(anomalies)} anomalies detected")
    return anomalies


# ──────────────────────────────────────────────
# Layer 2: Isolation Forest detection
# ──────────────────────────────────────────────

def detect_isolation_forest(
    grouped: Dict[Tuple[str, str], RegionData],
    config: ScanConfig,
) -> List[DetectedAnomaly]:
    """
    Isolation Forest anomaly detection.

    Builds a feature matrix from all (region, disease, week) data points
    and identifies outliers using the Isolation Forest algorithm.

    Features per data point:
      - case_count: absolute number of cases
      - growth_rate: week-over-week change ratio
      - deviation_from_mean: how far from the series mean
      - week_of_year: seasonality signal
    """
    IsolationForest = _get_isolation_forest()
    if IsolationForest is None:
        logger.warning("Isolation Forest unavailable — skipping ML layer")
        return []

    current_week = _get_current_week_start()

    # Build feature matrix: each row is a (region, disease, week) data point
    feature_rows = []  # (features_array, RegionData, week, count)

    for (_, _), rd in grouped.items():
        sorted_weeks = sorted(rd.weekly_counts.keys())
        if len(sorted_weeks) < 2:
            continue

        mean_count = np.mean(list(rd.weekly_counts.values()))

        for i, week in enumerate(sorted_weeks):
            count = rd.weekly_counts[week]
            prev_count = rd.weekly_counts[sorted_weeks[i - 1]] if i > 0 else count

            # Growth rate: ratio of change (capped to avoid division by zero)
            growth_rate = (count - prev_count) / max(prev_count, 1)

            # Deviation from series mean
            deviation = (count - mean_count) / max(mean_count, 1)

            # Week of year for seasonality
            week_of_year = week.isocalendar()[1]

            features = [count, growth_rate, deviation, week_of_year]
            feature_rows.append((features, rd, week, count))

    total_samples = len(feature_rows)
    if total_samples < config.ml_min_samples:
        logger.info(
            f"Isolation Forest: insufficient data ({total_samples} samples, "
            f"need {config.ml_min_samples}) — skipping"
        )
        return []

    # Build numpy matrix
    X = np.array([row[0] for row in feature_rows])

    # Fit and predict
    model = IsolationForest(
        contamination=config.ml_contamination,
        random_state=42,
        n_estimators=100,
    )
    predictions = model.fit_predict(X)
    scores = model.decision_function(X)

    # Collect anomalies (prediction == -1) for the current week only
    anomalies = []
    for idx, (features, rd, week, count) in enumerate(feature_rows):
        if predictions[idx] != -1:
            continue
        if week != current_week:
            continue
        if count == 0:
            continue

        # Map anomaly score to severity
        # decision_function: lower (more negative) = more anomalous
        anomaly_score = -float(scores[idx])  # Flip so higher = more anomalous

        if anomaly_score > 0.3:
            severity = AnomalySeverity.HIGH
        elif anomaly_score > 0.15:
            severity = AnomalySeverity.MEDIUM
        else:
            severity = AnomalySeverity.LOW

        mean_count = np.mean(list(rd.weekly_counts.values()))

        anomalies.append(DetectedAnomaly(
            region=rd.region,
            h3_index=rd.h3_index,
            disease=rd.disease,
            current_count=count,
            baseline=round(float(mean_count), 2),
            score=round(anomaly_score, 4),
            source=DetectionSource.ISOLATION_FOREST,
            severity=severity,
            week_start=current_week.isoformat(),
            details={
                "raw_decision_score": round(float(scores[idx]), 4),
                "growth_rate": round(features[1], 4),
                "deviation_from_mean": round(features[2], 4),
                "total_samples_used": total_samples,
                "contamination": config.ml_contamination,
            },
        ))

    logger.info(f"Isolation Forest layer: {len(anomalies)} anomalies detected ({total_samples} samples analyzed)")
    return anomalies


# ──────────────────────────────────────────────
# Layer combination
# ──────────────────────────────────────────────

def merge_detection_results(
    zscore_anomalies: List[DetectedAnomaly],
    ml_anomalies: List[DetectedAnomaly],
) -> List[DetectedAnomaly]:
    """
    Merge results from both detection layers.

    If both layers detect the same (region, disease), create a COMBINED
    anomaly with HIGH severity (high confidence).

    Returns deduplicated list of all anomalies.
    """
    # Index z-score anomalies by (region, disease)
    zscore_map: Dict[Tuple[str, str], DetectedAnomaly] = {}
    for a in zscore_anomalies:
        zscore_map[(a.region, a.disease)] = a

    # Index ML anomalies
    ml_map: Dict[Tuple[str, str], DetectedAnomaly] = {}
    for a in ml_anomalies:
        ml_map[(a.region, a.disease)] = a

    # Find overlaps
    combined_keys = set(zscore_map.keys()) & set(ml_map.keys())
    zscore_only = set(zscore_map.keys()) - combined_keys
    ml_only = set(ml_map.keys()) - combined_keys

    merged = []

    # Combined: both layers agree → HIGH confidence
    for key in combined_keys:
        zs = zscore_map[key]
        ml = ml_map[key]
        merged.append(DetectedAnomaly(
            region=zs.region,
            h3_index=zs.h3_index or ml.h3_index,
            disease=zs.disease,
            current_count=zs.current_count,
            baseline=zs.baseline,
            score=zs.score,  # Use z-score as primary score
            source=DetectionSource.COMBINED,
            severity=AnomalySeverity.HIGH,
            week_start=zs.week_start,
            details={
                "zscore": zs.score,
                "zscore_severity": zs.severity.value,
                "ml_score": ml.score,
                "ml_severity": ml.severity.value,
                "confidence": "HIGH — detected by both layers",
                **zs.details,
            },
        ))

    # Z-score only
    for key in zscore_only:
        merged.append(zscore_map[key])

    # ML only
    for key in ml_only:
        merged.append(ml_map[key])

    logger.info(
        f"Detection merge: {len(combined_keys)} combined, "
        f"{len(zscore_only)} z-score only, {len(ml_only)} ML only"
    )
    return merged
