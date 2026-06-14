from energy_etf_monitor.storage.models import (
    CotPositionRow,
    DailyFeatureRowModel,
    FundCrowdingMetricRow,
    FundDailyMetricRow,
    FundHoldingRow,
    FuturesSettlementRow,
    TimeSeriesObservationRow,
)


def test_storage_rows_include_dual_timestamp_columns() -> None:
    for model in (
        TimeSeriesObservationRow,
        CotPositionRow,
        FuturesSettlementRow,
        FundDailyMetricRow,
        FundHoldingRow,
        FundCrowdingMetricRow,
        DailyFeatureRowModel,
    ):
        columns = set(model.model_fields)
        assert "report_date" in columns
        assert "knowledge_date" in columns
        assert "quarantine" in columns
