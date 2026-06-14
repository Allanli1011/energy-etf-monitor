import csv
import json
from dataclasses import dataclass
from pathlib import Path

from energy_etf_monitor.modeling.baselines import BaselineEvaluationReport


@dataclass(frozen=True)
class ExportedBaselineReport:
    predictions_path: Path
    metrics_path: Path


PREDICTION_FIELDNAMES = (
    "report_date",
    "train_size",
    "target",
    "naive_probability",
    "logistic_probability",
    "regime",
)


def export_baseline_evaluation_report(
    report: BaselineEvaluationReport,
    destination: Path,
) -> ExportedBaselineReport:
    """Write walk-forward predictions and metric summaries to a report directory."""

    destination.mkdir(parents=True, exist_ok=True)
    predictions_path = destination / f"baseline_predictions_{report.target_name}.csv"
    metrics_path = destination / f"baseline_metrics_{report.target_name}.json"

    with predictions_path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PREDICTION_FIELDNAMES)
        writer.writeheader()
        for row in report.rows:
            writer.writerow(
                {
                    "report_date": row.report_date.isoformat(),
                    "train_size": row.train_size,
                    "target": row.target,
                    "naive_probability": f"{row.naive_probability:.6f}",
                    "logistic_probability": f"{row.logistic_probability:.6f}",
                    "regime": row.regime,
                }
            )

    metrics_path.write_text(
        json.dumps(
            {
                "target_name": report.target_name,
                "prediction_count": len(report.rows),
                "metrics": report.metrics,
                "regime_metrics": report.regime_metrics,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return ExportedBaselineReport(
        predictions_path=predictions_path,
        metrics_path=metrics_path,
    )
