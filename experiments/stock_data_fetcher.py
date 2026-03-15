import yfinance as yf
import pandas as pd

def search_ticker(query: str):
    """
    Searches Yahoo Finance for a company or ETF and returns the best match ticker.
    """
    search = yf.Search(query)
    results = search.quotes # a list
    print(type(results))
    if not results:
        print("No results found.")
        return None

    # Take first result
    ticker = results[0]["symbol"]
    name = results[0].get("shortname", "N/A")

    print(f"\nFound: {name} ({ticker})")
    return ticker


def get_asset_data(ticker: str):
    """
    Fetches company info + 1 year historical data.
    """
    asset = yf.Ticker(ticker)

    # --- Basic Info ---
    info = asset.info

    print("\n===== BASIC INFORMATION =====")
    print("Company Name:", info.get("longName"))
    print("Symbol:", info.get("symbol"))
    print("Current Price:", info.get("currentPrice"))
    print("Market Cap:", info.get("marketCap"))
    print("52 Week High:", info.get("fiftyTwoWeekHigh"))
    print("52 Week Low:", info.get("fiftyTwoWeekLow"))
    print("PE Ratio:", info.get("trailingPE"))

    # --- Historical Data ---
    print("\nFetching 1 year historical data...")
    hist = asset.history(period="1y")

    print("Number of records:", len(hist))
    print("\nLast 5 days of data:")
    print(hist.tail())

    return hist


if __name__ == "__main__":
    user_input = input("Enter company name or ticker: ")

    # If user enters ticker directly (like AAPL)
    if len(user_input) <= 5 and user_input.isupper():
        ticker = user_input
    else:
        ticker = search_ticker(user_input)

    if ticker:
        data = get_asset_data(ticker)
