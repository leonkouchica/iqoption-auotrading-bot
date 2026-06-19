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
from bot.strategies.bar_by_bar import bar_by_bar_signal
from bot.helpers import wait_for_minute_start
from tutorial2 import RiskManager

logger = logging.getLogger("AutoTrading Bot")

# Module-level bot reference for the signal generator
_bot: 'TradingBot' = None



def generate_signal_from_live_candle(candle) -> Direction:
    """
    Multi-candle analysis for better signal quality.
    
    Analyzes the last 3 completed candles for:
    - Trend direction (consecutive candles going same way?)
    - Momentum (size of latest candle body vs average)
    - Rejection patterns (long wicks = potential reversal)
    
    NEW FILTERS:
    - Ranging-market detection (skip choppy/alternating candles)
    - Higher-timeframe trend confirmation (5-min must agree with 1-min)
    
    Returns Direction.CALL, Direction.PUT, or Direction.INDECISION.
    Also sets _bot._last_signal_strength to 'STRONG' or 'CONFIRMED'.
    """
    cm = _bot.candle_manager if _bot else None
    _bot._last_signal_strength = None
    
    if cm is None:
        if candle.close > candle.open: return Direction.CALL
        elif candle.close < candle.open: return Direction.PUT
        return Direction.INDECISION
    
    candles_1m = cm.get_candles(_bot.config.asset, 60, count=8)
    
    if len(candles_1m) < 5:
        logger.info(f"📊 Building history ({len(candles_1m)}/5 candles)")
        return Direction.CALL if candle.close > candle.open else Direction.PUT if candle.close < candle.open else Direction.INDECISION
    
    # ─── FILTER 1: Ranging-market detection ──────────────────────────
    # Check if the last 5 candles are alternating direction (choppy market)
    last5 = candles_1m[-5:]
    dirs_5 = [1 if c.close > c.open else -1 for c in last5]
    flips = sum(1 for i in range(1, len(dirs_5)) if dirs_5[i] != dirs_5[i-1])
    if flips >= 4:
        logger.info(f"⏭️  SKIP | Choppy market ({flips} flips in 5 candles)")
        return Direction.INDECISION
    
    # ─── FILTER 2: Higher-timeframe trend confirmation ───────────────
    # Get 5-minute candles to confirm the broader trend
    candles_5m = cm.get_candles(_bot.config.asset, 300, count=2)
    htf_trend = 0  # 0=neutral, 1=bullish, -1=bearish
    if len(candles_5m) >= 2:
        last_5m = candles_5m[-1]
        htf_trend = 1 if last_5m.close > last_5m.open else -1 if last_5m.close < last_5m.open else 0
    
    c1, c2, c3 = candles_1m[-3], candles_1m[-2], candles_1m[-1]
    
    def body(c):    return abs(c.close - c.open)
    def dir_sign(c): return 1 if c.close > c.open else -1 if c.close < c.open else 0
    def upper_w(c): return c.high - max(c.open, c.close)
    def lower_w(c): return min(c.open, c.close) - c.low
    
    d1, d2, d3 = dir_sign(c1), dir_sign(c2), dir_sign(c3)
    trend = d1 + d2 + d3
    avg_body = (body(c1) + body(c2) + body(c3)) / 3
    momentum = body(c3) / avg_body if avg_body > 0 else 1.0
    rejection_up = upper_w(c3) > body(c3) * 0.8 and d3 <= 0
    rejection_down = lower_w(c3) > body(c3) * 0.8 and d3 >= 0
    
    logger.info(f"📊 Trend={trend:+d} | Mom={momentum:.1f}x | Body={body(c3):.6f} | U-Wick={upper_w(c3):.6f} | L-Wick={lower_w(c3):.6f} | HTF={htf_trend:+d}")
    
    # ─── Strong trend + momentum + no rejection + HTF agrees ───
    if trend >= 2 and momentum >= 0.5 and not rejection_up:
        if htf_trend >= 0:  # 5-min is bullish or neutral
            logger.info("🟢 STRONG CALL")
            _bot._last_signal_strength = 'STRONG'
            return Direction.CALL
        else:
            logger.info(f"⏭️  SKIP | STRONG CALL rejected — HTF bearish ({htf_trend:+d})")
    if trend <= -2 and momentum >= 0.5 and not rejection_down:
        if htf_trend <= 0:  # 5-min is bearish or neutral
            logger.info("🔴 STRONG PUT")
            _bot._last_signal_strength = 'STRONG'
            return Direction.PUT
        else:
            logger.info(f"⏭️  SKIP | STRONG PUT rejected — HTF bullish ({htf_trend:+d})")
    
    # ─── Confirmed trend (all 3 same direction) ───
    if trend == 3 and momentum >= 0.3:
        if htf_trend >= 0:
            logger.info("🟢 CONFIRMED CALL (3 green)")
            _bot._last_signal_strength = 'CONFIRMED'
            return Direction.CALL
        else:
            logger.info(f"⏭️  SKIP | CONFIRMED CALL rejected — HTF bearish ({htf_trend:+d})")
    if trend == -3 and momentum >= 0.3:
        if htf_trend <= 0:
            logger.info("🔴 CONFIRMED PUT (3 red)")
            _bot._last_signal_strength = 'CONFIRMED'
            return Direction.PUT
        else:
            logger.info(f"⏭️  SKIP | CONFIRMED PUT rejected — HTF bullish ({htf_trend:+d})")
    
    # ─── Rejection alert ───
    if rejection_up:
        logger.info("⚠️  Rejection (long upper wick) — skipping")
    if rejection_down:
        logger.info("⚠️  Rejection (long lower wick) — skipping")
    
    logger.info(f"⏭️  SKIP | Weak signal (trend={trend:+d}, mom={momentum:.1f}x)")
    return Direction.INDECISION



class TradingBot:
    def __init__(self):
        global _bot
        _bot = self
        self.config          = TradingConfig()
        self.analytics_config = AnalyticsConfig()
        self.risk_manager    = RiskManager(self.config)
        self.analyzer        = TradeAnalyzer(self.analytics_config)
        self.client          = None
        self.candle_manager   = None
        self._stop_flag      = False
        
        # ─── Guard against duplicate trades ───
        self._last_trade_candle_id = None     # Track last candle we traded on
        self._last_trade_time = 0             # Timestamp of last trade
        self._trading_active = False          # Lock: only 1 trade at a time
        self._last_signal_strength = None     # 'STRONG' or 'CONFIRMED' for position sizing
        
        # ─── Ensure clean shutdown on ANY exit ───
        atexit.register(self._force_shutdown)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C and termination signals."""
        logger.info(f"🛑 Received signal {signum}, shutting down...")
        self._stop_flag = True
        self._force_shutdown()
        sys.exit(0)
    
    def _force_shutdown(self):
        """Force cleanup — kill WebSocket, disconnect, ensure process dies."""
        try:
            if self.client and self.client._connected:
                # Unsubscribe all candles first
                if hasattr(self.client, 'candle_manager'):
                    self.client.candle_manager.unsubscribe_all()
                self.client.disconnect()
        except Exception:
            pass
        finally:
            # Force-kill the websocket thread
            if self.client and hasattr(self.client, 'websocket'):
                try:
                    self.client.websocket.close()
                except Exception:
                    pass
        self._last_trade_time = 0             # Timestamp of last trade
        self._trading_active = False          # Lock: only 1 trade at a time

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

    # Add this method to TradingBot class
    def subscribe_to_live_candles(self) -> bool:
        """Subscribe to real-time candle updates"""
        logger.info(f"📡 Subscribing to live candles for {self.config.asset}...")
        
        # Use 60s candles for multi-candle analysis
        success = self.client.start_candle_stream(
            asset=self.config.asset,
            candle_size=60  # 1-minute candles for analysis
        )
        
        if success:
            # Store candle_manager reference for the signal generator
            self.candle_manager = self.client.candle_manager
            # Register callback for new candles
            self.client.on_new_candle(self.on_new_candle_signal)
            logger.info("✅ Live candle subscription active")
        return success

    def on_new_candle_signal(self, candle):
        """
        Callback when a new candle closes.
        This is where you generate signals from LIVE data.
        """
        # ─── GUARD: Only 1 trade at a time — skip if already trading ───
        if self._trading_active:
            logger.info("⏭️  Skipping signal — trade already in progress")
            return
        
        # ─── GUARD: Prevent multiple trades on the same candle ───
        candle_id = getattr(candle, 'id', getattr(candle, 'timestamp', None))
        if candle_id is not None and candle_id == self._last_trade_candle_id:
            logger.info(f"⏭️  Skipping duplicate signal for candle {candle_id}")
            return
        
        # ─── GUARD: Prevent trading too fast (max 1 trade per 55s) ───
        now = time.time()
        if now - self._last_trade_time < 55:
            logger.info(f"⏭️  Skipping signal — too soon ({now - self._last_trade_time:.0f}s)")
            return
        
        # Store the candle for your strategy
        self.latest_candle = candle
        
        # Your signal logic here
        signal = generate_signal_from_live_candle(candle)
        
        if signal != Direction.INDECISION:
            logger.info(f"🎯 Signal generated from live candle: {signal.value}")
            self._trading_active = True
            self._last_trade_candle_id = candle_id
            self._last_trade_time = time.time()
            try:
                self.execute_trade(signal)
            finally:
                self._trading_active = False
            self._last_trade_time = time.time()

    def execute_trade(self, direction: Direction) -> Optional[Dict]:
        position_size  = self.risk_manager.calculate_position_size()
        
        # Scale position by signal strength: CONFIRMED = 60% of full size
        if self._last_signal_strength == 'CONFIRMED':
            scaled = round(position_size * 0.6, 2)
            scaled = max(scaled, self.config.min_trade_amount)  # respect min
            logger.info(f"💰 Scaled position: ${position_size} → ${scaled} (CONFIRMED signal)")
            position_size = scaled
        
        balance_before = self.risk_manager.current_balance

        # Place the trade — don't block waiting for confirmation
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
            # Order confirmation timed out but trade was likely placed
            # Check balance change directly
            logger.warning(f"⚠️  Confirmation timeout, but trade likely placed. Waiting for outcome...")
        
        # Wait for trade expiry + buffer
        wait_seconds = self.config.expiry_minutes * 60 + 5
        logger.info(f"⏳ Waiting {wait_seconds}s for trade outcome...")
        time.sleep(wait_seconds)
        
        # Get latest balance from cached state (avoids WebSocket deadlock)
        try:
            new_balance = self.client.appstate.balance
            if new_balance is None:
                new_balance = balance_before
        except Exception:
            new_balance = balance_before
        
        pnl = round(new_balance - balance_before, 2)
        
        if new_balance != balance_before:
            self.risk_manager.record_trade(pnl)
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
            self.risk_manager.update_balance(new_balance)
            logger.info(f"📊 Trade Result: ${pnl:+.2f} | New Balance: ${new_balance:.2f}")
            return trade_data
        return None

    def run(self):
        if not self.connect():
            logger.error("Failed to connect. Exiting...")
            return

        logger.info("✅ Connected successfully!")
        logger.info(f"   📊 Account : {self.client.appstate.balance_type_str.capitalize()}")
        logger.info(f"   💵 Balance : ${self.risk_manager.starting_balance:.2f}")
        logger.info(f"   📁 Output  : {self.analytics_config.output_dir}/")
        self.config.display()

        # NEW: Subscribe to live candles
        if not self.subscribe_to_live_candles():
            logger.error("Failed to subscribe to live candles. Exiting...")
            return
        
        logger.info("🤖 Bot running with LIVE candles | Press Ctrl+C to stop")
        logger.info("=" * 60)

        try:
            while True:
                can_trade, reason = self.risk_manager.can_trade()
                if not can_trade:
                    logger.warning(f"⛔ Trading blocked: {reason}")
                    self.risk_manager.print_status()
                    if "profit target" in reason or "loss limit" in reason:
                        logger.info("🏁 Daily limits reached. Generating final report...")
                        break
                    time.sleep(30)
                    continue

                # wait_for_minute_start(self.client)
                # signal = bar_by_bar_signal(self.client, self.config.asset)

                # if signal == Direction.INDECISION:
                #     time.sleep(55)
                #     continue

                # self.execute_trade(signal)
                # self.risk_manager.print_status()
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