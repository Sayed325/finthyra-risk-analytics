from src.ingestion.common import get_supabase

supabase = get_supabase()

new_assets = [
    {
        "ticker": "IVV",
        "name": "iShares Core S&P 500 ETF",
        "asset_class": "etf",
        "region": "us",
        "currency": "USD",
        "is_benchmark": False,
        "is_active": True,
    },
    {
        "ticker": "VTI",
        "name": "Vanguard Total Stock Market ETF",
        "asset_class": "etf",
        "region": "us",
        "currency": "USD",
        "is_benchmark": False,
        "is_active": True,
    },
]

supabase.table("assets").upsert(new_assets).execute()

print("✅ Assets added")