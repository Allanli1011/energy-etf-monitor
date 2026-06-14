from datetime import UTC, date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

from energy_etf_monitor.commodities import WTI
from energy_etf_monitor.records import FuturesSettlement, NewsArticle
from energy_etf_monitor.storage.repository import IngestionRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _settlement() -> FuturesSettlement:
    return FuturesSettlement(
        source="cme",
        product_code="CL",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 12, 16, tzinfo=UTC),
        contract_month=date(2026, 7, 1),
        settlement_price=70.0,
        open_interest=100_000,
    )


def _news(
    *,
    suffix: str,
    direction: str,
    importance: float,
    confidence: float,
    published: datetime,
    knowledge: datetime,
) -> NewsArticle:
    return NewsArticle(
        source="gdelt",
        report_date=published.date(),
        knowledge_date=knowledge,
        published_at=published,
        url=f"https://a.com/{suffix}",
        url_hash=f"hash-{suffix}",
        title=f"headline {suffix}",
        commodity="WTI",
        impact_direction=direction,
        importance_score=importance,
        confidence=confidence,
    )


def test_feature_row_includes_point_in_time_news_aggregates(session: Session) -> None:
    repository = IngestionRepository(session)
    as_of = datetime(2026, 6, 12, 20, tzinfo=UTC)
    repository.upsert_futures_settlements([_settlement()])
    repository.upsert_news_articles(
        [
            _news(
                suffix="bull",
                direction="Bullish",
                importance=80,
                confidence=0.6,
                published=datetime(2026, 6, 12, 9, tzinfo=UTC),
                knowledge=datetime(2026, 6, 12, 9, tzinfo=UTC),
            ),
            _news(
                suffix="bear",
                direction="Bearish",
                importance=40,
                confidence=0.5,
                published=datetime(2026, 6, 11, 9, tzinfo=UTC),
                knowledge=datetime(2026, 6, 11, 9, tzinfo=UTC),
            ),
        ]
    )

    row = repository.derive_feature_row(config=WTI, as_of=as_of)

    assert row.news_count == 2.0
    # mean([+0.80*0.6, -0.40*0.5]) = mean([0.48, -0.20]) = 0.14
    assert row.news_impact_score == pytest.approx(0.14)
    assert row.news_tone_mean is None  # no tone provided


def test_news_aggregates_exclude_articles_not_yet_known(session: Session) -> None:
    repository = IngestionRepository(session)
    repository.upsert_futures_settlements([_settlement()])
    repository.upsert_news_articles(
        [
            _news(
                suffix="late",
                direction="Bullish",
                importance=90,
                confidence=0.7,
                published=datetime(2026, 6, 12, 9, tzinfo=UTC),
                knowledge=datetime(2026, 6, 12, 19, 30, tzinfo=UTC),
            )
        ]
    )

    # Decision at 17:00 (after the 16:00 settlement, before the 19:30 news release):
    # the settlement is a usable source but the article is not yet visible.
    row = repository.derive_feature_row(config=WTI, as_of=datetime(2026, 6, 12, 17, tzinfo=UTC))

    assert row.news_count is None
    assert row.news_impact_score is None
