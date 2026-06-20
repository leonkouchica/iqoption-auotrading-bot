import time
import sys
import atexit
import signal
import logging
from datetime import datetime
from typing import Dict, Optional

from iqoptionapi.iqapi import IQOptionClient
from iqoptionapi.models import Direction, OptionsTradeParams

from tradingconfig import TradingConfig, AnalyticsConfig
from bot.analytics.analyzer import TradeAnalyzer
from bot.risk.manager import RiskManager
from bot.helpers import wait_for_minute_start

logger = logging.getLogger("AutoTrading Bot")

# Module-level bot reference for the signal generator
_bot: 'TradingBot' = None


# ═══════════════════════════════════════════════════════════════════════════
#  CANDLESTICK PATTERN HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _body(c) -> float:
    return abs(c.close - c.open)

def _range(c) -> float:
    return c.high - c.low

def _dir(c) -> int:
    """Returns +1 (bullish), -1 (bearish), or 0 (doji)."""
    if c.close > c.open: return  1
    if c.close < c.open: return -1
    return 0

def _upper_wick(c) -> float:
    return c.high - max(c.open, c.close)

def _lower_wick(c) -> float:
    return min(c.open, c.close) - c.low

def _is_inside_bar(current, previous) -> bool:
    """
    Inside bar: current candle is completely contained within previous candle.
    Indicates price contraction / indecision before a breakout.
    """
    return current.high < previous.high and current.low > previous.low

def _is_engulfing(current, previous) -> Optional[Direction]:
    """
    Engulfing candle: current body fully covers previous candle's body.
    - Bullish engulfing: current is green, previous was red, body engulfs previous body.
    - Bearish engulfing: current is red, previous was green, body engulfs previous body.
    Returns Direction.CALL, Direction.PUT, or None.
    """
    curr_body_high = max(current.open, current.close)
    curr_body_low  = min(current.open, current.close)
    prev_body_high = max(previous.open, previous.close)
    prev_body_low  = min(previous.open, previous.close)

    if (_dir(current) == 1 and _dir(previous) == -1
            and curr_body_high >= prev_body_high
            and curr_body_low  <= prev_body_low):
        return Direction.CALL

    if (_dir(current) == -1 and _dir(previous) == 1
            and curr_body_high >= prev_body_high
            and curr_body_low  <= prev_body_low):
        return Direction.PUT

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  SIGNAL ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def generate_signal_from_live_candle(candle) -> Direction:
    """
    Multi-layer signal engine.

    Analysis layers (in order):
    1.  Choppy-market filter  — skip alternating candles
    2.  HTF trend bias        — 5-min trend must agree (uses 3 candles, not 1)
    3.  Inside bar filter     — skip price-contraction candles
    4.  Minimum body filter   — skip doji / near-doji candles
    5.  Engulfing pattern     — highest-confidence continuation or reversal
    6.  Exhaustion reversal   — counter-trade after a strong 4+ candle run
    7.  Trend-following       — CONFIRMED (3/3) or STRONG (2/3) momentum signals

    Sets _bot._last_signal_scale:
        1.0 = CONFIRMED / Engulfing  (full position)
        0.8 = STRONG                 (80% position)
        0.6 = Reversal               (60% position)

    Returns Direction.CALL, Direction.PUT, or Direction.INDECISION.
    """
    cm  = _bot.candle_manager if _bot else None
    _bot._last_signal_scale = 1.0  # default

    # ── Fallback when candle manager not ready ───────────────────────────
    if cm is None:
        if candle.close > candle.open: return Direction.CALL
        if candle.close < candle.open: return Direction.PUT
        return Direction.INDECISION

    candles_1m = cm.get_candles(_bot.config.asset, 60, count=8)

    if len(candles_1m) < 5:
        logger.info(f"📊 Building history ({len(candles_1m)}/5 candles)")
        return Direction.CALL if candle.close > candle.open else \
               Direction.PUT  if candle.close < candle.open else \
               Direction.INDECISION

    # ── FILTER 1: Choppy-market detection ───────────────────────────────
    last5   = candles_1m[-5:]
    dirs_5  = [_dir(c) for c in last5]
    flips   = sum(1 for i in range(1, len(dirs_5)) if dirs_5[i] != dirs_5[i-1])
    if flips >= 4:
        logger.info(f"⏭️  SKIP | Choppy market ({flips} flips in 5 candles)")
        return Direction.INDECISION

    # ── FILTER 2: HTF trend bias (3 five-minute candles) ─────────────────
    candles_5m = cm.get_candles(_bot.config.asset, 300, count=4)
    htf_trend  = 0  # 0=neutral, +1=bullish, -1=bearish
    if len(candles_5m) >= 3:
        htf_dirs  = [_dir(c) for c in candles_5m[-3:]]
        htf_trend = sum(htf_dirs)           # range: -3 to +3
        # Require at least 2/3 five-min candles to agree for a directional bias
        if abs(htf_trend) < 2:
            htf_trend = 0                   # treat as neutral

    # Working candles
    c1, c2, c3 = candles_1m[-3], candles_1m[-2], candles_1m[-1]
    avg_body   = ((_body(c1) + _body(c2) + _body(c3)) / 3) or 1e-10

    logger.info(
        f"📊 HTF={htf_trend:+d} | "
        f"d1={_dir(c1):+d} d2={_dir(c2):+d} d3={_dir(c3):+d} | "
        f"Body={_body(c3):.6f} | Range={_range(c3):.6f} | "
        f"U-Wick={_upper_wick(c3):.6f} | L-Wick={_lower_wick(c3):.6f}"
    )

    # ── FILTER 3: Inside bar — skip (price contraction / no edge) ────────
    if _is_inside_bar(c3, c2):
        logger.info("⏭️  SKIP | Inside bar — price contracting, wait for breakout")
        return Direction.INDECISION

    # ── FILTER 4: Minimum body size — skip doji / near-doji ──────────────
    candle_range = _range(c3)
    if candle_range > 0 and (_body(c3) / candle_range) < 0.30:
        logger.info(
            f"⏭️  SKIP | Doji / indecision candle "
            f"(body={_body(c3)/candle_range:.0%} of range)"
        )
        return Direction.INDECISION

    # ── PATTERN: Engulfing candle ────────────────────────────────────────
    engulf = _is_engulfing(c3, c2)
    if engulf is not None:
        direction_name = "CALL" if engulf == Direction.CALL else "PUT"
        # Check HTF agreement (neutral counts as OK for engulfing)
        htf_ok = (
            (engulf == Direction.CALL and htf_trend >= 0) or
            (engulf == Direction.PUT  and htf_trend <= 0)
        )
        if htf_ok:
            logger.info(f"🕯️  ENGULFING {direction_name} — full position")
            _bot._last_signal_scale = 1.0
            return engulf
        else:
            logger.info(f"⏭️  SKIP | Engulfing {direction_name} rejected — HTF disagrees ({htf_trend:+d})")

    # ── PATTERN: Exhaustion reversal ─────────────────────────────────────
    # After 4+ same-direction candles, a momentum spike often signals a blowoff top/bottom.
    # We fade (trade against) the exhausted move.
    last4_dirs = [_dir(c) for c in candles_1m[-4:]]
    if all(d == 1 for d in last4_dirs):
        momentum = _body(c3) / avg_body
        if momentum >= 2.0:                 # last candle body ≥ 2× avg = blowoff
            if htf_trend <= 0:              # HTF must not be strongly bullish
                logger.info(f"🔄 EXHAUSTION PUT (4 green + blowoff {momentum:.1f}x) — 60% position")
                _bot._last_signal_scale = 0.6
                return Direction.PUT
    if all(d == -1 for d in last4_dirs):
        momentum = _body(c3) / avg_body
        if momentum >= 2.0:
            if htf_trend >= 0:              # HTF must not be strongly bearish
                logger.info(f"🔄 EXHAUSTION CALL (4 red + blowoff {momentum:.1f}x) — 60% position")
                _bot._last_signal_scale = 0.6
                return Direction.CALL

    # ── SIGNAL: Trend-following ──────────────────────────────────────────
    d1, d2, d3 = _dir(c1), _dir(c2), _dir(c3)
    trend      = d1 + d2 + d3
    momentum   = _body(c3) / avg_body

    rejection_up   = _upper_wick(c3) > _body(c3) * 0.8 and d3 <= 0
    rejection_down = _lower_wick(c3) > _body(c3) * 0.8 and d3 >= 0

    # CONFIRMED: all 3 candles same direction (highest confidence → 100%)
    if trend == 3 and momentum >= 0.3 and not rejection_up:
        if htf_trend >= 0:
            logger.info("🟢 CONFIRMED CALL (3 green) — full position")
            _bot._last_signal_scale = 1.0
            return Direction.CALL
        else:
            logger.info(f"⏭️  SKIP | CONFIRMED CALL — HTF bearish ({htf_trend:+d})")

    if trend == -3 and momentum >= 0.3 and not rejection_down:
        if htf_trend <= 0:
            logger.info("🔴 CONFIRMED PUT (3 red) — full position")
            _bot._last_signal_scale = 1.0
            return Direction.PUT
        else:
            logger.info(f"⏭️  SKIP | CONFIRMED PUT — HTF bullish ({htf_trend:+d})")

    # STRONG: 2 of 3 candles agree with momentum (80% position)
    if trend >= 2 and momentum >= 0.5 and not rejection_up:
        if htf_trend >= 0:
            logger.info("🟢 STRONG CALL — 80% position")
            _bot._last_signal_scale = 0.8
            return Direction.CALL
        else:
            logger.info(f"⏭️  SKIP | STRONG CALL — HTF bearish ({htf_trend:+d})")

    if trend <= -2 and momentum >= 0.5 and not rejection_down:
        if htf_trend <= 0:
            logger.info("🔴 STRONG PUT — 80% position")
            _bot._last_signal_scale = 0.8
            return Direction.PUT
        else:
            logger.info(f"⏭️  SKIP | STRONG PUT — HTF bullish ({htf_trend:+d})")

    # Rejection log
    if rejection_up:
        logger.info("⚠️  Rejection (long upper wick) — skipping")
    if rejection_down:
        logger.info("⚠️  Rejection (long lower wick) — skipping")

    logger.info(f"⏭️  SKIP | No qualifying signal (trend={trend:+d}, mom={momentum:.1f}x)")
    return Direction.INDECISION


# ═══════════════════════════════════════════════════════════════════════════
#  TRADING BOT
# ═══════════════════════════════════════════════════════════════════════════

class TradingBot:
    def __init__(self):
        global _bot
        _bot = self
        self.config           = TradingConfig()
        self.analytics_config = AnalyticsConfig()
        self.risk_manager     = RiskManager(self.config)
        self.analyzer         = TradeAnalyzer(self.analytics_config)
        self.client           = None
        self.candle_manager   = None
        self._stop_flag       = False

        # ── Guard against duplicate / too-fast trades ───────────────────
        self._last_trade_candle_id = None
        self._last_trade_time      = 0
        self._trading_active       = False

        # ── Signal metadata ─────────────────────────────────────────────
        self._last_signal_scale    = 1.0   # position scale set by signal engine

        # ── Failure tracking ────────────────────────────────────────────
        self._consecutive_failures = 0

        # ── Clean shutdown on ANY exit ───────────────────────────────────
        atexit.register(self._force_shutdown)
        signal.signal(signal.SIGINT,  self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # ─────────────────────────────────────────────────────────────────────
    #  Lifecycle
    # ─────────────────────────────────────────────────────────────────────

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C and termination signals."""
        logger.info(f"🛑 Received signal {signum}, shutting down...")
        self._stop_flag = True
        self._force_shutdown()
        sys.exit(0)

    def _force_shutdown(self):
        """Force cleanup — kill WebSocket, disconnect."""
        try:
            if self.client and self.client._connected:
                if hasattr(self.client, 'candle_manager'):
                    self.client.candle_manager.unsubscribe_all()
                self.client.disconnect()
        except Exception:
            pass
        finally:
            if self.client and hasattr(self.client, 'websocket'):
                try:
                    self.client.websocket.close()
                except Exception:
                    pass
        self._trading_active = False

    def connect(self) -> bool:
        logger.info("🔌 Connecting to IQOption...")
        try:
            self.client = IQOptionClient()
            self.client.connect()
            if self.client._connected:
                balance = self.client.get_balance()
                self.risk_manager.update_balance(balance)
                self.risk_manager.starting_balance = balance
                return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
        return False

    def subscribe_to_live_candles(self) -> bool:
        """Subscribe to real-time 1-minute candle updates."""
        logger.info(f"📡 Subscribing to live candles for {self.config.asset}...")

        success = self.client.start_candle_stream(
            asset=self.config.asset,
            candle_size=60
        )

        if success:
            self.candle_manager    = self.client.candle_manager
            self._last_trade_time  = time.time()   # prevent burst on catchup
            self.client.on_new_candle(self.on_new_candle_signal)
            logger.info("✅ Live candle subscription active")
        return success

    # ─────────────────────────────────────────────────────────────────────
    #  Signal callback
    # ─────────────────────────────────────────────────────────────────────

    def on_new_candle_signal(self, candle):
        """Callback fired when a new 1-minute candle closes."""

        # ── GUARD: only 1 trade at a time ───────────────────────────────
        if self._trading_active:
            logger.info("⏭️  Skipping signal — trade already in progress")
            return

        # ── GUARD: no duplicate candle ───────────────────────────────────
        candle_id = getattr(candle, 'id', getattr(candle, 'timestamp', None))
        if candle_id is not None and candle_id == self._last_trade_candle_id:
            logger.info(f"⏭️  Skipping duplicate signal for candle {candle_id}")
            return

        # ── GUARD: minimum gap between trades (55s) ──────────────────────
        now = time.time()
        if now - self._last_trade_time < 55:
            logger.info(f"⏭️  Too soon ({now - self._last_trade_time:.0f}s since last trade)")
            return

        self.latest_candle = candle
        signal = generate_signal_from_live_candle(candle)

        if signal != Direction.INDECISION:
            logger.info(f"🎯 Signal: {signal.value} | Scale: {self._last_signal_scale:.0%}")
            self._trading_active       = True
            self._last_trade_candle_id = candle_id
            self._last_trade_time      = time.time()
            try:
                result = self.execute_trade(signal)
                if result is None:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= 5:
                        logger.error("❌ 5 consecutive failures — market likely closed. Stopping.")
                        self._stop_flag = True
                    elif self._consecutive_failures >= 2:
                        backoff = 120
                        logger.warning(f"⚠️  Trade failed ({self._consecutive_failures}x) — backing off {backoff}s")
                        self._last_trade_time = time.time() + backoff - 55
                    else:
                        logger.warning("⚠️  Trade did not complete — retrying in 55s")
                else:
                    self._consecutive_failures = 0
            finally:
                self._trading_active = False

    # ─────────────────────────────────────────────────────────────────────
    #  Trade execution
    # ─────────────────────────────────────────────────────────────────────

    def execute_trade(self, direction: Direction) -> Optional[Dict]:
        # ── Position size scaled by signal confidence ────────────────────
        position_size = self.risk_manager.calculate_position_size(
            scale=self._last_signal_scale
        )
        logger.info(
            f"💰 Position: ${position_size} "
            f"(scale={self._last_signal_scale:.0%})"
        )

        balance_before = self.risk_manager.current_balance

        # ── Place the trade ──────────────────────────────────────────────
        result = self.client.execute_options_trade(OptionsTradeParams(
            asset=self.config.asset,
            expiry=self.config.expiry_minutes,
            amount=position_size,
            direction=direction,
            option_type=self.config.option_type,
        ))

        if result is None:
            logger.error("❌ Trade failed: no response from API")
            return None

        success, order_id = result

        if not success or not order_id:
            logger.warning("⚠️  Confirmation timeout — trade likely placed. Waiting for outcome...")

        # ── Wait for expiry ──────────────────────────────────────────────
        wait_seconds = self.config.expiry_minutes * 60 + 5
        logger.info(f"⏳ Waiting {wait_seconds}s for trade outcome...")
        time.sleep(wait_seconds)

        # ── Poll balance up to 3 times (handles WebSocket lag) ──────────
        new_balance = None
        for attempt in range(3):
            try:
                cached = self.client.appstate.balance
                if cached is not None and cached != balance_before:
                    new_balance = cached
                    break
                elif cached is not None and attempt == 2:
                    # Third attempt — accept unchanged balance as legitimate draw
                    new_balance = cached
            except Exception:
                pass
            if attempt < 2:
                logger.info(f"⏳ Balance unchanged — retrying ({attempt + 2}/3)...")
                time.sleep(2)

        if new_balance is None:
            logger.warning("⚠️  Could not read balance after 3 attempts — trade not recorded")
            return None

        pnl = round(new_balance - balance_before, 2)

        # ── Record outcome ───────────────────────────────────────────────
        self.risk_manager.record_trade(pnl)
        self.risk_manager.update_balance(new_balance)   # sync to API value

        trade_data = {
            'trade_id':       order_id or 'unknown',
            'timestamp':      datetime.now().isoformat(),
            'asset':          self.config.asset,
            'direction':      direction.value,
            'amount':         position_size,
            'expiry_minutes': self.config.expiry_minutes,
            'pnl':            pnl,
            'balance_before': balance_before,
            'balance_after':  new_balance,
            'outcome':        'win' if pnl > 0 else 'loss' if pnl < 0 else 'draw',
        }
        self.analyzer.add_trade(trade_data)
        logger.info(f"📊 Trade Result: ${pnl:+.2f} | New Balance: ${new_balance:.2f}")
        return trade_data

    # ─────────────────────────────────────────────────────────────────────
    #  Main loop
    # ─────────────────────────────────────────────────────────────────────

    def run(self):
        if not self.connect():
            logger.error("Failed to connect. Exiting...")
            return

        logger.info("✅ Connected successfully!")
        logger.info(f"   📊 Account : {self.client.appstate.balance_type_str.capitalize()}")
        logger.info(f"   💵 Balance : ${self.risk_manager.starting_balance:.2f}")
        logger.info(f"   📁 Output  : {self.analytics_config.output_dir}/")
        self.config.display()

        if not self.subscribe_to_live_candles():
            logger.error("Failed to subscribe to live candles. Exiting...")
            return

        logger.info("🤖 Bot running with LIVE candles | Press Ctrl+C to stop")
        logger.info("=" * 60)

        try:
            while not self._stop_flag:
                can_trade, reason = self.risk_manager.can_trade()
                if not can_trade:
                    logger.warning(f"⛔ Trading blocked: {reason}")
                    self.risk_manager.print_status()
                    if "profit target" in reason or "loss limit" in reason:
                        logger.info("🏁 Daily limits reached. Generating final report...")
                        break
                    time.sleep(30)
                    continue
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n\n🛑 Trading stopped by user")
            self._force_shutdown()
            sys.exit(0)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            self._force_shutdown()
        finally:
            self._generate_report()
            self._force_shutdown()
            logger.info("🔌 Disconnected")
            sys.exit(0)

    def _generate_report(self):
        print("\n" + "=" * 60)
        print("📊 GENERATING PERFORMANCE REPORT")
        print("=" * 60)
        self.analyzer.to_dataframe()
        metrics = self.analyzer.calculate_metrics()
        self.analyzer.print_performance_report(metrics)
        if self.analytics_config.save_csv:
            self.analyzer.save_csv()
        self.analyzer.save_master_stats(metrics)
        if self.analytics_config.generate_charts:
            self.analyzer.generate_charts()
        print("\n✅ Report generation complete!")
        print(f"📁 Output folder: '{self.analytics_config.output_dir}/'")
        print("=" * 60)


if __name__ == "__main__":
    TradingBot().run()