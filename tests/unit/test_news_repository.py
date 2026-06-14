from datetime import UTC, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

from energy_etf_monitor.news.dedup import url_hash
from energy_etf_monitor.records import NewsArticle
from energy_etf_monitor.storage.repository import IngestionRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _article(
    *,
    url: str,
    title: str,
    published: datetime,
    knowledge: datetime | None = None,
    importance: float = 50.0,
    direction: str = "Bullish",
) -> NewsArticle:
    return NewsArticle(
        source="gdelt",
        report_date=published.date(),
        knowledge_date=knowledge or published,
        published_at=published,
        url=url,
        url_hash=url_hash(url),
        title=title,
        commodity="WTI",
        catalyst_type="opec",
        importance_score=importance,
        impact_direction=direction,
        confidence=0.7,
        rationale="OPEC supply change",
    )


def test_upsert_news_articles_is_idempotent_on_source_and_url_hash(session: Session) -> None:
    repository = IngestionRepository(session)
    article = _article(
        url="https://a.com/x",
        title="OPEC cuts output",
        published=datetime(2026, 6, 12, 9, tzinfo=UTC),
    )
    first = repository.upsert_news_articles([article])
    assert (first.inserted, first.updated) == (1, 0)

    updated_article = _article(
        url="https://a.com/x",
        title="OPEC cuts output (updated)",
        published=datetime(2026, 6, 12, 9, tzinfo=UTC),
        importance=80.0,
    )
    second = repository.upsert_news_articles([updated_article])
    assert (second.inserted, second.updated) == (0, 1)

    stored = repository.list_news_articles()
    assert len(stored) == 1
    assert stored[0].importance_score == 80.0


def test_list_news_articles_respects_knowledge_date_and_importance(session: Session) -> None:
    repository = IngestionRepository(session)
    repository.upsert_news_articles(
        [
            _article(
                url="https://a.com/1",
                title="Big OPEC cut",
                published=datetime(2026, 6, 12, 9, tzinfo=UTC),
                knowledge=datetime(2026, 6, 12, 9, tzinfo=UTC),
                importance=90.0,
            ),
            _article(
                url="https://a.com/2",
                title="Minor pipeline note",
                published=datetime(2026, 6, 12, 9, tzinfo=UTC),
                knowledge=datetime(2026, 6, 12, 9, tzinfo=UTC),
                importance=20.0,
            ),
            _article(
                url="https://a.com/3",
                title="Future scoop",
                published=datetime(2026, 6, 12, 23, tzinfo=UTC),
                knowledge=datetime(2026, 6, 12, 23, tzinfo=UTC),
                importance=95.0,
            ),
        ]
    )

    # As of noon, the 23:00 article is not yet known; importance filter drops the minor one.
    visible = repository.list_news_articles(
        as_of=datetime(2026, 6, 12, 12, tzinfo=UTC),
        min_importance=50.0,
    )
    assert [article.title for article in visible] == ["Big OPEC cut"]


def test_upsert_news_articles_quarantines_invalid_direction(session: Session) -> None:
    repository = IngestionRepository(session)
    bad = _article(
        url="https://a.com/x",
        title="weird",
        published=datetime(2026, 6, 12, 9, tzinfo=UTC),
        direction="VeryBullish",
    )
    result = repository.upsert_news_articles([bad])
    assert result.quarantined == 1
    # Quarantined rows are excluded from the panel listing.
    assert repository.list_news_articles() == []
