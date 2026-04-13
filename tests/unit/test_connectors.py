from app.connectors.binance_spot import BinanceSpotContextConnector
from app.connectors.coingecko import CoinGeckoContextConnector
from app.connectors.premium_news import PremiumNewsConnector
from app.connectors.tcmb import TCMBMacroConnector
from app.connectors.x_signal import XSignalConnector
from app.config import get_settings
from app.sources.catalog import build_source_catalog


def test_tcmb_connector_disabled_without_key() -> None:
    connector = TCMBMacroConnector()
    connector.settings.tcmb_evds_api_key = ""
    snapshot = connector.fetch_snapshot()
    assert snapshot["enabled"] is False
    assert snapshot["status"] == "disabled"


def test_premium_news_connector_disabled_without_keys() -> None:
    connector = PremiumNewsConnector()
    connector.settings.eventregistry_api_key = ""
    connector.settings.newsapi_ai_key = ""
    snapshot = connector.fetch_candidates("ASELS")
    assert snapshot["enabled"] is False
    assert snapshot["provider"] == "disabled"


def test_x_signal_connector_disabled_without_token() -> None:
    connector = XSignalConnector()
    connector.settings.x_api_bearer_token = ""
    snapshot = connector.fetch_signal("ASELS")
    assert snapshot["enabled"] is False
    assert snapshot["status"] == "disabled"


def test_tcmb_connector_uses_configured_series_csv() -> None:
    connector = TCMBMacroConnector()
    connector.settings.tcmb_evds_series_csv = "usd_try:TP.DK.USD.A.YTL,bist100:TP.MK.F.BILESIK.TUM"
    series_map = connector._series_map()
    assert series_map["usd_try"] == "TP.DK.USD.A.YTL"
    assert series_map["bist100"] == "TP.MK.F.BILESIK.TUM"


def test_source_catalog_discovery_disabled_by_default() -> None:
    settings = get_settings()
    original = settings.news_enable_discovery
    settings.news_enable_discovery = False
    try:
        catalog = {item.key: item for item in build_source_catalog()}
        assert catalog["google_news_discovery"].enabled is False
        assert catalog["ekonomim_rss"].enabled is True
        assert catalog["bigpara_rss"].enabled is True
    finally:
        settings.news_enable_discovery = original


def test_crypto_connectors_disabled_when_feature_off() -> None:
    coingecko = CoinGeckoContextConnector()
    binance = BinanceSpotContextConnector()
    coingecko.settings.crypto_context_enabled = False
    binance.settings.crypto_context_enabled = False

    cg = coingecko.fetch_context(["BTC", "ETH"])
    bn = binance.fetch_context(["BTC", "ETH"])

    assert cg["enabled"] is False
    assert bn["enabled"] is False


def test_source_catalog_contains_crypto_context_entries() -> None:
    catalog = {item.key: item for item in build_source_catalog()}
    assert catalog["coingecko_context"].asset_scope == "crypto"
    assert catalog["binance_spot_context"].asset_scope == "crypto"
