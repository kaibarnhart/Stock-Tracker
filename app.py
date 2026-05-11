import os
import sqlite3
from datetime import datetime, date

import yfinance as yf
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
app.secret_key = "super-simple-secret-key"


# -----------------------------
# DATABASE
# -----------------------------
def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), "stock_db.sqlite3")
    conn = sqlite3.connect(db_path)
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT UNIQUE NOT NULL,
            date_added TEXT NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()


init_db()


# -----------------------------
# STOCK HELPERS
# -----------------------------
def format_large_number(n):
    if n is None:
        return "-"
    try:
        n = float(n)
        if abs(n) >= 1_000_000_000_000:
            return f"{n / 1_000_000_000_000:.2f}T"
        if abs(n) >= 1_000_000_000:
            return f"{n / 1_000_000_000:.2f}B"
        if abs(n) >= 1_000_000:
            return f"{n / 1_000_000:.2f}M"
        return f"{n:,.0f}"
    except Exception:
        return "-"


def safe_round(value, digits=2):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except Exception:
        return None


def get_stock_object(ticker):
    ticker = ticker.strip().upper()
    if not ticker:
        return None, None
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return stock, info
    except Exception as e:
        print("STOCK OBJECT ERROR:", e)
        return None, None


def fetch_stock_overview(ticker):
    ticker = ticker.strip().upper()
    if not ticker:
        return None

    try:
        stock, info = get_stock_object(ticker)
        if not stock:
            return None

        symbol = info.get("symbol", ticker)
        long_name = info.get("longName") or info.get("shortName") or symbol
        currency = info.get("currency", "USD")

        current_price = info.get("currentPrice")
        previous_close = info.get("previousClose")

        if current_price is None:
            hist = stock.history(period="2d", interval="1d")
            if not hist.empty:
                current_price = float(hist["Close"].dropna().iloc[-1])
                if len(hist["Close"].dropna()) >= 2:
                    previous_close = float(hist["Close"].dropna().iloc[-2])

        if current_price is None:
            return None

        price_change = None
        change_percent = None
        if previous_close not in (None, 0):
            price_change = current_price - previous_close
            change_percent = (price_change / previous_close) * 100

        overview = {
            "symbol": symbol,
            "name": long_name,
            "currency": currency,
            "price": safe_round(current_price),
            "price_change": safe_round(price_change),
            "change_percent": safe_round(change_percent),
            "open": safe_round(info.get("open")),
            "day_high": safe_round(info.get("dayHigh")),
            "day_low": safe_round(info.get("dayLow")),
            "market_cap": format_large_number(info.get("marketCap")),
            "trailing_pe": safe_round(info.get("trailingPE")),
            "fifty_two_week_high": safe_round(info.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": safe_round(info.get("fiftyTwoWeekLow")),
        }

        return overview

    except Exception as e:
        print("OVERVIEW ERROR:", e)
        return None


def get_history_params(range_key):
    today = date.today()
    if range_key == "1D":
        return {"period": "1d", "interval": "5m"}
    if range_key == "5D":
        return {"period": "5d", "interval": "30m"}
    if range_key == "1M":
        return {"period": "1mo", "interval": "1d"}
    if range_key == "6M":
        return {"period": "6mo", "interval": "1d"}
    if range_key == "YTD":
        start = f"{today.year}-01-01"
        return {"start": start, "interval": "1d"}
    if range_key == "1Y":
        return {"period": "1y", "interval": "1d"}
    if range_key == "5Y":
        return {"period": "5y", "interval": "1wk"}
    if range_key == "MAX":
        return {"period": "max", "interval": "1mo"}
    return {"period": "1mo", "interval": "1d"}


def fetch_chart_data(ticker, range_key="1M"):
    ticker = ticker.strip().upper()
    if not ticker:
        return {"labels": [], "prices": []}

    try:
        stock = yf.Ticker(ticker)
        params = get_history_params(range_key)
        hist = stock.history(**params)

        if hist.empty:
            return {"labels": [], "prices": []}

        hist = hist.dropna(subset=["Close"])

        labels = []
        prices = []

        for idx, row in hist.iterrows():
            if range_key == "1D":
                labels.append(idx.strftime("%-I:%M %p"))
            elif range_key == "5D":
                labels.append(idx.strftime("%b %-d %-I:%M %p"))
            elif range_key in {"1M", "6M", "YTD", "1Y"}:
                labels.append(idx.strftime("%b %-d"))
            else:
                labels.append(idx.strftime("%b %Y"))

            prices.append(round(float(row["Close"]), 2))

        return {"labels": labels, "prices": prices}

    except Exception as e:
        print("CHART ERROR:", e)
        return {"labels": [], "prices": []}


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        ticker = request.form.get("ticker", "").strip().upper()
        if not ticker:
            flash("Please enter a ticker.", "error")
            return redirect(url_for("index"))
        return redirect(url_for("stock_page", ticker=ticker))

    return render_template("index.html")


@app.route("/stock/<ticker>")
def stock_page(ticker):
    stock = fetch_stock_overview(ticker)

    if not stock:
        flash("Could not find that ticker. Please try again.", "error")
        return redirect(url_for("index"))

    chart_data = fetch_chart_data(ticker, "1M")
    return render_template(
        "stock.html",
        stock=stock,
        default_range="1M",
        chart_labels=chart_data["labels"],
        chart_prices=chart_data["prices"],
    )


@app.route("/api/history/<ticker>")
def api_history(ticker):
    range_key = request.args.get("range", "1M").upper()
    chart_data = fetch_chart_data(ticker, range_key)
    return jsonify(chart_data)


@app.route("/add/<ticker>")
def add_to_watchlist(ticker):
    ticker = ticker.strip().upper()
    if not ticker:
        flash("No ticker provided.", "error")
        return redirect(url_for("index"))

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT OR IGNORE INTO watchlist (ticker, date_added) VALUES (?, ?)",
            (ticker, datetime.utcnow().isoformat()),
        )
        conn.commit()
        flash(f"{ticker} added to watchlist.", "success")
    except Exception as e:
        print("ADD ERROR:", e)
        flash("Error adding ticker to watchlist.", "error")
    finally:
        conn.close()

    return redirect(url_for("watchlist"))


@app.route("/watchlist")
def watchlist():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, ticker, date_added FROM watchlist ORDER BY date_added DESC")
    rows = cur.fetchall()
    conn.close()

    stocks = []

    for row in rows:
        watch_id, ticker, date_added = row
        quote = fetch_stock_overview(ticker)

        if quote:
            stocks.append(
                {
                    "id": watch_id,
                    "ticker": ticker,
                    "price": quote.get("price"),
                    "change_percent": quote.get("change_percent"),
                    "date_added": date_added,
                }
            )
        else:
            stocks.append(
                {
                    "id": watch_id,
                    "ticker": ticker,
                    "price": None,
                    "change_percent": None,
                    "date_added": date_added,
                }
            )

    return render_template("watchlist.html", stocks=stocks)


@app.route("/delete/<int:watch_id>", methods=["POST"])
def delete_from_watchlist(watch_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM watchlist WHERE id = ?", (watch_id,))
    conn.commit()
    conn.close()

    flash("Deleted from watchlist.", "success")
    return redirect(url_for("watchlist"))


if __name__ == "__main__":
    app.run(debug=True)