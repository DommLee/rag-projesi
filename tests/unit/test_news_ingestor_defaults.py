from app.ingestion.news import NewsIngestor


def test_news_ingestor_defaults_use_open_primary_feeds_only() -> None:
    ingestor = NewsIngestor()
    ingestor.settings.news_enable_discovery = False
    urls = ingestor._default_feed_urls("ASELS")
    assert any("aa.com.tr" in url for url in urls)
    assert any("bloomberght.com" in url for url in urls)
    assert any("paraanaliz.com" in url for url in urls)
    assert any("ekonomim.com" in url for url in urls)
    assert any("bigpara.hurriyet.com.tr" in url for url in urls)
    assert all("news.google.com" not in url for url in urls)


def test_news_ingestor_can_enable_discovery_feeds() -> None:
    ingestor = NewsIngestor()
    ingestor.settings.news_enable_discovery = True
    urls = ingestor._default_feed_urls("ASELS")
    assert any("news.google.com" in url for url in urls)
