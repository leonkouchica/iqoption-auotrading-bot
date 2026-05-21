"""
═══════════════════════════════════════════════════════════════════════════
BUILDS UPON: Tutorial 1

NEW FEATURES ADDED:
  ✅ Daily Profit Target : Stops trading when you've made your goal for the day
  ✅ Daily Loss Limit : Cuts losses before they become catastrophic
  ✅ Max Daily Trades : Prevent overtrading
  ✅ Drawdown Protection : Stops trading if balance drops X% from peak
  ✅ Position Sizing : Calculates trade size based on account balance (% risk)
  ✅ Balance Tracking : Real-time P&L monitoring
  ✅ Consecutive Loss Protection : Cool-off after N losses
═══════════════════════════════════════════════════════════════════════════
"""


import time
import logging

class ShortNameFilter(logging.Filter):
    """Shortens long logger names to last component only"""
    
    def filter(self, record):
        if hasattr(record, 'name'):
            # Take only the last part after the last dot
            parts = record.name.split('.')
            record.name = parts[-1][:12]  # Max 12 chars
        return True

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)-12s %(levelname)-6s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()],
)

# Add filter to all handlers
for handler in logging.getLogger().handlers:
    handler.addFilter(ShortNameFilter())

# Your logger
logger = logging.getLogger("Iqtradingbot")
from dataclasses import dataclass
from datetime import datetime, date
from typing import Dict, Optional, Tuple
from tradingconfig import TradingConfig
from iqoptionapi.iqapi import IQOptionClient
from iqoptionapi.models import Direction, OptionsTradeParams, OptionType


# ═══════════════════════════════════════════════════════════════════════
#  RISK MANAGER CLASS (NEW in Tutorial 2)
# ═══════════════════════════════════════════════════════════════════════

class RiskManager:
    """
    Handles all risk management logic.
    Tracks daily stats, checks limits, calculates position sizes.
    """
    
    def __init__(self, config: TradingConfig):
        self.config = config
        
        # Daily statistics
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.daily_wins = 0
        self.daily_losses = 0
        
        # Balance tracking
        self.current_balance = 0.0
        self.peak_balance = 0.0
        self.starting_balance = 0.0
        
        # Consecutive tracking
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        
        # Cool-off tracking
        self.cooloff_until = 0  # Timestamp when cool-off ends
        
        # Today's date for rollover
        self.today = date.today()
    
    def _check_day_rollover(self):
        """Reset daily stats if it's a new day"""
        today = date.today()
        if today != self.today:
            logger.info("📅 New day detected - resetting daily statistics")
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.daily_wins = 0
            self.daily_losses = 0
            self.consecutive_losses = 0
            self.consecutive_wins = 0
            self.today = today
    
    def update_balance(self, new_balance: float):
        """Update current balance and track peak"""
        self.current_balance = new_balance
        if new_balance > self.peak_balance:
            self.peak_balance = new_balance
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed based on all risk rules.
        Returns: (can_trade, reason)
        """
        self._check_day_rollover()
        
        # Check cool-off period
        if time.time() < self.cooloff_until:
            remaining = int(self.cooloff_until - time.time())
            return False, f"Cool-off active: {remaining} seconds remaining"
        
        # Check daily profit target
        if self.daily_pnl >= self.config.daily_profit_target:
            return False, f"Daily profit target reached: ${self.daily_pnl:.2f} (target: ${self.config.daily_profit_target})"
        
        # Check daily loss limit
        if self.daily_pnl <= -self.config.daily_loss_limit:
            return False, f"Daily loss limit reached: ${self.daily_pnl:.2f} (limit: -${self.config.daily_loss_limit})"
        
        # Check max daily trades
        if self.daily_trades >= self.config.max_daily_trades:
            return False, f"Max daily trades reached: {self.daily_trades}/{self.config.max_daily_trades}"
        
        # Check consecutive losses
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            return False, f"Max consecutive losses reached: {self.consecutive_losses}"
        
        # Check drawdown
        if self.peak_balance > 0:
            drawdown = ((self.peak_balance - self.current_balance) / self.peak_balance) * 100
            if drawdown >= self.config.max_drawdown_percent:
                return False, f"Max drawdown reached: {drawdown:.1f}% (limit: {self.config.max_drawdown_percent}%)"
        
        # Check trading hours
        current_hour = datetime.now().hour
        if current_hour < self.config.trading_start_hour or current_hour > self.config.trading_end_hour:
            return False, f"Outside trading hours: {current_hour}:00 (trading hours: {self.config.trading_start_hour}:00-{self.config.trading_end_hour}:00)"
        
        return True, "Ready to trade"
    
    def calculate_position_size(self) -> float:
        """
        Calculate position size based on risk percentage.
        Uses current balance and caps at min/max.
        """
        # Calculate based on risk percentage
        position = (self.current_balance * self.config.risk_per_trade) / 100
        
        # Apply min/max limits
        position = max(position, self.config.min_trade_amount)
        position = min(position, self.config.max_trade_amount)
        
        # Round to 2 decimal places
        return round(position, 2)
    
    def record_trade(self, pnl: float):
        """
        Record trade outcome and update statistics.
        Called after each trade completes.
        """
        self.daily_trades += 1
        self.daily_pnl += pnl
        self.current_balance += pnl
        
        # Update win/loss counts
        if pnl > 0:
            self.daily_wins += 1
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl < 0:
            self.daily_losses += 1
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            
            # Check if we need to trigger cool-off
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                self.cooloff_until = time.time() + (self.config.cooloff_minutes * 60)
                logger.warning(f"⏸️  COOL-OFF TRIGGERED! {self.config.cooloff_minutes} minute pause after {self.consecutive_losses} losses")
        
        # Update peak balance
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
    
    def get_stats(self) -> Dict:
        """Get current risk statistics for display"""
        drawdown = 0
        if self.peak_balance > 0:
            drawdown = ((self.peak_balance - self.current_balance) / self.peak_balance) * 100
        
        win_rate = 0
        if self.daily_trades > 0:
            win_rate = (self.daily_wins / self.daily_trades) * 100
        
        return {
            'balance': self.current_balance,
            'peak_balance': self.peak_balance,
            'drawdown': drawdown,
            'daily_pnl': self.daily_pnl,
            'daily_trades': self.daily_trades,
            'daily_wins': self.daily_wins,
            'daily_losses': self.daily_losses,
            'win_rate': win_rate,
            'consecutive_losses': self.consecutive_losses,
            'consecutive_wins': self.consecutive_wins,
        }
    
    def print_status(self):
        """Print current risk status"""
        stats = self.get_stats()
        print("")
        logger.info(f"{'='*50}")
        logger.info(f"📊 RISK MANAGEMENT STATUS")
        logger.info(f"{'='*50}")
        logger.info(f"💰 Balance:        ${stats['balance']:.2f} (Peak: ${stats['peak_balance']:.2f})")
        logger.info(f"📉 Drawdown:       {stats['drawdown']:.1f}%")
        logger.info(f"📈 Daily P&L:      ${stats['daily_pnl']:+.2f}")
        logger.info(f"🎯 Win Rate:       {stats['win_rate']:.1f}% ({stats['daily_wins']}W/{stats['daily_losses']}L)")
        logger.info(f"📊 Trades Today:   {stats['daily_trades']}/{self.config.max_daily_trades}")
        logger.info(f"🔥 Consecutive:    {stats['consecutive_wins']}W / {stats['consecutive_losses']}L")
        
        if self.cooloff_until > time.time():
            remaining = int(self.cooloff_until - time.time())
            logger.info(f"⏸️  Cool-off:       {remaining} seconds remaining")
        logger.info(f"{'='*50}\n")


# ═══════════════════════════════════════════════════════════════════════
#  CANDLE COLOR STRATEGY (from Tutorial 1)
# ═══════════════════════════════════════════════════════════════════════

def get_signal_from_candle(client, asset: str) -> Direction:
    """Get trading signal from latest candle (same as Tutorial 1)"""
    try:
        candles = client.get_candles(asset_name=asset, count=1)
        
        if candles:
            candle = candles[-1]
            if candle['close'] > candle['open']:
                return Direction.CALL
            elif candle['close'] < candle['open']:
                return Direction.PUT
    except Exception as e:
        logger.error(f"Error getting signal: {e}")
    
    return Direction.INDECISION


def wait_for_minute_start(client):
    """Wait for the next minute to start (same as Tutorial 1)"""
    time.sleep(1)
    timestamp = client.message_handler.server_time
    dt = datetime.fromtimestamp(timestamp / 1000)
    seconds = dt.second
    
    if seconds > 5:  # Wait for next minute if we're past :05
        wait_time = 60 - seconds
        logger.info(f"⏰ Waiting {wait_time} seconds for next minute...")
        time.sleep(wait_time)
    
    return True


# ═══════════════════════════════════════════════════════════════════════
#  MAIN TRADING BOT WITH RISK MANAGEMENT (Tutorial 2)
# ═══════════════════════════════════════════════════════════════════════

class TradingBotWithRisk:
    """
    Trading bot that integrates risk management from Tutorial 2.
    Builds upon the simple bot from Tutorial 1.
    """
    
    def __init__(self, config:TradingConfig=None):
        # Initialize risk management (NEW in Tutorial 2)
        self.config = config or TradingConfig()
        self.risk_manager = RiskManager(self.config)
        
        # API client
        self.client = None
        
        # Statistics
        self.trades = []
    
    def connect(self) -> bool:
        """Connect to IQ Option"""
        logger.info("Connecting to IQOption...")
        
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
    
    def check_timing(self) -> bool:
        """Check if current second is allowed for trading"""
        current_second = datetime.now().second
        return current_second in [0,1,2,3]
    
    def execute_trade(self, direction: Direction) -> Optional[Tuple[bool, float]]:
        """Execute a trade with risk-managed position sizing"""
        
        # Calculate position size based on risk (NEW in Tutorial 2)
        position_size = self.risk_manager.calculate_position_size()
        balance_before = self.risk_manager.current_balance
        
        logger.info(f"Placing Trade: {self.config.asset}, {direction.value.upper()}, ${position_size}")
        
        # Prepare trade parameters
        trade_params = OptionsTradeParams(
            asset=self.config.asset,
            expiry=self.config.expiry_minutes,
            amount=position_size,
            direction=direction,
            option_type=self.config.option_type
        )
        
        # Execute trade
        success, order_id = self.client.execute_options_trade(trade_params)
        
        if not success or not order_id:
            logger.error(f"❌ Trade failed: {order_id}")
            return None
        
        logger.info(f"✅ Trade placed! Order ID: {order_id}")
        
        # Get result
        success, outcome_data, pnl = self.client.get_trade_outcome(order_id, self.config.expiry_minutes)
        
        if success and outcome_data is not None:
            balance_after = balance_before + pnl
            
            # Record trade in risk manager (NEW in Tutorial 2)
            self.risk_manager.record_trade(pnl)
            
            # Store trade record
            trade_record = {
                'id': order_id,
                'timestamp': datetime.now().isoformat(),
                'direction': direction.value,
                'amount': position_size,
                'pnl': pnl,
                'balance_after': balance_after
            }
            self.trades.append(trade_record)
            
            # Display result
            emoji = "🎉" if pnl > 0 else "💸" if pnl < 0 else "🤝"
            logger.info(f"{emoji} RESULT: {outcome_data.get('result', 'unknown').upper()} | P&L: ${pnl:+.2f}")
            
            return True, pnl
        
        logger.error(f"❌ Failed to get trade result")
        return None

    def run(self):
        """Main trading loop with risk management integration"""
        # Connect to IQ Option
        if not self.connect():
            logger.error("Failed to connect. Exiting...")
            return

        try:
            while True:
                # ── STEP 1: Check risk limits (NEW in Tutorial 2) ──
                can_trade, reason = self.risk_manager.can_trade()

                if not can_trade:
                    logger.warning(f"⛔ Trading blocked: {reason}")
                    
                    # If daily limits reached, exit
                    if "profit target" in reason or "loss limit" in reason or "max daily trades" in reason:
                        logger.info("🏁 Daily limits reached. Bot stopping...")
                        break
                    
                    time.sleep(30)
                    continue
                
                # ── STEP 3: Wait for minute start ──
                wait_for_minute_start(self.client)
                
                # ── STEP 4: Get signal ──
                signal = get_signal_from_candle(self.client, self.config.asset)
                
                if signal == Direction.INDECISION:
                    logger.info("📊 No clear signal, waiting...")
                    continue
                
                # ── STEP 5: Execute trade with risk management ──
                result = self.execute_trade(signal)
                
                # ── STEP 6: Display updated risk status ──
                self.risk_manager.print_status()
                
                # Small pause before next trade
                time.sleep(.5)
                
        except KeyboardInterrupt:
            print("\n\n🛑 Trading stopped by user")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            # Final summary
            self.print_final_summary()
            self.client.disconnect()
            logger.info("🔌 Disconnected")
    
    def print_final_summary(self):
        """Print final trading summary"""
        stats = self.risk_manager.get_stats()
        
        print("\n" + "="*60)
        print("📊 FINAL TRADING SUMMARY")
        print("="*60)
        print(f"💰 Starting Balance:  ${self.risk_manager.starting_balance:.2f}")
        print(f"💰 Final Balance:     ${stats['balance']:.2f}")
        print(f"📈 Total P&L:         ${stats['daily_pnl']:+.2f}")
        print(f"📊 Total Trades:      {stats['daily_trades']}")
        print(f"🎯 Win Rate:          {stats['win_rate']:.1f}%")
        print(f"🔥 Max Drawdown:      {stats['drawdown']:.1f}%")
        print("="*60)


# ═══════════════════════════════════════════════════════════════════════
#  RUN THE BOT
# ═══════════════════════════════════════════════════════════════════════

def main():
    """Entry point for Tutorial 2"""
    bot = TradingBotWithRisk()
    bot.config.display()
    bot.run()


if __name__ == "__main__":
    main()