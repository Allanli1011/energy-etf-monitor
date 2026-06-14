import csv
import json
from datetime import date

from energy_etf_monitor.modeling.baselines import (
    BaselineEvaluationReport,
    BaselinePredictionRow,
)
from energy_etf_monitor.modeling.reports import export_baseline_evaluation_report


def test_export_baseline_evaluation_report_writes_predictions_and_metrics(
    tmp_path,
) -> None:
    report = BaselineEvaluationReport(
        target_name="price_direction",
        rows=[
            BaselinePredictionRow(
                report_date=date(2020, 3, 2),
                train_size=252,
                target=1,
                naive_probability=0.0,
                logistic_probability=0.7,
                regime="covid_2020",
            ),
            BaselinePredictionRow(
                report_date=date(2021, 2, 1),
                train_size=253,
                target=0,
                naive_probability=1.0,
                logistic_probability=0.4,
                regime="inflation_2021_2022",
            ),
        ],
        metrics={"naive_accuracy": 0.0, "logistic_accuracy": 1.0},
        regime_metrics={
            "covid_2020": {"naive_accuracy": 0.0, "logistic_accuracy": 1.0},
            "inflation_2021_2022": {"naive_accuracy": 0.0, "logistic_accuracy": 1.0},
        },
    )

    exported = export_baseline_evaluation_report(report, tmp_path / "reports")

    assert exported.predictions_path.name == "baseline_predictions_price_direction.csv"
    assert exported.metrics_path.name == "baseline_metrics_price_direction.json"
    with exported.predictions_path.open(newline="") as file:
        prediction_rows = list(csv.DictReader(file))
    assert prediction_rows == [
        {
            "report_date": "2020-03-02",
            "train_size": "252",
            "target": "1",
            "naive_probability": "0.000000",
            "logistic_probability": "0.700000",
            "regime": "covid_2020",
        },
        {
            "report_date": "2021-02-01",
            "train_size": "253",
            "target": "0",
            "naive_probability": "1.000000",
            "logistic_probability": "0.400000",
            "regime": "inflation_2021_2022",
        },
    ]

    metrics_payload = json.loads(exported.metrics_path.read_text())
    assert metrics_payload == {
        "target_name": "price_direction",
        "prediction_count": 2,
        "metrics": {"logistic_accuracy": 1.0, "naive_accuracy": 0.0},
        "regime_metrics": {
            "covid_2020": {"logistic_accuracy": 1.0, "naive_accuracy": 0.0},
            "inflation_2021_2022": {
                "logistic_accuracy": 1.0,
                "naive_accuracy": 0.0,
            },
        },
    }
