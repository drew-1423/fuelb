"""Explicit identities: a crude or retail proxy never becomes a Med assessment."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Series:
    id: str
    source: str
    title: str
    role: str
    unit: str
    normalized_unit: str
    factor: float
    frequency: str
    timezone: str
    url: str
    research_lag_days: int
    stale_days: int

    def metadata(self):
        return dict(asdict(self), publication_timestamp_status="unknown_per_observation",
                    vintage_status="latest_download_not_historical_vintage",
                    research_lag_status="assumption_not_verified_release_history")


EIA = "https://www.eia.gov/dnav/pet/hist/"
EC = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"
BARREL_LITERS = 158.987294928
FUTURES = {
    'brent_futures': {'symbol':'BZ=F', 'fallback':'brent_spot'},
    'rbob_futures': {'symbol':'RB=F', 'fallback':'nyh_gasoline'},
    'gasoil_futures': {'symbol':'HO=F', 'fallback':None},
}
CBOE_OVX_URL = "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/OVX_History.csv"
FRED_OVX_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=OVXCLS"
SERIES = {s.id: s for s in [
    Series("brent_spot", "market_eia", "EIA Europe Brent spot FOB", "crude_benchmark_proxy_for_gasoline", "USD/bbl", "USD/bbl", 1, "daily", "Europe/London", EIA+"RBRTED.htm", 14, 14),
    Series("nyh_gasoline", "market_eia", "EIA NY Harbor conventional regular gasoline FOB", "US_refined_product_proxy_not_Med_95", "USD/US_gal", "USD/bbl", 42, "daily", "America/New_York", EIA+"EER_EPMRU_PF4_Y35NY_DPGD.htm", 14, 14),
    Series("us_gasoline_stocks", "market_eia", "US weekly total gasoline ending stocks", "US_inventory_indicator", "thousand_bbl", "million_bbl", .001, "weekly", "America/New_York", EIA+"LeafHandler.ashx?n=PET&s=WGTSTUS1&f=W", 14, 21),
    Series("us_crude_stocks", "market_eia", "US weekly crude ending stocks excluding SPR", "US_inventory_indicator", "thousand_bbl", "million_bbl", .001, "weekly", "America/New_York", EIA+"LeafHandler.ashx?n=PET&s=WCESTUS1&f=W", 14, 21),
    Series("us_refinery_utilization", "market_eia", "US operable refinery capacity utilization", "US_supply_indicator_not_Med_utilization", "percent", "percent", 1, "weekly", "America/New_York", EIA+"LeafHandler.ashx?n=PET&s=WPULEUS3&f=W", 14, 21),
    Series("eurusd", "market_fed", "Federal Reserve H.10 direct XML RXI$US_N.B.EU", "FX_USD_per_EUR_not_LBP", "USD/EUR", "USD/EUR", 1, "daily", "America/New_York", "https://www.federalreserve.gov/releases/h10/hist/dat00_eu.htm", 10, 14),
    Series("italy_gasoline_ex_tax", "market_ec", "Italy Euro-super 95 consumer price excluding taxes", "European_retail_proxy_not_wholesale", "EUR/1000L", "EUR/L", .001, "weekly", "Europe/Brussels", EC, 7, 21),
    Series("greece_gasoline_ex_tax", "market_ec", "Greece Euro-super 95 consumer price excluding taxes", "European_retail_proxy_not_wholesale", "EUR/1000L", "EUR/L", .001, "weekly", "Europe/Brussels", EC, 7, 21),
    Series("lbp_payment_fx", "market_official_review", "MOEW decision USD customer payment conversion", "official_document_customer_payment_FX_not_full_formula", "LBP/USD", "LBP/USD", 1, "irregular", "Asia/Beirut", "https://energyandwater.gov.lb/mediafiles/prices/1-2025-05-29.pdf", 1, 7),
    Series('brent_futures', 'market_yahoo', 'Yahoo BZ=F Brent last-day financial futures (NYMEX)',
           'continuous_Brent_futures_proxy_not_direct_ICE_contract_history', 'USD/bbl', 'USD/bbl', 1,
           'daily', 'America/New_York', 'https://finance.yahoo.com/quote/BZ=F/history/', 0, 7),
    Series('rbob_futures', 'market_yahoo', 'Yahoo RB=F NYMEX RBOB gasoline futures',
           'US_gasoline_continuous_futures_proxy_not_Med_95', 'USD/US_gal', 'USD/bbl', 42,
           'daily', 'America/New_York', 'https://finance.yahoo.com/quote/RB=F/history/', 0, 7),
    Series('gasoil_futures', 'market_yahoo', 'Yahoo HO=F NYMEX NY Harbor ULSD / heating oil futures',
           'US_distillate_continuous_futures_proxy_not_ICE_gasoil', 'USD/US_gal', 'USD/bbl', 42,
           'daily', 'America/New_York', 'https://finance.yahoo.com/quote/HO=F/history/', 0, 7),
    Series("cboe_ovx", "market_cboe", "Cboe Crude Oil ETF Volatility Index (OVX)",
           "USO_options_implied_volatility_not_Lebanese_gasoline_volatility",
           "percent_annualized", "percent_annualized", 1, "daily", "America/New_York", CBOE_OVX_URL, 0, 7),
]}

MISSING = {
    "platts_AAWZA00": "Genuine FOB Med 95 RON assessment; licensed history and release vintages absent; exact current Lebanese retail symbol unverified.",
    "platts_AAWZB00": "Genuine CIF Med assessment includes freight; licensed history absent; do not add freight twice.",
    "eurobob_wholesale": "ARA barge gasoline is a different regional/product basis; licensed history absent.",
    "ice_brent_contracts": "Actual futures contracts and settlements absent; need licensed contract history, expiration calendar and explicit roll policy.",
    "med_clean_freight": "No authorized Med clean-product freight/war-risk premium history obtained; Baltic data need a licence.",
    "med_refinery_outages": "No verified dated structured regional outage/capacity history obtained.",
    "pricing_formula_fx": "Only one reviewed customer-payment FX observation; full formula FX series and regime transitions remain unresolved.",
    "opec_monthly": "Public monthly reports available as context; structured vintage-preserving extraction deferred, no invented observations.",
}
