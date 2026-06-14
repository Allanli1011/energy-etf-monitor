from energy_etf_monitor.modeling.dataset import SupervisedExample

VALID_TARGET_NAMES = frozenset({"price_direction", "spread_direction"})


def validate_target_name(target_name: str) -> None:
    if target_name not in VALID_TARGET_NAMES:
        raise ValueError("target_name must be price_direction or spread_direction")


def target_value(example: SupervisedExample, target_name: str) -> int:
    validate_target_name(target_name)
    if target_name == "price_direction":
        return example.price_direction_target
    return example.spread_direction_target
