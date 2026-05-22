"""
Set the active asset universe for Finthyra.

Active (is_active=TRUE):  AAPL, MSFT, NVDA, AMZN, GOOGL, SPY, QQQ, VTI
Inactive (is_active=FALSE): SAP, SIE.DE, BAS.DE, ALV.DE, VUSA.L, EUNL.DE, IWDA.L, IVV, VEA
"""

from src.ingestion.common import get_supabase

ACTIVE_TICKERS = {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "SPY", "QQQ", "VTI"}

INACTIVE_TICKERS = {
    "SAP", "SIE.DE", "BAS.DE", "ALV.DE",
    "VUSA.L", "EUNL.DE", "IWDA.L",
    "IVV", "VEA",
}


def set_active_assets() -> None:
    supabase = get_supabase()

    for ticker in INACTIVE_TICKERS:
        supabase.table("assets").update({"is_active": False}).eq("ticker", ticker).execute()

    for ticker in ACTIVE_TICKERS:
        supabase.table("assets").update({"is_active": True}).eq("ticker", ticker).execute()

    rows = supabase.table("assets").select("ticker,is_active").execute().data or []

    active = sorted(r["ticker"] for r in rows if r["is_active"])
    inactive = sorted(r["ticker"] for r in rows if not r["is_active"])

    print("Active assets:")
    for t in active:
        print(f"  ✓ {t}")

    print("\nInactive assets:")
    for t in inactive:
        print(f"  ✗ {t}")

    print(f"\nDone: {len(active)} active, {len(inactive)} inactive.")


if __name__ == "__main__":
    set_active_assets()
