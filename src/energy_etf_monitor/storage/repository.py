from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from statistics import fmean, pstdev

from sqlmodel import Session, select

from energy_etf_monitor.commodities import WTI, CommodityConfig
from energy_etf_monitor.config import Settings
from energy_etf_monitor.features.crowding import derive_fund_crowding_metric
from energy_etf_monitor.ingestion.uscf import derive_implied_flow
from energy_etf_monitor.quality_gate import apply_quality_gate
from energy_etf_monitor.records import (
    CotPosition,
    DailyFeatureRow,
    DailyPrediction,
    FundCrowdingMetric,
    FundDailyMetric,
    FundHolding,
    FuturesSettlement,
    NewsArticle,
    TimeSeriesObservation,
)
from energy_etf_monitor.storage.db import create_engine_from_settings
from energy_etf_monitor.storage.models import (
    CotPositionRow,
    DailyFeatureRowModel,
    DailyPredictionRow,
    FundCrowdingMetricRow,
    FundDailyMetricRow,
    FundHoldingRow,
    FuturesSettlementRow,
    NewsArticleRow,
    TimeSeriesObservationRow,
)

WTI_INVENTORY_SERIES_ID = "WCESTUS1"
USD_INDEX_SERIES_ID = "DTWEXBGS"
REAL_YIELD_10Y_SERIES_ID = "DFII10"
COT_FEATURE_WINDOW = 156
INVENTORY_SEASONAL_LOOKBACK_YEARS = 5
NEWS_FEATURE_LOOKBACK_DAYS = 3
_NEWS_DIRECTION_SIGN = {"Bullish": 1.0, "Bearish": -1.0}
ROLL_WINDOW_START_BUSINESS_DAY = 5
ROLL_WINDOW_END_BUSINESS_DAY = 9


@dataclass(frozen=True)
class LoadResult:
    inserted: int = 0
    updated: int = 0
    quarantined: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated


class IngestionRepository:
    def __init__(self, session: Session, *, owns_session: bool = False, engine=None) -> None:
        self.session = session
        self.owns_session = owns_session
        self.engine = engine

    @classmethod
    def from_settings(cls, settings: Settings) -> "IngestionRepository":
        engine = create_engine_from_settings(settings)
        return cls(Session(engine), owns_session=True, engine=engine)

    def __enter__(self) -> "IngestionRepository":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is not None:
            self.session.rollback()
        if self.owns_session:
            self.session.close()
        if self.engine is not None:
            self.engine.dispose()

    def upsert_time_series(
        self,
        records: Sequence[TimeSeriesObservation],
    ) -> LoadResult:
        inserted = updated = quarantined = 0
        for record in records:
            gated = apply_quality_gate(record)
            existing = self.session.exec(
                select(TimeSeriesObservationRow).where(
                    TimeSeriesObservationRow.source == gated.source,
                    TimeSeriesObservationRow.series_id == gated.series_id,
                    TimeSeriesObservationRow.report_date == gated.report_date,
                )
            ).one_or_none()
            if existing is None:
                self.session.add(
                    TimeSeriesObservationRow(
                        source=gated.source,
                        series_id=gated.series_id,
                        report_date=gated.report_date,
                        knowledge_date=_to_db_datetime(gated.knowledge_date),
                        value=gated.value,
                        unit=gated.unit,
                        quarantine=gated.quarantine,
                    )
                )
                inserted += 1
            else:
                existing.knowledge_date = _to_db_datetime(gated.knowledge_date)
                existing.value = gated.value
                existing.unit = gated.unit
                existing.quarantine = gated.quarantine
                updated += 1
            quarantined += int(gated.quarantine)
        self.session.commit()
        return LoadResult(inserted=inserted, updated=updated, quarantined=quarantined)

    def upsert_cot_positions(
        self,
        records: Sequence[CotPosition],
    ) -> LoadResult:
        inserted = updated = quarantined = 0
        for record in records:
            gated = apply_quality_gate(record)
            existing = self.session.exec(
                select(CotPositionRow).where(
                    CotPositionRow.source == gated.source,
                    CotPositionRow.commodity == gated.commodity,
                    CotPositionRow.contract_market_code == gated.contract_market_code,
                    CotPositionRow.report_date == gated.report_date,
                )
            ).one_or_none()
            if existing is None:
                self.session.add(
                    CotPositionRow(
                        source=gated.source,
                        commodity=gated.commodity,
                        market_name=gated.market_name,
                        contract_market_code=gated.contract_market_code,
                        report_date=gated.report_date,
                        knowledge_date=_to_db_datetime(gated.knowledge_date),
                        open_interest=gated.open_interest,
                        swap_dealer_long=gated.swap_dealer_long,
                        swap_dealer_short=gated.swap_dealer_short,
                        swap_dealer_spread=gated.swap_dealer_spread,
                        producer_merchant_long=gated.producer_merchant_long,
                        producer_merchant_short=gated.producer_merchant_short,
                        managed_money_long=gated.managed_money_long,
                        managed_money_short=gated.managed_money_short,
                        other_reportable_long=gated.other_reportable_long,
                        other_reportable_short=gated.other_reportable_short,
                        quarantine=gated.quarantine,
                    )
                )
                inserted += 1
            else:
                existing.market_name = gated.market_name
                existing.knowledge_date = _to_db_datetime(gated.knowledge_date)
                existing.open_interest = gated.open_interest
                existing.swap_dealer_long = gated.swap_dealer_long
                existing.swap_dealer_short = gated.swap_dealer_short
                existing.swap_dealer_spread = gated.swap_dealer_spread
                existing.producer_merchant_long = gated.producer_merchant_long
                existing.producer_merchant_short = gated.producer_merchant_short
                existing.managed_money_long = gated.managed_money_long
                existing.managed_money_short = gated.managed_money_short
                existing.other_reportable_long = gated.other_reportable_long
                existing.other_reportable_short = gated.other_reportable_short
                existing.quarantine = gated.quarantine
                updated += 1
            quarantined += int(gated.quarantine)
        self.session.commit()
        return LoadResult(inserted=inserted, updated=updated, quarantined=quarantined)

    def upsert_futures_settlements(
        self,
        records: Sequence[FuturesSettlement],
    ) -> LoadResult:
        inserted = updated = quarantined = 0
        for record in records:
            gated = apply_quality_gate(record)
            existing = self.session.exec(
                select(FuturesSettlementRow).where(
                    FuturesSettlementRow.source == gated.source,
                    FuturesSettlementRow.product_code == gated.product_code,
                    FuturesSettlementRow.report_date == gated.report_date,
                    FuturesSettlementRow.contract_month == gated.contract_month,
                )
            ).one_or_none()
            if existing is None:
                self.session.add(
                    FuturesSettlementRow(
                        source=gated.source,
                        product_code=gated.product_code,
                        report_date=gated.report_date,
                        knowledge_date=_to_db_datetime(gated.knowledge_date),
                        contract_month=gated.contract_month,
                        settlement_price=gated.settlement_price,
                        open_interest=gated.open_interest,
                        quarantine=gated.quarantine,
                    )
                )
                inserted += 1
            else:
                existing.knowledge_date = _to_db_datetime(gated.knowledge_date)
                existing.settlement_price = gated.settlement_price
                existing.open_interest = gated.open_interest
                existing.quarantine = gated.quarantine
                updated += 1
            quarantined += int(gated.quarantine)
        self.session.commit()
        return LoadResult(inserted=inserted, updated=updated, quarantined=quarantined)

    def upsert_fund_daily_metrics(
        self,
        records: Sequence[FundDailyMetric],
    ) -> LoadResult:
        inserted = updated = quarantined = 0
        for record in sorted(records, key=lambda item: item.report_date):
            record = self._with_implied_flow(record)
            gated = apply_quality_gate(record)
            existing = self.session.exec(
                select(FundDailyMetricRow).where(
                    FundDailyMetricRow.source == gated.source,
                    FundDailyMetricRow.fund_ticker == gated.fund_ticker,
                    FundDailyMetricRow.report_date == gated.report_date,
                )
            ).one_or_none()
            if existing is None:
                self.session.add(
                    FundDailyMetricRow(
                        source=gated.source,
                        fund_ticker=gated.fund_ticker,
                        report_date=gated.report_date,
                        knowledge_date=_to_db_datetime(gated.knowledge_date),
                        nav_per_share=gated.nav_per_share,
                        shares_outstanding=gated.shares_outstanding,
                        total_net_assets=gated.total_net_assets,
                        implied_flow_usd=gated.implied_flow_usd,
                        quarantine=gated.quarantine,
                    )
                )
                inserted += 1
            else:
                existing.knowledge_date = _to_db_datetime(gated.knowledge_date)
                existing.nav_per_share = gated.nav_per_share
                existing.shares_outstanding = gated.shares_outstanding
                existing.total_net_assets = gated.total_net_assets
                existing.implied_flow_usd = gated.implied_flow_usd
                existing.quarantine = gated.quarantine
                updated += 1
            quarantined += int(gated.quarantine)
        self.session.commit()
        return LoadResult(inserted=inserted, updated=updated, quarantined=quarantined)

    def upsert_fund_holdings(
        self,
        records: Sequence[FundHolding],
    ) -> LoadResult:
        inserted = updated = quarantined = 0
        for record in records:
            gated = apply_quality_gate(record)
            existing = self.session.exec(
                select(FundHoldingRow).where(
                    FundHoldingRow.source == gated.source,
                    FundHoldingRow.fund_ticker == gated.fund_ticker,
                    FundHoldingRow.report_date == gated.report_date,
                    FundHoldingRow.holding_key == gated.holding_key,
                )
            ).one_or_none()
            if existing is None:
                self.session.add(
                    FundHoldingRow(
                        source=gated.source,
                        fund_ticker=gated.fund_ticker,
                        holding_key=gated.holding_key,
                        holding_name=gated.holding_name,
                        instrument_type=gated.instrument_type,
                        ticker=gated.ticker,
                        report_date=gated.report_date,
                        knowledge_date=_to_db_datetime(gated.knowledge_date),
                        contract_month=gated.contract_month,
                        quantity=gated.quantity,
                        market_value=gated.market_value,
                        percent_nav=gated.percent_nav,
                        quarantine=gated.quarantine,
                    )
                )
                inserted += 1
            else:
                existing.holding_name = gated.holding_name
                existing.instrument_type = gated.instrument_type
                existing.ticker = gated.ticker
                existing.knowledge_date = _to_db_datetime(gated.knowledge_date)
                existing.contract_month = gated.contract_month
                existing.quantity = gated.quantity
                existing.market_value = gated.market_value
                existing.percent_nav = gated.percent_nav
                existing.quarantine = gated.quarantine
                updated += 1
            quarantined += int(gated.quarantine)
        self.session.commit()
        return LoadResult(inserted=inserted, updated=updated, quarantined=quarantined)

    def upsert_fund_crowding_metrics(
        self,
        records: Sequence[FundCrowdingMetric],
    ) -> LoadResult:
        inserted = updated = quarantined = 0
        for record in records:
            gated = apply_quality_gate(record)
            existing = self.session.exec(
                select(FundCrowdingMetricRow).where(
                    FundCrowdingMetricRow.source == gated.source,
                    FundCrowdingMetricRow.fund_ticker == gated.fund_ticker,
                    FundCrowdingMetricRow.commodity == gated.commodity,
                    FundCrowdingMetricRow.product_code == gated.product_code,
                    FundCrowdingMetricRow.report_date == gated.report_date,
                )
            ).one_or_none()
            if existing is None:
                self.session.add(
                    FundCrowdingMetricRow(
                        source=gated.source,
                        fund_ticker=gated.fund_ticker,
                        commodity=gated.commodity,
                        product_code=gated.product_code,
                        report_date=gated.report_date,
                        knowledge_date=_to_db_datetime(gated.knowledge_date),
                        fund_total_net_assets=gated.fund_total_net_assets,
                        held_contract_count=gated.held_contract_count,
                        open_interest_contracts=gated.open_interest_contracts,
                        open_interest_notional=gated.open_interest_notional,
                        aum_to_open_interest_notional=gated.aum_to_open_interest_notional,
                        held_contracts_to_open_interest=gated.held_contracts_to_open_interest,
                        matched_contract_months=gated.matched_contract_months,
                        quarantine=gated.quarantine,
                    )
                )
                inserted += 1
            else:
                existing.knowledge_date = _to_db_datetime(gated.knowledge_date)
                existing.fund_total_net_assets = gated.fund_total_net_assets
                existing.held_contract_count = gated.held_contract_count
                existing.open_interest_contracts = gated.open_interest_contracts
                existing.open_interest_notional = gated.open_interest_notional
                existing.aum_to_open_interest_notional = gated.aum_to_open_interest_notional
                existing.held_contracts_to_open_interest = gated.held_contracts_to_open_interest
                existing.matched_contract_months = gated.matched_contract_months
                existing.quarantine = gated.quarantine
                updated += 1
            quarantined += int(gated.quarantine)
        self.session.commit()
        return LoadResult(inserted=inserted, updated=updated, quarantined=quarantined)

    def upsert_daily_feature_rows(
        self,
        records: Sequence[DailyFeatureRow],
    ) -> LoadResult:
        inserted = updated = quarantined = 0
        for record in records:
            gated = apply_quality_gate(record)
            existing = self.session.exec(
                select(DailyFeatureRowModel).where(
                    DailyFeatureRowModel.source == gated.source,
                    DailyFeatureRowModel.commodity == gated.commodity,
                    DailyFeatureRowModel.report_date == gated.report_date,
                )
            ).one_or_none()
            if existing is None:
                self.session.add(
                    DailyFeatureRowModel(
                        source=gated.source,
                        commodity=gated.commodity,
                        report_date=gated.report_date,
                        knowledge_date=_to_db_datetime(gated.knowledge_date),
                        cl_front_month_settlement=gated.cl_front_month_settlement,
                        cl_m1_m2_spread=gated.cl_m1_m2_spread,
                        cl_m2_m3_spread=gated.cl_m2_m3_spread,
                        cl_m3_m6_spread=gated.cl_m3_m6_spread,
                        cl_curve_curvature_m1_m2_m3=(
                            gated.cl_curve_curvature_m1_m2_m3
                        ),
                        cl_front_month_return_1d=gated.cl_front_month_return_1d,
                        cl_carry_m1_m2=gated.cl_carry_m1_m2,
                        cl_carry_m1_m2_change_1d=gated.cl_carry_m1_m2_change_1d,
                        cot_swap_dealer_net=gated.cot_swap_dealer_net,
                        cot_swap_dealer_net_zscore=gated.cot_swap_dealer_net_zscore,
                        cot_swap_dealer_net_index=gated.cot_swap_dealer_net_index,
                        cot_open_interest=gated.cot_open_interest,
                        inventory_value=gated.inventory_value,
                        inventory_seasonal_surprise=gated.inventory_seasonal_surprise,
                        usd_index_value=gated.usd_index_value,
                        real_yield_10y=gated.real_yield_10y,
                        crowding_aum_to_oi=gated.crowding_aum_to_oi,
                        crowding_contracts_to_oi=gated.crowding_contracts_to_oi,
                        roll_window_flag=gated.roll_window_flag,
                        roll_window_crowding_interaction=(
                            gated.roll_window_crowding_interaction
                        ),
                        news_count=gated.news_count,
                        news_tone_mean=gated.news_tone_mean,
                        news_impact_score=gated.news_impact_score,
                        quarantine=gated.quarantine,
                    )
                )
                inserted += 1
            else:
                existing.knowledge_date = _to_db_datetime(gated.knowledge_date)
                existing.cl_front_month_settlement = gated.cl_front_month_settlement
                existing.cl_m1_m2_spread = gated.cl_m1_m2_spread
                existing.cl_m2_m3_spread = gated.cl_m2_m3_spread
                existing.cl_m3_m6_spread = gated.cl_m3_m6_spread
                existing.cl_curve_curvature_m1_m2_m3 = gated.cl_curve_curvature_m1_m2_m3
                existing.cl_front_month_return_1d = gated.cl_front_month_return_1d
                existing.cl_carry_m1_m2 = gated.cl_carry_m1_m2
                existing.cl_carry_m1_m2_change_1d = gated.cl_carry_m1_m2_change_1d
                existing.cot_swap_dealer_net = gated.cot_swap_dealer_net
                existing.cot_swap_dealer_net_zscore = gated.cot_swap_dealer_net_zscore
                existing.cot_swap_dealer_net_index = gated.cot_swap_dealer_net_index
                existing.cot_open_interest = gated.cot_open_interest
                existing.inventory_value = gated.inventory_value
                existing.inventory_seasonal_surprise = gated.inventory_seasonal_surprise
                existing.usd_index_value = gated.usd_index_value
                existing.real_yield_10y = gated.real_yield_10y
                existing.crowding_aum_to_oi = gated.crowding_aum_to_oi
                existing.crowding_contracts_to_oi = gated.crowding_contracts_to_oi
                existing.roll_window_flag = gated.roll_window_flag
                existing.roll_window_crowding_interaction = (
                    gated.roll_window_crowding_interaction
                )
                existing.news_count = gated.news_count
                existing.news_tone_mean = gated.news_tone_mean
                existing.news_impact_score = gated.news_impact_score
                existing.quarantine = gated.quarantine
                updated += 1
            quarantined += int(gated.quarantine)
        self.session.commit()
        return LoadResult(inserted=inserted, updated=updated, quarantined=quarantined)

    def derive_fund_crowding_metric(
        self,
        *,
        fund_ticker: str,
        commodity: str,
        product_code: str,
        report_date,
    ) -> FundCrowdingMetric:
        fund_metric = self.session.exec(
            select(FundDailyMetricRow).where(
                FundDailyMetricRow.fund_ticker == fund_ticker,
                FundDailyMetricRow.report_date == report_date,
                FundDailyMetricRow.quarantine.is_(False),
            )
        ).one()
        holdings = self.session.exec(
            select(FundHoldingRow).where(
                FundHoldingRow.fund_ticker == fund_ticker,
                FundHoldingRow.report_date == report_date,
                FundHoldingRow.quarantine.is_(False),
            )
        ).all()
        settlements = self.session.exec(
            select(FuturesSettlementRow).where(
                FuturesSettlementRow.product_code == product_code,
                FuturesSettlementRow.report_date == report_date,
                FuturesSettlementRow.quarantine.is_(False),
            )
        ).all()
        return derive_fund_crowding_metric(
            fund_metric=_row_to_fund_metric(fund_metric),
            holdings=[_row_to_fund_holding(row) for row in holdings],
            settlements=[_row_to_futures_settlement(row) for row in settlements],
            commodity=commodity,
            product_code=product_code,
        )

    def derive_feature_row(
        self,
        *,
        config: CommodityConfig,
        as_of: datetime,
    ) -> DailyFeatureRow:
        as_of_datetime = _to_db_datetime(as_of)
        settlements = self._latest_futures_curve(
            product_code=config.product_code, as_of=as_of_datetime
        )
        front_months = sorted(settlements, key=lambda row: row.contract_month)
        m1 = front_months[0] if len(front_months) >= 1 else None
        m2 = front_months[1] if len(front_months) >= 2 else None
        m3 = front_months[2] if len(front_months) >= 3 else None
        m6 = _contract_at_month_offset(front_months, m1, month_offset=5)
        cl_carry_m1_m2 = _carry(m1, m2)
        previous_curve = self._previous_futures_curve(
            product_code=config.product_code,
            as_of=as_of_datetime,
            before_report_date=front_months[0].report_date if front_months else None,
        )
        previous_carry = _carry_from_curve(previous_curve)
        previous_m1 = (
            _settlement_for_contract(previous_curve, m1.contract_month)
            if m1 is not None
            else None
        )

        cot_rows = self._available_cot_positions(
            commodity=config.name,
            as_of=as_of_datetime,
            window=COT_FEATURE_WINDOW,
        )
        cot = cot_rows[0] if cot_rows else None
        cot_net_values = [
            value
            for value in (_cot_swap_dealer_net(row) for row in cot_rows)
            if value is not None
        ]
        inventory = self._latest_time_series_observation(
            series_id=config.inventory_series_id,
            as_of=as_of_datetime,
        )
        usd_index = self._latest_time_series_observation(
            series_id=USD_INDEX_SERIES_ID,
            as_of=as_of_datetime,
        )
        real_yield = self._latest_time_series_observation(
            series_id=REAL_YIELD_10Y_SERIES_ID,
            as_of=as_of_datetime,
        )
        crowding = (
            self._latest_fund_crowding_metric(
                fund_ticker=config.crowding_fund_ticker,
                commodity=config.name,
                product_code=config.crowding_product_code or config.product_code,
                as_of=as_of_datetime,
            )
            if config.crowding_fund_ticker is not None
            else None
        )
        roll_window_flag = _roll_window_flag(as_of_datetime.date())
        roll_window_crowding_interaction = (
            roll_window_flag * crowding.aum_to_open_interest_notional
            if crowding is not None
            else None
        )
        source_rows = front_months + [
            row
            for row in (cot, inventory, usd_index, real_yield, crowding)
            if row is not None
        ]
        if not source_rows:
            raise ValueError(
                f"No {config.name} feature sources available as of {as_of_datetime.isoformat()}"
            )

        news_count, news_tone_mean, news_impact_score = self._news_aggregates(
            commodity=config.name, as_of=as_of_datetime
        )

        return DailyFeatureRow(
            source="feature_pipeline",
            commodity=config.name,
            report_date=as_of_datetime.date(),
            knowledge_date=max(row.knowledge_date for row in source_rows),
            cl_front_month_settlement=m1.settlement_price if m1 is not None else None,
            cl_m1_m2_spread=_settlement_spread(m1, m2),
            cl_m2_m3_spread=_settlement_spread(m2, m3),
            cl_m3_m6_spread=_settlement_spread(m3, m6),
            cl_curve_curvature_m1_m2_m3=_curve_curvature(m1, m2, m3),
            cl_front_month_return_1d=_settlement_return(m1, previous_m1),
            cl_carry_m1_m2=cl_carry_m1_m2,
            cl_carry_m1_m2_change_1d=(
                cl_carry_m1_m2 - previous_carry
                if cl_carry_m1_m2 is not None and previous_carry is not None
                else None
            ),
            cot_swap_dealer_net=_cot_swap_dealer_net(cot) if cot is not None else None,
            cot_swap_dealer_net_zscore=_latest_zscore(cot_net_values),
            cot_swap_dealer_net_index=_latest_min_max_index(cot_net_values),
            cot_open_interest=float(cot.open_interest) if cot is not None else None,
            inventory_value=inventory.value if inventory is not None else None,
            inventory_seasonal_surprise=(
                self._seasonal_time_series_surprise(
                    latest=inventory,
                    as_of=as_of_datetime,
                    lookback_years=INVENTORY_SEASONAL_LOOKBACK_YEARS,
                )
                if inventory is not None
                else None
            ),
            usd_index_value=usd_index.value if usd_index is not None else None,
            real_yield_10y=real_yield.value if real_yield is not None else None,
            crowding_aum_to_oi=(
                crowding.aum_to_open_interest_notional if crowding is not None else None
            ),
            crowding_contracts_to_oi=(
                crowding.held_contracts_to_open_interest if crowding is not None else None
            ),
            roll_window_flag=roll_window_flag,
            roll_window_crowding_interaction=roll_window_crowding_interaction,
            news_count=news_count,
            news_tone_mean=news_tone_mean,
            news_impact_score=news_impact_score,
        )

    def derive_wti_feature_row(self, *, as_of: datetime) -> DailyFeatureRow:
        return self.derive_feature_row(config=WTI, as_of=as_of)

    def derive_feature_rows(
        self,
        *,
        config: CommodityConfig,
        start_date: date,
        end_date: date,
        as_of_time: time,
        skip_weekends: bool = True,
    ) -> list[DailyFeatureRow]:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        rows: list[DailyFeatureRow] = []
        current_date = start_date
        while current_date <= end_date:
            # Skip weekends by default: futures do not settle on Sat/Sun, so a calendar-day
            # row there would just restate Friday's stale curve and corrupt the horizon
            # (which must count trading days, not calendar days) downstream in the models.
            if skip_weekends and current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue
            rows.append(
                self.derive_feature_row(
                    config=config,
                    as_of=datetime.combine(current_date, as_of_time),
                )
            )
            current_date += timedelta(days=1)
        return rows

    def derive_wti_feature_rows(
        self,
        *,
        start_date: date,
        end_date: date,
        as_of_time: time,
        skip_weekends: bool = True,
    ) -> list[DailyFeatureRow]:
        return self.derive_feature_rows(
            config=WTI,
            start_date=start_date,
            end_date=end_date,
            as_of_time=as_of_time,
            skip_weekends=skip_weekends,
        )

    def list_daily_feature_rows(
        self,
        *,
        commodity: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[DailyFeatureRow]:
        statement = select(DailyFeatureRowModel).where(
            DailyFeatureRowModel.commodity == commodity,
            DailyFeatureRowModel.quarantine.is_(False),
        )
        if start_date is not None:
            statement = statement.where(DailyFeatureRowModel.report_date >= start_date)
        if end_date is not None:
            statement = statement.where(DailyFeatureRowModel.report_date <= end_date)
        statement = statement.order_by(DailyFeatureRowModel.report_date.asc())
        return [_row_to_daily_feature(row) for row in self.session.exec(statement).all()]

    def list_fund_daily_metrics(
        self,
        *,
        fund_ticker: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundDailyMetric]:
        statement = select(FundDailyMetricRow).where(
            FundDailyMetricRow.fund_ticker == fund_ticker,
            FundDailyMetricRow.quarantine.is_(False),
        )
        if start_date is not None:
            statement = statement.where(FundDailyMetricRow.report_date >= start_date)
        if end_date is not None:
            statement = statement.where(FundDailyMetricRow.report_date <= end_date)
        statement = statement.order_by(FundDailyMetricRow.report_date.asc())
        return [_row_to_fund_metric(row) for row in self.session.exec(statement).all()]

    def list_fund_holdings(
        self,
        *,
        fund_ticker: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundHolding]:
        statement = select(FundHoldingRow).where(
            FundHoldingRow.fund_ticker == fund_ticker,
            FundHoldingRow.quarantine.is_(False),
        )
        if start_date is not None:
            statement = statement.where(FundHoldingRow.report_date >= start_date)
        if end_date is not None:
            statement = statement.where(FundHoldingRow.report_date <= end_date)
        statement = statement.order_by(
            FundHoldingRow.report_date.asc(),
            FundHoldingRow.contract_month.asc(),
            FundHoldingRow.holding_key.asc(),
        )
        return [_row_to_fund_holding(row) for row in self.session.exec(statement).all()]

    def list_cot_positions(
        self,
        *,
        commodity: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[CotPosition]:
        statement = select(CotPositionRow).where(
            CotPositionRow.commodity == commodity,
            CotPositionRow.quarantine.is_(False),
        )
        if start_date is not None:
            statement = statement.where(CotPositionRow.report_date >= start_date)
        if end_date is not None:
            statement = statement.where(CotPositionRow.report_date <= end_date)
        statement = statement.order_by(CotPositionRow.report_date.asc())
        return [_row_to_cot_position(row) for row in self.session.exec(statement).all()]

    def latest_daily_feature_row(
        self,
        *,
        commodity: str,
        as_of: datetime,
    ) -> DailyFeatureRow | None:
        as_of_datetime = _to_db_datetime(as_of)
        row = self.session.exec(
            select(DailyFeatureRowModel)
            .where(
                DailyFeatureRowModel.commodity == commodity,
                DailyFeatureRowModel.report_date <= as_of_datetime.date(),
                DailyFeatureRowModel.knowledge_date <= as_of_datetime,
                DailyFeatureRowModel.quarantine.is_(False),
            )
            .order_by(
                DailyFeatureRowModel.report_date.desc(),
                DailyFeatureRowModel.knowledge_date.desc(),
            )
        ).first()
        return _row_to_daily_feature(row) if row is not None else None

    def upsert_daily_predictions(
        self,
        records: Sequence[DailyPrediction],
    ) -> LoadResult:
        inserted = updated = quarantined = 0
        for record in records:
            gated = apply_quality_gate(record)
            existing = self.session.exec(
                select(DailyPredictionRow).where(
                    DailyPredictionRow.source == gated.source,
                    DailyPredictionRow.commodity == gated.commodity,
                    DailyPredictionRow.report_date == gated.report_date,
                    DailyPredictionRow.horizon_days == gated.horizon_days,
                )
            ).one_or_none()
            if existing is None:
                self.session.add(
                    DailyPredictionRow(
                        source=gated.source,
                        commodity=gated.commodity,
                        report_date=gated.report_date,
                        knowledge_date=_to_db_datetime(gated.knowledge_date),
                        horizon_days=gated.horizon_days,
                        feature_report_date=gated.feature_report_date,
                        price_up_probability=gated.price_up_probability,
                        spread_up_probability=gated.spread_up_probability,
                        price_naive_probability=gated.price_naive_probability,
                        spread_naive_probability=gated.spread_naive_probability,
                        price_model_version=gated.price_model_version,
                        spread_model_version=gated.spread_model_version,
                        price_top_drivers=gated.price_top_drivers,
                        spread_top_drivers=gated.spread_top_drivers,
                        quarantine=gated.quarantine,
                    )
                )
                inserted += 1
            else:
                existing.knowledge_date = _to_db_datetime(gated.knowledge_date)
                existing.feature_report_date = gated.feature_report_date
                existing.price_up_probability = gated.price_up_probability
                existing.spread_up_probability = gated.spread_up_probability
                existing.price_naive_probability = gated.price_naive_probability
                existing.spread_naive_probability = gated.spread_naive_probability
                existing.price_model_version = gated.price_model_version
                existing.spread_model_version = gated.spread_model_version
                existing.price_top_drivers = gated.price_top_drivers
                existing.spread_top_drivers = gated.spread_top_drivers
                existing.quarantine = gated.quarantine
                updated += 1
            quarantined += int(gated.quarantine)
        self.session.commit()
        return LoadResult(inserted=inserted, updated=updated, quarantined=quarantined)

    def upsert_news_articles(self, records: Sequence[NewsArticle]) -> LoadResult:
        inserted = updated = quarantined = 0
        for record in records:
            gated = apply_quality_gate(record)
            existing = self.session.exec(
                select(NewsArticleRow).where(
                    NewsArticleRow.source == gated.source,
                    NewsArticleRow.url_hash == gated.url_hash,
                )
            ).one_or_none()
            if existing is None:
                self.session.add(
                    NewsArticleRow(
                        source=gated.source,
                        report_date=gated.report_date,
                        knowledge_date=_to_db_datetime(gated.knowledge_date),
                        published_at=_to_db_datetime(gated.published_at),
                        url=gated.url,
                        url_hash=gated.url_hash,
                        title=gated.title,
                        canonical_url=gated.canonical_url,
                        summary=gated.summary,
                        tone=gated.tone,
                        commodity=gated.commodity,
                        contract_family=gated.contract_family,
                        catalyst_type=gated.catalyst_type,
                        importance_score=gated.importance_score,
                        impact_direction=gated.impact_direction,
                        spread_impact_direction=gated.spread_impact_direction,
                        confidence=gated.confidence,
                        rationale=gated.rationale,
                        quarantine=gated.quarantine,
                    )
                )
                inserted += 1
            else:
                existing.knowledge_date = _to_db_datetime(gated.knowledge_date)
                existing.published_at = _to_db_datetime(gated.published_at)
                existing.title = gated.title
                existing.canonical_url = gated.canonical_url
                existing.summary = gated.summary
                existing.tone = gated.tone
                existing.commodity = gated.commodity
                existing.contract_family = gated.contract_family
                existing.catalyst_type = gated.catalyst_type
                existing.importance_score = gated.importance_score
                existing.impact_direction = gated.impact_direction
                existing.spread_impact_direction = gated.spread_impact_direction
                existing.confidence = gated.confidence
                existing.rationale = gated.rationale
                existing.quarantine = gated.quarantine
                updated += 1
            quarantined += int(gated.quarantine)
        self.session.commit()
        return LoadResult(inserted=inserted, updated=updated, quarantined=quarantined)

    def list_news_articles(
        self,
        *,
        as_of: datetime | None = None,
        commodity: str | None = None,
        min_importance: float = 0.0,
        limit: int | None = None,
    ) -> list[NewsArticle]:
        statement = select(NewsArticleRow).where(
            NewsArticleRow.quarantine.is_(False),
            NewsArticleRow.importance_score >= min_importance,
        )
        if as_of is not None:
            as_of_datetime = _to_db_datetime(as_of)
            statement = statement.where(NewsArticleRow.knowledge_date <= as_of_datetime)
        if commodity is not None:
            statement = statement.where(NewsArticleRow.commodity == commodity)
        statement = statement.order_by(
            NewsArticleRow.importance_score.desc(),
            NewsArticleRow.published_at.desc(),
        )
        if limit is not None:
            statement = statement.limit(limit)
        return [_row_to_news_article(row) for row in self.session.exec(statement).all()]

    def list_daily_predictions(
        self,
        *,
        commodity: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[DailyPrediction]:
        statement = select(DailyPredictionRow).where(
            DailyPredictionRow.commodity == commodity,
        )
        if start_date is not None:
            statement = statement.where(DailyPredictionRow.report_date >= start_date)
        if end_date is not None:
            statement = statement.where(DailyPredictionRow.report_date <= end_date)
        statement = statement.order_by(DailyPredictionRow.report_date.asc())
        return [_row_to_daily_prediction(row) for row in self.session.exec(statement).all()]

    def _latest_time_series_observation(
        self,
        *,
        series_id: str,
        as_of: datetime,
    ) -> TimeSeriesObservationRow | None:
        return self.session.exec(
            select(TimeSeriesObservationRow)
            .where(
                TimeSeriesObservationRow.series_id == series_id,
                TimeSeriesObservationRow.report_date <= as_of.date(),
                TimeSeriesObservationRow.knowledge_date <= as_of,
                TimeSeriesObservationRow.quarantine.is_(False),
            )
            .order_by(
                TimeSeriesObservationRow.report_date.desc(),
                TimeSeriesObservationRow.knowledge_date.desc(),
            )
        ).first()

    def _latest_cot_position(
        self,
        *,
        commodity: str,
        as_of: datetime,
    ) -> CotPositionRow | None:
        return self.session.exec(
            select(CotPositionRow)
            .where(
                CotPositionRow.commodity == commodity,
                CotPositionRow.report_date <= as_of.date(),
                CotPositionRow.knowledge_date <= as_of,
                CotPositionRow.quarantine.is_(False),
            )
            .order_by(
                CotPositionRow.report_date.desc(),
                CotPositionRow.knowledge_date.desc(),
            )
        ).first()

    def _available_cot_positions(
        self,
        *,
        commodity: str,
        as_of: datetime,
        window: int,
    ) -> list[CotPositionRow]:
        return list(
            self.session.exec(
                select(CotPositionRow)
                .where(
                    CotPositionRow.commodity == commodity,
                    CotPositionRow.report_date <= as_of.date(),
                    CotPositionRow.knowledge_date <= as_of,
                    CotPositionRow.quarantine.is_(False),
                )
                .order_by(
                    CotPositionRow.report_date.desc(),
                    CotPositionRow.knowledge_date.desc(),
                )
                .limit(window)
            ).all()
        )

    def _news_aggregates(
        self,
        *,
        commodity: str,
        as_of: datetime,
        lookback_days: int = NEWS_FEATURE_LOOKBACK_DAYS,
    ) -> tuple[float | None, float | None, float | None]:
        """Point-in-time news aggregates: count, mean tone, direction-weighted impact.

        Only articles published within the lookback window AND already known as of the decision
        time (knowledge_date <= as_of) are aggregated, so this respects the same gate as every
        other feature. Returns (None, None, None) when no news is available.
        """

        as_of_datetime = _to_db_datetime(as_of)
        window_start = as_of_datetime - timedelta(days=lookback_days)
        rows = self.session.exec(
            select(NewsArticleRow).where(
                NewsArticleRow.commodity == commodity,
                NewsArticleRow.published_at >= window_start,
                NewsArticleRow.knowledge_date <= as_of_datetime,
                NewsArticleRow.quarantine.is_(False),
            )
        ).all()
        if not rows:
            return None, None, None
        count = float(len(rows))
        tones = [row.tone for row in rows if row.tone is not None]
        tone_mean = fmean(tones) if tones else None
        impact = fmean(_signed_news_impact(row) for row in rows)
        return count, tone_mean, impact

    def _seasonal_time_series_surprise(
        self,
        *,
        latest: TimeSeriesObservationRow,
        as_of: datetime,
        lookback_years: int,
    ) -> float | None:
        latest_week = latest.report_date.isocalendar().week
        candidates = self.session.exec(
            select(TimeSeriesObservationRow)
            .where(
                TimeSeriesObservationRow.series_id == latest.series_id,
                TimeSeriesObservationRow.report_date < latest.report_date,
                TimeSeriesObservationRow.knowledge_date <= as_of,
                TimeSeriesObservationRow.quarantine.is_(False),
            )
            .order_by(TimeSeriesObservationRow.report_date.desc())
        ).all()
        seasonal_values = [
            row.value
            for row in candidates
            if row.report_date.isocalendar().week == latest_week
        ][:lookback_years]
        if not seasonal_values:
            return None
        return latest.value - fmean(seasonal_values)

    def _latest_futures_curve(
        self,
        *,
        product_code: str,
        as_of: datetime,
    ) -> list[FuturesSettlementRow]:
        latest_report_date = self.session.exec(
            select(FuturesSettlementRow.report_date)
            .where(
                FuturesSettlementRow.product_code == product_code,
                FuturesSettlementRow.report_date <= as_of.date(),
                FuturesSettlementRow.knowledge_date <= as_of,
                FuturesSettlementRow.quarantine.is_(False),
            )
            .order_by(FuturesSettlementRow.report_date.desc())
        ).first()
        if latest_report_date is None:
            return []
        return list(
            self.session.exec(
                select(FuturesSettlementRow)
                .where(
                    FuturesSettlementRow.product_code == product_code,
                    FuturesSettlementRow.report_date == latest_report_date,
                    FuturesSettlementRow.knowledge_date <= as_of,
                    FuturesSettlementRow.quarantine.is_(False),
                )
                .order_by(FuturesSettlementRow.contract_month.asc())
            ).all()
        )

    def _previous_futures_curve(
        self,
        *,
        product_code: str,
        as_of: datetime,
        before_report_date: date | None,
    ) -> list[FuturesSettlementRow]:
        if before_report_date is None:
            return []
        latest_report_date = self.session.exec(
            select(FuturesSettlementRow.report_date)
            .where(
                FuturesSettlementRow.product_code == product_code,
                FuturesSettlementRow.report_date < before_report_date,
                FuturesSettlementRow.knowledge_date <= as_of,
                FuturesSettlementRow.quarantine.is_(False),
            )
            .order_by(FuturesSettlementRow.report_date.desc())
        ).first()
        if latest_report_date is None:
            return []
        return list(
            self.session.exec(
                select(FuturesSettlementRow)
                .where(
                    FuturesSettlementRow.product_code == product_code,
                    FuturesSettlementRow.report_date == latest_report_date,
                    FuturesSettlementRow.knowledge_date <= as_of,
                    FuturesSettlementRow.quarantine.is_(False),
                )
                .order_by(FuturesSettlementRow.contract_month.asc())
            ).all()
        )

    def _latest_fund_crowding_metric(
        self,
        *,
        fund_ticker: str,
        commodity: str,
        product_code: str,
        as_of: datetime,
    ) -> FundCrowdingMetricRow | None:
        return self.session.exec(
            select(FundCrowdingMetricRow)
            .where(
                FundCrowdingMetricRow.fund_ticker == fund_ticker,
                FundCrowdingMetricRow.commodity == commodity,
                FundCrowdingMetricRow.product_code == product_code,
                FundCrowdingMetricRow.report_date <= as_of.date(),
                FundCrowdingMetricRow.knowledge_date <= as_of,
                FundCrowdingMetricRow.quarantine.is_(False),
            )
            .order_by(
                FundCrowdingMetricRow.report_date.desc(),
                FundCrowdingMetricRow.knowledge_date.desc(),
            )
        ).first()

    def _with_implied_flow(self, record: FundDailyMetric) -> FundDailyMetric:
        if record.implied_flow_usd is not None:
            return record
        previous = self.session.exec(
            select(FundDailyMetricRow)
            .where(
                FundDailyMetricRow.source == record.source,
                FundDailyMetricRow.fund_ticker == record.fund_ticker,
                FundDailyMetricRow.report_date < record.report_date,
                FundDailyMetricRow.quarantine.is_(False),
            )
            .order_by(FundDailyMetricRow.report_date.desc())
        ).first()
        return derive_implied_flow(
            current=record,
            previous=_row_to_fund_metric(previous) if previous is not None else None,
        )


def _signed_news_impact(row: NewsArticleRow) -> float:
    sign = _NEWS_DIRECTION_SIGN.get(row.impact_direction, 0.0)
    return sign * (row.importance_score / 100.0) * row.confidence


def _cot_swap_dealer_net(row: CotPositionRow) -> float | None:
    if row.swap_dealer_long is None or row.swap_dealer_short is None:
        return None
    return float(row.swap_dealer_long - row.swap_dealer_short)


def _carry(
    front_month: FuturesSettlementRow | None,
    second_month: FuturesSettlementRow | None,
) -> float | None:
    if front_month is None or second_month is None:
        return None
    if front_month.settlement_price == 0:
        return None
    return (front_month.settlement_price - second_month.settlement_price) / (
        front_month.settlement_price
    )


def _carry_from_curve(curve: Sequence[FuturesSettlementRow]) -> float | None:
    ordered = sorted(curve, key=lambda row: row.contract_month)
    if len(ordered) < 2:
        return None
    return _carry(ordered[0], ordered[1])


def _settlement_spread(
    nearer: FuturesSettlementRow | None,
    farther: FuturesSettlementRow | None,
) -> float | None:
    if nearer is None or farther is None:
        return None
    return nearer.settlement_price - farther.settlement_price


def _curve_curvature(
    first: FuturesSettlementRow | None,
    second: FuturesSettlementRow | None,
    third: FuturesSettlementRow | None,
) -> float | None:
    if first is None or second is None or third is None:
        return None
    return first.settlement_price - (2 * second.settlement_price) + third.settlement_price


def _settlement_return(
    current: FuturesSettlementRow | None,
    previous: FuturesSettlementRow | None,
) -> float | None:
    if current is None or previous is None:
        return None
    if previous.settlement_price == 0:
        return None
    return (current.settlement_price / previous.settlement_price) - 1


def _settlement_for_contract(
    curve: Sequence[FuturesSettlementRow],
    contract_month: date,
) -> FuturesSettlementRow | None:
    return next((row for row in curve if row.contract_month == contract_month), None)


def _contract_at_month_offset(
    curve: Sequence[FuturesSettlementRow],
    front_month: FuturesSettlementRow | None,
    *,
    month_offset: int,
) -> FuturesSettlementRow | None:
    if front_month is None:
        return None
    return next(
        (
            row
            for row in curve
            if _month_delta(front_month.contract_month, row.contract_month) == month_offset
        ),
        None,
    )


def _month_delta(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def _latest_zscore(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    standard_deviation = pstdev(values)
    if standard_deviation == 0:
        return None
    return (values[0] - fmean(values)) / standard_deviation


def _latest_min_max_index(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return None
    return (values[0] - minimum) / (maximum - minimum) * 100


def _roll_window_flag(value: date) -> float:
    if value.weekday() >= 5:
        return 0.0
    business_day = _business_day_of_month(value)
    if ROLL_WINDOW_START_BUSINESS_DAY <= business_day <= ROLL_WINDOW_END_BUSINESS_DAY:
        return 1.0
    return 0.0


def _business_day_of_month(value: date) -> int:
    current = date(value.year, value.month, 1)
    business_days = 0
    while current <= value:
        if current.weekday() < 5:
            business_days += 1
        current += timedelta(days=1)
    return business_days


def _to_db_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _row_to_cot_position(row: CotPositionRow) -> CotPosition:
    return CotPosition(
        source=row.source,
        commodity=row.commodity,
        market_name=row.market_name,
        contract_market_code=row.contract_market_code,
        report_date=row.report_date,
        knowledge_date=row.knowledge_date,
        open_interest=row.open_interest,
        swap_dealer_long=row.swap_dealer_long,
        swap_dealer_short=row.swap_dealer_short,
        swap_dealer_spread=row.swap_dealer_spread,
        producer_merchant_long=row.producer_merchant_long,
        producer_merchant_short=row.producer_merchant_short,
        managed_money_long=row.managed_money_long,
        managed_money_short=row.managed_money_short,
        other_reportable_long=row.other_reportable_long,
        other_reportable_short=row.other_reportable_short,
        quarantine=row.quarantine,
    )


def _row_to_fund_metric(row: FundDailyMetricRow) -> FundDailyMetric:
    return FundDailyMetric(
        source=row.source,
        fund_ticker=row.fund_ticker,
        report_date=row.report_date,
        knowledge_date=row.knowledge_date,
        nav_per_share=row.nav_per_share,
        shares_outstanding=row.shares_outstanding,
        total_net_assets=row.total_net_assets,
        implied_flow_usd=row.implied_flow_usd,
        quarantine=row.quarantine,
    )


def _row_to_fund_holding(row: FundHoldingRow) -> FundHolding:
    return FundHolding(
        source=row.source,
        fund_ticker=row.fund_ticker,
        holding_key=row.holding_key,
        holding_name=row.holding_name,
        instrument_type=row.instrument_type,
        ticker=row.ticker,
        report_date=row.report_date,
        knowledge_date=row.knowledge_date,
        contract_month=row.contract_month,
        quantity=row.quantity,
        market_value=row.market_value,
        percent_nav=row.percent_nav,
        quarantine=row.quarantine,
    )


def _row_to_futures_settlement(row: FuturesSettlementRow) -> FuturesSettlement:
    return FuturesSettlement(
        source=row.source,
        product_code=row.product_code,
        report_date=row.report_date,
        knowledge_date=row.knowledge_date,
        contract_month=row.contract_month,
        settlement_price=row.settlement_price,
        open_interest=row.open_interest,
        quarantine=row.quarantine,
    )


def _row_to_news_article(row: NewsArticleRow) -> NewsArticle:
    return NewsArticle(
        source=row.source,
        report_date=row.report_date,
        knowledge_date=row.knowledge_date,
        published_at=row.published_at,
        url=row.url,
        url_hash=row.url_hash,
        title=row.title,
        canonical_url=row.canonical_url,
        summary=row.summary,
        tone=row.tone,
        commodity=row.commodity,
        contract_family=row.contract_family,
        catalyst_type=row.catalyst_type,
        importance_score=row.importance_score,
        impact_direction=row.impact_direction,
        spread_impact_direction=row.spread_impact_direction,
        confidence=row.confidence,
        rationale=row.rationale,
        quarantine=row.quarantine,
    )


def _row_to_daily_prediction(row: DailyPredictionRow) -> DailyPrediction:
    return DailyPrediction(
        source=row.source,
        commodity=row.commodity,
        report_date=row.report_date,
        knowledge_date=row.knowledge_date,
        horizon_days=row.horizon_days,
        feature_report_date=row.feature_report_date,
        price_up_probability=row.price_up_probability,
        spread_up_probability=row.spread_up_probability,
        price_naive_probability=row.price_naive_probability,
        spread_naive_probability=row.spread_naive_probability,
        price_model_version=row.price_model_version,
        spread_model_version=row.spread_model_version,
        price_top_drivers=row.price_top_drivers,
        spread_top_drivers=row.spread_top_drivers,
        quarantine=row.quarantine,
    )


def _row_to_daily_feature(row: DailyFeatureRowModel) -> DailyFeatureRow:
    return DailyFeatureRow(
        source=row.source,
        commodity=row.commodity,
        report_date=row.report_date,
        knowledge_date=row.knowledge_date,
        cl_front_month_settlement=row.cl_front_month_settlement,
        cl_m1_m2_spread=row.cl_m1_m2_spread,
        cl_m2_m3_spread=row.cl_m2_m3_spread,
        cl_m3_m6_spread=row.cl_m3_m6_spread,
        cl_curve_curvature_m1_m2_m3=row.cl_curve_curvature_m1_m2_m3,
        cl_front_month_return_1d=row.cl_front_month_return_1d,
        cl_carry_m1_m2=row.cl_carry_m1_m2,
        cl_carry_m1_m2_change_1d=row.cl_carry_m1_m2_change_1d,
        cot_swap_dealer_net=row.cot_swap_dealer_net,
        cot_swap_dealer_net_zscore=row.cot_swap_dealer_net_zscore,
        cot_swap_dealer_net_index=row.cot_swap_dealer_net_index,
        cot_open_interest=row.cot_open_interest,
        inventory_value=row.inventory_value,
        inventory_seasonal_surprise=row.inventory_seasonal_surprise,
        usd_index_value=row.usd_index_value,
        real_yield_10y=row.real_yield_10y,
        crowding_aum_to_oi=row.crowding_aum_to_oi,
        crowding_contracts_to_oi=row.crowding_contracts_to_oi,
        roll_window_flag=row.roll_window_flag,
        roll_window_crowding_interaction=row.roll_window_crowding_interaction,
        news_count=row.news_count,
        news_tone_mean=row.news_tone_mean,
        news_impact_score=row.news_impact_score,
        quarantine=row.quarantine,
    )
