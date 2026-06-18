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
    level=logging.DEBUG,
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