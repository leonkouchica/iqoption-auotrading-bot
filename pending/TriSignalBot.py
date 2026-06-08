"""
IQ Option Automated Trading Bot
Uses RSI, Moving Average Crossover, and Bollinger Bands strategies.
"""

import csv
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
import pandas as pd
from iqoptionapi.stable_api import IQ_Option

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

     
# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class Config:
    # Credentials
    email: str = ""
    password: str = ""

    # Trade settings
    pair: str = "USDTHB-OTC"
    amount: float = 203
    expiration: int = 5          # minutes
    trade_interval: int = 60     # seconds between trades

    # Candle settings
    interval: int = 300          # 5-minute candles (seconds)
    count: int = 50              # historical candles to fetch

    # Risk management
    max_daily_loss: float = 5_000
    max_daily_trades: int = 100_000

    # Signal thresholds
    signal_threshold: int = 2
    atr_threshold: float = 0.002

    # CSV logging
    csv_file: Path = Path("mylog.csv")
    csv_columns: tuple = field(default_factory=lambda: (
        "Time", "Signal", "Pair", "Amount", "Action", "Result", "Balance"
    ))


# ── API helpers ───────────────────────────────────────────────────────────────

def connect(api: IQ_Option, retries: int = 3) -> None:
    """Connect to the IQ Option API, retrying on failure."""
    for attempt in range(1, retries + 1):
        log.info("Connecting to IQ Option (attempt %d/%d)…", attempt, retries)
        ok, reason = api.connect()
        if ok:
            log.info("Login successful.")
            return
        log.warning("Login failed: %s", reason)
        time.sleep(5)
    raise ConnectionError("Could not connect after multiple attempts.")


def fetch_candles(api: IQ_Option, cfg: Config) -> pd.DataFrame:
    """Fetch historical candlestick data and return a tidy DataFrame."""
    raw = api.get_candles(cfg.pair, cfg.interval, cfg.count, time.time())
    df = pd.DataFrame(raw)
    df["time"] = pd.to_datetime(df["from"], unit="s")
    df.set_index("time", inplace=True)
    return df.rename(columns={"close": "Close", "open": "Open",
                               "max": "High",  "min": "Low"})


# ── Indicators ────────────────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add RSI, MA crossover, Bollinger Bands, and ATR columns in-place."""
    close = df["Close"]

    # RSI (14)
    delta = close.diff()
    avg_gain = delta.clip(lower=0).rolling(14).mean()
    avg_loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["RSI"] = 100 - 100 / (1 + avg_gain / avg_loss)

    # Moving averages
    df["MA_Short"] = close.rolling(9).mean()
    df["MA_Long"]  = close.rolling(21).mean()

    # Bollinger Bands (20, ±2σ)
    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    df["BB_Middle"] = mid
    df["BB_Upper"]  = mid + 2 * std
    df["BB_Lower"]  = mid - 2 * std

    # ATR (14)
    prev_close = close.shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()

    return df


# ── Strategy ──────────────────────────────────────────────────────────────────

def generate_signal(df: pd.DataFrame, cfg: Config) -> str | None:
    """
    Score BUY/SELL pressure from three indicators.
    Returns 'call', 'put', or None when no clear signal.
    """
    add_indicators(df)
    r = df.iloc[-1]

    if r["ATR"] < cfg.atr_threshold:
        log.debug("ATR %.5f below threshold — skipping.", r["ATR"])
        return None

    scores = {"call": 0, "put": 0}

    # RSI
    if r["RSI"] < 30:
        scores["call"] += 1
    elif r["RSI"] > 70:
        scores["put"] += 1

    # MA crossover
    if r["MA_Short"] > r["MA_Long"]:
        scores["call"] += 1
    elif r["MA_Short"] < r["MA_Long"]:
        scores["put"] += 1

    # Bollinger Bands
    if r["Close"] < r["BB_Lower"]:
        scores["call"] += 1
    elif r["Close"] > r["BB_Upper"]:
        scores["put"] += 1

    gap = scores["call"] - scores["put"]
    if abs(gap) >= cfg.signal_threshold:
        return "call" if gap > 0 else "put"
    return None


# ── Order execution ───────────────────────────────────────────────────────────

def place_order(api: IQ_Option, cfg: Config, action: str) -> tuple[int | None, float | None]:
    """Place a binary option trade and return (order_id, balance)."""
    log.info("Placing %s order — %s @ %s", action.upper(), cfg.amount, cfg.pair)
    ok, order_id = api.buy(cfg.amount, cfg.pair, action, cfg.expiration)
    if ok:
        log.info("Order placed (id=%s).", order_id)
        return order_id, api.get_balance()
    log.error("Order failed.")
    return None, None


# ── CSV logging ───────────────────────────────────────────────────────────────

def init_csv(cfg: Config) -> None:
    """Create the log file with headers if it doesn't already exist."""
    if not cfg.csv_file.exists():
        with cfg.csv_file.open("w", newline="") as fh:
            csv.writer(fh).writerow(cfg.csv_columns)


def log_trade(cfg: Config, signal: str, action: str, result: str, balance: float) -> None:
    """Append one trade row to the CSV log."""
    row = [
        time.strftime("%Y-%m-%d %H:%M:%S"),
        signal, cfg.pair, cfg.amount,
        action.upper(), result, balance,
    ]
    with cfg.csv_file.open("a", newline="") as fh:
        csv.writer(fh).writerow(row)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(cfg: Config) -> None:
    """Main trading loop."""
    api = IQ_Option(cfg.email, cfg.password)
    connect(api)
    # api.change_balance("PRACTICE")  # Uncomment for paper trading
    init_csv(cfg)

    last_trade_time = 0.0
    cumulative_loss = 0.0
    trades_executed = 0

    while True:
        try:
            # ── Guard: daily limits ──────────────────────────────────────────
            if cumulative_loss >= cfg.max_daily_loss:
                log.warning("Daily loss limit reached (%.2f). Stopping.", cumulative_loss)
                break
            if trades_executed >= cfg.max_daily_trades:
                log.warning("Daily trade limit reached (%d). Stopping.", trades_executed)
                break

            # ── Signal ───────────────────────────────────────────────────────
            df = fetch_candles(api, cfg)
            signal = generate_signal(df, cfg)

            if signal:
                log.info("Signal: %s for %s", signal.upper(), cfg.pair)
            else:
                log.info("No valid signal.")

            # ── Execute trade ─────────────────────────────────────────────────
            now = time.time()
            if signal and (now - last_trade_time) >= cfg.trade_interval:
                order_id, balance = place_order(api, cfg, signal)

                if order_id is not None:
                    time.sleep(cfg.expiration * 60)   # wait for settlement
                    win = api.check_win_v3(order_id) >= 0
                    result = "TRADE WIN" if win else "TRADE LOSE"
                    log.info("Trade result: %s", result)

                    log_trade(cfg, signal, signal, result, balance)
                    trades_executed += 1

                    if not win:
                        cumulative_loss += cfg.amount

                last_trade_time = now

            time.sleep(10)

        except KeyboardInterrupt:
            log.info("Interrupted by user. Exiting.")
            break
        except Exception as exc:
            log.exception("Unexpected error: %s", exc)
            time.sleep(5)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run(Config())
