from dataclasses import dataclass
from datetime import date
from statistics import fmean

from energy_etf_monitor.modeling.dataset import SupervisedExample
from energy_etf_monitor.modeling.logistic import fit_logistic_model
from energy_etf_monitor.modeling.targets import target_value, validate_target_name


@dataclass(frozen=True)
class MarketRegime:
    name: str
    start_date: date
    end_date: date


MARKET_REGIMES = (
    MarketRegime("gfc_2008", date(2008, 1, 1), date(2009, 6, 30)),
    MarketRegime("oil_crash_2014_2016", date(2014, 6, 1), date(2016, 2, 29)),
    MarketRegime("covid_2020", date(2020, 2, 1), date(2020, 12, 31)),
    MarketRegime("inflation_2021_2022", date(2021, 1, 1), date(2022, 12, 31)),
)


@dataclass(frozen=True)
class BaselinePredictionRow:
    report_date: date
    train_size: int
    target: int
    naive_probability: float
    logistic_probability: float
    regime: str


@dataclass(frozen=True)
class BaselineEvaluationReport:
    target_name: str
    rows: list[BaselinePredictionRow]
    metrics: dict[str, float]
    regime_metrics: dict[str, dict[str, float]]


def evaluate_walk_forward_baselines(
    examples: list[SupervisedExample],
    *,
    target_name: str,
    min_train_size: int,
    learning_rate: float = 0.1,
    epochs: int = 100,
) -> BaselineEvaluationReport:
    validate_target_name(target_name)
    if min_train_size <= 0:
        raise ValueError("min_train_size must be positive")
    if len(examples) <= min_train_size:
        return BaselineEvaluationReport(
            target_name=target_name,
            rows=[],
            metrics={},
            regime_metrics={},
        )

    ordered = sorted(examples, key=lambda example: example.report_date)
    prediction_rows: list[BaselinePredictionRow] = []
    feature_names = tuple(sorted({name for example in ordered for name in example.features}))
    for index in range(len(ordered)):
        test = ordered[index]
        # Purge (embargo) training examples whose label was not yet realized at the decision
        # date: an example's target only becomes known on its target_report_date. Including
        # examples whose target_report_date >= the decision date leaks future information
        # (the classic walk-forward look-ahead leak). This is the project's core promise.
        train = [
            example
            for example in ordered[:index]
            if example.target_report_date < test.report_date
        ]
        if len(train) < min_train_size:
            continue
        train_targets = [target_value(example, target_name) for example in train]
        model = fit_logistic_model(
            train,
            train_targets,
            feature_names=feature_names,
            learning_rate=learning_rate,
            epochs=epochs,
        )
        prediction_rows.append(
            BaselinePredictionRow(
                report_date=test.report_date,
                train_size=len(train),
                target=target_value(test, target_name),
                naive_probability=float(train_targets[-1]),
                logistic_probability=model.predict(test.features),
                regime=market_regime_for_date(test.report_date),
            )
        )

    return BaselineEvaluationReport(
        target_name=target_name,
        rows=prediction_rows,
        metrics=_metrics(prediction_rows),
        regime_metrics=_metrics_by_regime(prediction_rows),
    )


def market_regime_for_date(report_date: date) -> str:
    for regime in MARKET_REGIMES:
        if regime.start_date <= report_date <= regime.end_date:
            return regime.name
    return "other"


def _metrics(rows: list[BaselinePredictionRow]) -> dict[str, float]:
    if not rows:
        return {}
    return {
        "naive_accuracy": fmean(
            int(_class_from_probability(row.naive_probability) == row.target)
            for row in rows
        ),
        "logistic_accuracy": fmean(
            int(_class_from_probability(row.logistic_probability) == row.target)
            for row in rows
        ),
        "naive_brier": fmean((row.naive_probability - row.target) ** 2 for row in rows),
        "logistic_brier": fmean(
            (row.logistic_probability - row.target) ** 2 for row in rows
        ),
    }


def _metrics_by_regime(
    rows: list[BaselinePredictionRow],
) -> dict[str, dict[str, float]]:
    regime_metrics: dict[str, dict[str, float]] = {}
    for regime in dict.fromkeys(row.regime for row in rows):
        regime_rows = [row for row in rows if row.regime == regime]
        regime_metrics[regime] = _metrics(regime_rows)
    return regime_metrics


def _class_from_probability(value: float) -> int:
    return int(value >= 0.5)

