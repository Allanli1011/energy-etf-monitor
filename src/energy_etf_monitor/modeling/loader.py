import json
from pathlib import Path

from energy_etf_monitor.modeling.artifacts import load_model_artifact
from energy_etf_monitor.modeling.predict import PredictionModel


def load_artifact(path: Path) -> PredictionModel:
    """Load a saved model artifact, dispatching on its `model_type`.

    LightGBM artifacts are loaded lazily so the core install never needs the native dependency
    unless a LightGBM model is actually used.
    """

    model_type = json.loads(Path(path).read_text()).get("model_type")
    if model_type == "lightgbm":
        from energy_etf_monitor.modeling.gbm import load_gbm_artifact

        return load_gbm_artifact(Path(path))
    return load_model_artifact(Path(path))
