import csv
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import fmean

from energy_etf_monitor.modeling.baselines import market_regime_for_date
from energy_etf_monitor.records import DailyFeatureRow, DailyPrediction


@dataclass(frozen=True)
class PredictionOutcome:
    report_date: date
    horizon_days: int
    regime: str
    price_probability: float
    price_naive_probability: float | None
    price_realized_up: bool
    spread_probability: float
    spread_naive_probability: float | None
    spread_realized_up: bool


@dataclass(frozen=True)
class ModelHealthReport:
    commodity: str
    outcomes: list[PredictionOutcome]
    metrics: dict[str, float]
    regime_metrics: dict[str, dict[str, float]]
    rolling_metrics: dict[str, float]


@dataclass(frozen=True)
class ExportedModelHealthReport:
    outcomes_path: Path
    metrics_path: Path


def build_model_health_report(
    predictions: list[DailyPrediction],
    feature_rows: list[DailyFeatureRow],
    *,
    as_of: datetime,
    commodity: str = "WTI",
    rolling_window: int = 20,
) -> ModelHealthReport:
    """Score persisted predictions against realized outcomes, point-in-time.

    A prediction made for ``feature_report_date`` with horizon ``h`` is only scored once the
    feature row ``h`` trading days later is both available AND known as of ``as_of`` (its
    knowledge_date has arrived) — so the health report never credits the model with an outcome it
    could not yet have observed. Quarantined predictions are skipped.
    """

    by_date = {row.report_date: row for row in feature_rows}
    ordered = sorted(feature_rows, key=lambda row: row.report_date)
    index_of = {row.report_date: position for position, row in enumerate(ordered)}
    as_of_naive = _as_utc_naive(as_of)

    outcomes: list[PredictionOutcome] = []
    for prediction in sorted(predictions, key=lambda item: item.report_date):
        if prediction.quarantine:
            continue
        current = by_date.get(prediction.feature_report_date)
        if current is None:
            continue
        future_index = index_of[prediction.feature_report_date] + prediction.horizon_days
        if future_index >= len(ordered):
            continue
        future = ordered[future_index]
        if _as_utc_naive(future.knowledge_date) > as_of_naive:
            continue
        price_realized = _direction(
            current.cl_front_month_settlement, future.cl_front_month_settlement
        )
        spread_realized = _direction(current.cl_m1_m2_spread, future.cl_m1_m2_spread)
        if price_realized is None or spread_realized is None:
            continue
        outcomes.append(
            PredictionOutcome(
                report_date=prediction.report_date,
                horizon_days=prediction.horizon_days,
                regime=market_regime_for_date(prediction.report_date),
                price_probability=prediction.price_up_probability,
                price_naive_probability=prediction.price_naive_probability,
                price_realized_up=price_realized,
                spread_probability=prediction.spread_up_probability,
                spread_naive_probability=prediction.spread_naive_probability,
                spread_realized_up=spread_realized,
            )
        )

    return ModelHealthReport(
        commodity=commodity,
        outcomes=outcomes,
        metrics=_metrics(outcomes),
        regime_metrics=_metrics_by_regime(outcomes),
        rolling_metrics=_metrics(outcomes[-rolling_window:]) if outcomes else {},
    )


def export_model_health_report(
    report: ModelHealthReport,
    destination: Path,
) -> ExportedModelHealthReport:
    """Write the scored outcomes and metric summaries to a report directory."""

    destination.mkdir(parents=True, exist_ok=True)
    outcomes_path = destination / f"model_health_outcomes_{report.commodity}.csv"
    metrics_path = destination / f"model_health_metrics_{report.commodity}.json"

    with outcomes_path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=_OUTCOME_FIELDNAMES)
        writer.writeheader()
        for outcome in report.outcomes:
            writer.writerow(
                {
                    "report_date": outcome.report_date.isoformat(),
                    "horizon_days": outcome.horizon_days,
                    "regime": outcome.regime,
                    "price_probability": f"{outcome.price_probability:.6f}",
                    "price_naive_probability": _format_optional(outcome.price_naive_probability),
                    "price_realized_up": int(outcome.price_realized_up),
                    "spread_probability": f"{outcome.spread_probability:.6f}",
                    "spread_naive_probability": _format_optional(outcome.spread_naive_probability),
                    "spread_realized_up": int(outcome.spread_realized_up),
                }
            )

    metrics_path.write_text(
        json.dumps(
            {
                "commodity": report.commodity,
                "outcome_count": len(report.outcomes),
                "metrics": report.metrics,
                "regime_metrics": report.regime_metrics,
                "rolling_metrics": report.rolling_metrics,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return ExportedModelHealthReport(outcomes_path=outcomes_path, metrics_path=metrics_path)


_OUTCOME_FIELDNAMES = (
    "report_date",
    "horizon_days",
    "regime",
    "price_probability",
    "price_naive_probability",
    "price_realized_up",
    "spread_probability",
    "spread_naive_probability",
    "spread_realized_up",
)


def _metrics(outcomes: list[PredictionOutcome]) -> dict[str, float]:
    if not outcomes:
        return {}
    metrics: dict[str, float] = {"count": float(len(outcomes))}
    for head in ("price", "spread"):
        realized = [int(getattr(item, f"{head}_realized_up")) for item in outcomes]
        probs = [getattr(item, f"{head}_probability") for item in outcomes]
        metrics[f"{head}_model_accuracy"] = fmean(
            int((prob >= 0.5) == bool(actual))
            for prob, actual in zip(probs, realized, strict=True)
        )
        metrics[f"{head}_model_brier"] = fmean(
            (prob - actual) ** 2 for prob, actual in zip(probs, realized, strict=True)
        )
        naive_pairs = [
            (getattr(item, f"{head}_naive_probability"), int(getattr(item, f"{head}_realized_up")))
            for item in outcomes
            if getattr(item, f"{head}_naive_probability") is not None
        ]
        if naive_pairs:
            metrics[f"{head}_naive_accuracy"] = fmean(
                int((prob >= 0.5) == bool(actual)) for prob, actual in naive_pairs
            )
            metrics[f"{head}_naive_brier"] = fmean(
                (prob - actual) ** 2 for prob, actual in naive_pairs
            )
            metrics[f"{head}_model_minus_naive_accuracy"] = (
                metrics[f"{head}_model_accuracy"] - metrics[f"{head}_naive_accuracy"]
            )
    return metrics


def _metrics_by_regime(outcomes: list[PredictionOutcome]) -> dict[str, dict[str, float]]:
    regime_metrics: dict[str, dict[str, float]] = {}
    for regime in dict.fromkeys(outcome.regime for outcome in outcomes):
        regime_metrics[regime] = _metrics(
            [outcome for outcome in outcomes if outcome.regime == regime]
        )
    return regime_metrics


def _direction(current: float | None, future: float | None) -> bool | None:
    if current is None or future is None:
        return None
    return future > current


def _format_optional(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
