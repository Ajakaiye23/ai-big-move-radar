"""Data sources behind a uniform interface, gated by config.

`data.mode` selects where data comes from:
  offline -> deterministic synthetic generator (no network) — default, CI, demo
  live    -> yfinance prices + Reddit/Finnhub/GDELT text (needs API keys in env)
  auto    -> try live per-source, fall back to offline on failure/missing keys

Every source is its own feature group (references/data-pipeline.md); the
ablation, not this module, decides which groups earn their place. Raw pulls are
immutable and persisted with a JSON sidecar so the dataset is auditable.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from .. import utils

log = utils.get_logger("data.sources")


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #
def get_prices(ticker: str, cfg: dict) -> tuple[pd.DataFrame, dict]:
    """Return (OHLCV dataframe[date,open,high,low,close,volume], provenance dict)."""
    mode = cfg["data"]["mode"]
    start, end = cfg["data"]["start"], cfg["data"]["end"]
    seed = cfg["project"]["seed"]

    if mode in ("live", "auto"):
        try:
            df = _yfinance_prices(ticker, start, end)
            if len(df) > 30:
                return df, {"source": "yfinance", "ticker": ticker, "rows": len(df)}
            log.warning("yfinance returned %d rows for %s; %s", len(df), ticker,
                        "falling back to synthetic" if mode == "auto" else "")
            if mode == "live":
                raise RuntimeError(f"yfinance returned too little data for {ticker}")
        except Exception as e:  # noqa: BLE001
            if mode == "live":
                raise
            log.warning("yfinance failed for %s (%s); using synthetic prices", ticker, e)

    df = utils.synth_prices(ticker, start, end, seed)
    return df, {"source": "synthetic", "ticker": ticker, "rows": len(df), "seed": seed}


def _yfinance_prices(ticker: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(ticker, start=start, end=end, auto_adjust=True,
                      progress=False, threads=False)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    return raw[["date", "open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------- #
# Text (Reddit / news)
# --------------------------------------------------------------------------- #
def get_text(ticker: str, prices: pd.DataFrame, cfg: dict,
             prices_are_synthetic: bool = True) -> tuple[pd.DataFrame, dict]:
    """Return (text dataframe[id,ticker,timestamp_utc,source,text], provenance).

    Crucial honesty rule: synthetic text is produced ONLY when prices are also
    synthetic. Mixing the injected synthetic sentiment signal with REAL prices
    would fabricate an edge that doesn't exist — so with real prices and no text
    API keys, sentiment is simply absent (no-coverage), never faked.
    """
    mode = cfg["data"]["mode"]
    seed = cfg["project"]["seed"]
    cutoff = cfg["data"]["knowledge_cutoff_et"]
    empty = pd.DataFrame(columns=["id", "ticker", "timestamp_utc", "source", "text"])

    if mode in ("live", "auto"):
        frames = []
        if cfg["data"]["sources"].get("reddit") and _have_reddit_keys():
            try:
                frames.append(_reddit_text(ticker, cfg))
            except Exception as e:  # noqa: BLE001
                log.warning("reddit fetch failed for %s: %s", ticker, e)
        if cfg["data"]["sources"].get("finnhub") and os.getenv("FINNHUB_API_KEY"):
            try:
                frames.append(_finnhub_news(ticker, cfg))
            except Exception as e:  # noqa: BLE001
                log.warning("finnhub fetch failed for %s: %s", ticker, e)
        if cfg["data"]["sources"].get("news_gdelt"):   # free, keyless
            try:
                frames.append(_gdelt_news(ticker, cfg))
            except Exception as e:  # noqa: BLE001
                log.warning("gdelt fetch failed for %s: %s", ticker, e)
        if cfg["data"]["sources"].get("alphavantage_news") and os.getenv("ALPHAVANTAGE_API_KEY"):
            try:
                frames.append(_alphavantage_news(ticker, cfg))
            except Exception as e:  # noqa: BLE001
                log.warning("alphavantage fetch failed for %s: %s", ticker, e)
        frames = [f for f in frames if f is not None and not f.empty]
        if frames:
            df = pd.concat(frames, ignore_index=True).drop_duplicates("id")
            return df, {"source": "live", "ticker": ticker, "rows": len(df)}
        # No live text. If prices are real, return EMPTY (never fake sentiment on
        # real prices). Only synthesize text when prices are synthetic too.
        if not prices_are_synthetic:
            log.warning("no live text for %s (no API keys?) — sentiment will be "
                        "absent for real prices, not faked", ticker)
            return empty, {"source": "none", "ticker": ticker, "rows": 0,
                           "note": "no text API keys; real prices keep sentiment empty"}
        log.warning("no live text for %s; using synthetic posts (synthetic prices)", ticker)

    df = utils.synth_text(ticker, prices, seed, cutoff)
    return df, {"source": "synthetic", "ticker": ticker, "rows": len(df), "seed": seed}


def _have_reddit_keys() -> bool:
    return bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"))


def _reddit_text(ticker: str, cfg: dict) -> pd.DataFrame:
    """Live Reddit pull via PRAW. Filters by cashtag/ticker across configured subs."""
    import praw  # noqa: F401

    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.getenv("REDDIT_USER_AGENT", "ai-stock-sentiment/0.1"),
    )
    rows: list[dict[str, Any]] = []
    for sub in cfg["data"]["subreddits"]:
        for post in reddit.subreddit(sub).search(ticker, sort="new", limit=100):
            ts = pd.Timestamp(post.created_utc, unit="s", tz="UTC")
            text = f"{post.title}. {post.selftext or ''}".strip()
            rows.append({
                "id": post.id,
                "ticker": ticker,
                "timestamp_utc": ts.isoformat(),
                "source": f"reddit:{sub}",
                "text": text[:1000],
            })
    return pd.DataFrame(rows, columns=["id", "ticker", "timestamp_utc", "source", "text"])


# Company names give GDELT/text search far better recall than bare tickers.
_COMPANY_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMD": "AMD",
    "TSLA": "Tesla", "AMZN": "Amazon", "GOOGL": "Google", "META": "Meta",
    "AVGO": "Broadcom", "NFLX": "Netflix", "ORCL": "Oracle", "CRM": "Salesforce",
    "ADBE": "Adobe", "CSCO": "Cisco", "QCOM": "Qualcomm", "INTC": "Intel",
    "MU": "Micron", "MRVL": "Marvell", "ARM": "Arm Holdings", "SMCI": "Super Micro",
    "AMC": "AMC Entertainment", "GME": "GameStop", "PLTR": "Palantir", "COIN": "Coinbase",
    "SOFI": "SoFi", "HOOD": "Robinhood", "MSTR": "MicroStrategy", "RIVN": "Rivian",
    "LCID": "Lucid Motors", "NIO": "Nio", "UBER": "Uber", "ABNB": "Airbnb",
    "SHOP": "Shopify", "PYPL": "PayPal", "DIS": "Disney", "BA": "Boeing",
    "JPM": "JPMorgan", "WMT": "Walmart", "COST": "Costco",
    "SPY": "S&P 500", "QQQ": "Nasdaq 100",
}


def _alphavantage_news(ticker: str, cfg: dict) -> pd.DataFrame:
    """Alpha Vantage NEWS_SENTIMENT — free key, returns articles already scored.
    Free tier is only ~25 requests/day, so it's a light supplement, not a backbone.
    Activates automatically when ALPHAVANTAGE_API_KEY is set."""
    import datetime as dt

    import requests

    key = os.environ["ALPHAVANTAGE_API_KEY"]
    start = dt.date.fromisoformat(str(cfg["data"]["start"]))
    r = requests.get("https://www.alphavantage.co/query", timeout=30, params={
        "function": "NEWS_SENTIMENT", "tickers": ticker, "limit": 1000,
        "time_from": start.strftime("%Y%m%dT0000"), "apikey": key})
    r.raise_for_status()
    rows = []
    for a in r.json().get("feed", []):
        title = a.get("title", "")
        if not title:
            continue
        try:
            ts = pd.Timestamp(dt.datetime.strptime(a["time_published"], "%Y%m%dT%H%M%S"), tz="UTC")
        except (ValueError, KeyError):
            continue
        rows.append({"id": f"av:{utils.stable_hash(a.get('url', title)) % 10**12}",
                     "ticker": ticker, "timestamp_utc": ts.isoformat(),
                     "source": "news:alphavantage", "text": title[:300]})
    return pd.DataFrame(rows, columns=["id", "ticker", "timestamp_utc", "source", "text"])


def _gdelt_news(ticker: str, cfg: dict) -> pd.DataFrame:
    """Free, keyless GDELT 2.0 Doc API — global news/blog headlines, deep history.

    Paginates by date window (GDELT caps ~250 records/query) and respects the
    free-tier ~1 request / 5s limit. Titles feed FinBERT like any other text.
    """
    import datetime as dt
    import time

    import requests

    name = _COMPANY_NAMES.get(ticker, ticker)
    query = f'"{name}" (stock OR shares OR earnings OR stocks)'
    start = dt.date.fromisoformat(str(cfg["data"]["start"]))
    end = dt.date.fromisoformat(str(cfg["data"]["end"]))
    step = dt.timedelta(days=int(os.getenv("GDELT_CHUNK_DAYS", "15")))
    sleep = float(os.getenv("GDELT_SLEEP", "5"))
    url = "https://api.gdeltproject.org/api/v2/doc/doc"

    rows, seen = [], set()
    cur = start
    got_any = False
    while cur <= end:
        ct = min(cur + step, end)
        params = {"query": query, "mode": "artlist", "maxrecords": 250,
                  "format": "json", "sort": "datedesc",
                  "startdatetime": cur.strftime("%Y%m%d000000"),
                  "enddatetime": ct.strftime("%Y%m%d235959")}
        try:
            r = None
            for attempt in range(2):                # light retry on 429 throttle
                r = requests.get(url, params=params, timeout=30,
                                 headers={"User-Agent": "ai-stock-sentiment/0.1"})
                if r.status_code != 429:
                    break
                time.sleep(sleep)
            # Circuit breaker: if GDELT is throttling us and we've gotten nothing,
            # bail out fast instead of crawling all chunks (the IP is rate-limited).
            if r is not None and r.status_code == 429 and not got_any:
                log.warning("gdelt throttled (429) for %s — skipping (re-enable when clear)", ticker)
                break
            if r is not None and r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                got_any = True
                for a in r.json().get("articles", []):
                    title = a.get("title", "")
                    if not title or title in seen:
                        continue
                    seen.add(title)
                    try:
                        ts = pd.Timestamp(dt.datetime.strptime(
                            a.get("seendate", ""), "%Y%m%dT%H%M%SZ"), tz="UTC")
                    except ValueError:
                        continue
                    rows.append({
                        "id": f"gdelt:{utils.stable_hash(a.get('url', title)) % 10**12}",
                        "ticker": ticker,
                        "timestamp_utc": ts.isoformat(),
                        "source": "news:gdelt",
                        "text": title[:300],
                    })
        except Exception as e:  # noqa: BLE001 — isolate per-chunk failures
            log.warning("gdelt chunk %s..%s failed for %s: %s", cur, ct, ticker, e)
        cur = ct + dt.timedelta(days=1)
        time.sleep(sleep)

    df = pd.DataFrame(rows, columns=["id", "ticker", "timestamp_utc", "source", "text"])
    cap = int(os.getenv("MAX_NEWS_PER_TICKER", "2500"))
    if len(df) > cap:
        df = df.sort_values("timestamp_utc").tail(cap).reset_index(drop=True)
    return df


def _finnhub_news(ticker: str, cfg: dict) -> pd.DataFrame:
    """Live Finnhub company-news pull (the events/news backbone).

    The free tier caps a single response at the most recent ~250 articles, so a
    one-shot call for a multi-month range only returns the last week or two. We
    PAGINATE in short date windows to recover real historical coverage.
    """
    import datetime as dt
    import time

    import requests

    key = os.environ["FINNHUB_API_KEY"]
    url = "https://finnhub.io/api/v1/company-news"
    start = dt.date.fromisoformat(str(cfg["data"]["start"]))
    end = dt.date.fromisoformat(str(cfg["data"]["end"]))
    step = dt.timedelta(days=int(os.getenv("FINNHUB_CHUNK_DAYS", "10")))

    sess = requests.Session()
    rows, seen = [], set()
    cur = start
    while cur <= end:
        chunk_to = min(cur + step, end)
        for attempt in range(4):
            r = sess.get(url, params={"symbol": ticker, "from": cur.isoformat(),
                                      "to": chunk_to.isoformat(), "token": key}, timeout=30)
            if r.status_code == 429:      # rate limited -> back off and retry
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            break
        else:
            cur = chunk_to + dt.timedelta(days=1)
            continue
        for item in r.json():
            headline = item.get("headline", "")
            key_dedupe = (headline, int(item.get("datetime", 0)) // 86400)
            if not headline or key_dedupe in seen:
                continue
            seen.add(key_dedupe)
            ts = pd.Timestamp(item["datetime"], unit="s", tz="UTC")
            text = f"{headline}. {item.get('summary', '')}".strip()
            rows.append({
                "id": f"finnhub:{item['id']}",
                "ticker": ticker,
                "timestamp_utc": ts.isoformat(),
                "source": "news:finnhub",
                "text": text[:1000],
            })
        cur = chunk_to + dt.timedelta(days=1)
        time.sleep(float(os.getenv("FINNHUB_SLEEP", "0.25")))  # stay under 60/min

    df = pd.DataFrame(rows, columns=["id", "ticker", "timestamp_utc", "source", "text"])
    # Cap FinBERT cost: keep the most recent MAX_NEWS_PER_TICKER unique articles.
    cap = int(os.getenv("MAX_NEWS_PER_TICKER", "2500"))
    if len(df) > cap:
        df = df.sort_values("timestamp_utc").tail(cap).reset_index(drop=True)
    return df


# --------------------------------------------------------------------------- #
# Persistence with provenance sidecar (immutable raw store)
# --------------------------------------------------------------------------- #
def save_raw(cfg: dict, kind: str, ticker: str, df: pd.DataFrame, meta: dict) -> Path:
    raw = utils.p(cfg, "raw")
    sub = raw / ("prices" if kind == "prices" else "text")
    sub.mkdir(parents=True, exist_ok=True)
    ext = "csv" if kind == "prices" else "jsonl"
    out = sub / f"{ticker}.{ext}"
    if kind == "prices":
        df.to_csv(out, index=False)
    else:
        df.to_json(out, orient="records", lines=True)
    meta = {**meta, "pulled_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "mode": cfg["data"]["mode"]}
    utils.write_json(out.with_suffix(out.suffix + ".meta.json"), meta)
    return out


def load_raw_prices(cfg: dict, ticker: str) -> pd.DataFrame:
    path = utils.p(cfg, "raw") / "prices" / f"{ticker}.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def load_raw_text(cfg: dict, ticker: str) -> pd.DataFrame:
    path = utils.p(cfg, "raw") / "text" / f"{ticker}.jsonl"
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=["id", "ticker", "timestamp_utc", "source", "text"])
    return pd.read_json(path, lines=True)
