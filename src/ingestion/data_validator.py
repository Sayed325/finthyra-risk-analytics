#author: @ShoumikDutta
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
import logging

load_dotenv()

# ---------- Setup ----------
logger = logging.getLogger("data_validator")
logging.basicConfig(level=logging.INFO)



SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY") 

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------- Helpers ----------
def today():
    return datetime.utcnow().date()


def days_ago(n):
    return today() - timedelta(days=n)


# ---------- Check 1: Completeness ----------
def check_completeness():
    issues = []

    assets = supabase.table("assets").select("id,ticker").eq("is_active", True).execute().data

    for asset in assets:
        asset_id = asset["id"]
        ticker = asset["ticker"]

        rows = (
            supabase.table("prices")
            .select("date")
            .eq("asset_id", asset_id)
            .gte("date", days_ago(7).isoformat())
            .execute()
            .data
        )

        if not rows:
            issues.append(f"{ticker}: no data in last 7 days")
            continue

        dates = sorted([r["date"] for r in rows])

        # simple gap check (not exact trading calendar, but good baseline)
        if len(dates) < 3:
            issues.append(f"{ticker}: missing recent trading days")

    return issues


# ---------- Check 2: Freshness ----------
def check_freshness():
    issues = []

    assets = supabase.table("assets").select("id,ticker").eq("is_active", True).execute().data

    for asset in assets:
        asset_id = asset["id"]
        ticker = asset["ticker"]

        row = (
            supabase.table("prices")
            .select("date")
            .eq("asset_id", asset_id)
            .order("date", desc=True)
            .limit(1)
            .execute()
            .data
        )

        if not row:
            issues.append(f"{ticker}: no data at all")
            continue

        last_date = datetime.fromisoformat(row[0]["date"]).date()

        if (today() - last_date).days > 3:
            issues.append(f"{ticker}: stale data ({last_date})")

    # Macro indicators
    macro_rows = (
        supabase.table("macro_indicators")
        .select("indicator,date")
        .order("date", desc=True)
        .execute()
        .data
    )

    latest_per_indicator = {}
    for r in macro_rows:
        ind = r["indicator"]
        if ind not in latest_per_indicator:
            latest_per_indicator[ind] = r["date"]

    for ind, d in latest_per_indicator.items():
        last_date = datetime.fromisoformat(d).date()

        if ind == "cpi":
            if (today() - last_date).days > 45:
                issues.append(f"{ind}: too old ({last_date})")
        else:
            if (today() - last_date).days > 3:
                issues.append(f"{ind}: stale ({last_date})")

    return issues


# ---------- Check 3: Sanity ----------
def check_sanity():
    issues = []

    rows = supabase.table("prices").select("*").limit(1000).execute().data

    for r in rows:
        if r["close"] is not None and r["close"] <= 0:
            issues.append(f"asset {r['asset_id']} bad close {r['close']}")

        if r["volume"] is not None and r["volume"] < 0:
            issues.append(f"asset {r['asset_id']} bad volume {r['volume']}")

        if r["daily_return"] is not None:
            if r["daily_return"] < -0.5 or r["daily_return"] > 0.5:
                issues.append(f"asset {r['asset_id']} abnormal return {r['daily_return']}")

    macro = supabase.table("macro_indicators").select("*").limit(500).execute().data

    for r in macro:
        val = r["value"]

        if val is None:
            continue

        if r["indicator"] == "vix":
            if val < 5 or val > 100:
                issues.append(f"VIX out of range: {val}")
        else:
            if val <= 0:
                issues.append(f"{r['indicator']} invalid value {val}")

    return issues


# ---------- Check 4: Duplicates ----------
def check_duplicates():
    issues = []

    # prices duplicates
    rows = supabase.table("prices").select("asset_id,date").execute().data

    seen = set()
    for r in rows:
        key = (r["asset_id"], r["date"])
        if key in seen:
            issues.append(f"duplicate price: {key}")
        seen.add(key)

    # macro duplicates
    rows = supabase.table("macro_indicators").select("indicator,date").execute().data

    seen = set()
    for r in rows:
        key = (r["indicator"], r["date"])
        if key in seen:
            issues.append(f"duplicate macro: {key}")
        seen.add(key)

    return issues


# ---------- Main ----------
def validate_data():
    completeness_issues = check_completeness()
    freshness_issues = check_freshness()
    sanity_issues = check_sanity()
    duplicate_issues = check_duplicates()

    status = "pass"

    if sanity_issues or duplicate_issues:
        status = "fail"
    elif completeness_issues or freshness_issues:
        status = "warn"

    report = {
        "status": status,
        "checks": {
            "completeness": {
                "status": "pass" if not completeness_issues else "warn",
                "details": completeness_issues,
            },
            "freshness": {
                "status": "pass" if not freshness_issues else "warn",
                "details": freshness_issues,
            },
            "sanity": {
                "status": "pass" if not sanity_issues else "fail",
                "details": sanity_issues,
            },
            "duplicates": {
                "status": "pass" if not duplicate_issues else "fail",
                "details": duplicate_issues,
            },
        },
        "timestamp": datetime.utcnow().isoformat(),
    }

    logger.info(report)
    return report


if __name__ == "__main__":
    result = validate_data()
    print(result)
"""Data quality checks and validation."""
