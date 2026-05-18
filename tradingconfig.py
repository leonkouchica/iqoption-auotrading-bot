import logging
from typing import Dict, Tuple
from dataclasses import dataclass
from iqoption_api.models import OptionType

logger = logging.getLogger(__name__)


@dataclass
class TradingConfig:
    """
    Configuration class for trading bot with all settings.
    Includes trading parameters, timing, and comprehensive risk management.
    """
    
    # ═══════════════════════════════════════════════════════════════════════
    #  TRADING SETTINGS
    # ═══════════════════════════════════════════════════════════════════════
    asset: str = "EURUSD-op"                    # Trading asset
    expiry_minutes: int = 1                      # Trade expiry (1, 2, 5, 10, 15 minutes)
    option_type: str = OptionType.BINARY_OPTION  # 'binary' or 'digital'
    
    # ═══════════════════════════════════════════════════════════════════════
    #  TIMING SETTINGS
    # ═══════════════════════════════════════════════════════════════════════
    duration_minutes: int = 3000                 # How long to run (0 = unlimited)
    trade_seconds: Tuple[int, ...] = (0, 1, 2)   # Seconds of minute to trade
    
    # ═══════════════════════════════════════════════════════════════════════
    #  RISK MANAGEMENT - DAILY LIMITS
    # ═══════════════════════════════════════════════════════════════════════
    daily_profit_target: float = 150.0           # Stop when profit reaches this amount
    daily_loss_limit: float = 100.0              # Stop when loss reaches this amount
    max_daily_trades: int = 20                   # Maximum trades per day, 0=disabled
    
    # ═══════════════════════════════════════════════════════════════════════
    #  RISK MANAGEMENT - POSITION SIZING
    # ═══════════════════════════════════════════════════════════════════════
    risk_per_trade: float = 0.2                  # % of balance to risk per trade
    min_trade_amount: float = 5.0                # Minimum trade size
    max_trade_amount: float = 100.0              # Maximum trade size
    
    # ═══════════════════════════════════════════════════════════════════════
    #  RISK MANAGEMENT - PROTECTION FEATURES
    # ═══════════════════════════════════════════════════════════════════════
    max_consecutive_losses: int = 3              # Pause after N losses
    cooloff_minutes: int = 5                     # How long to pause after losses
    max_drawdown_percent: float = 10.0           # Stop if balance drops X% from peak
    
    # ═══════════════════════════════════════════════════════════════════════
    #  RISK MANAGEMENT - TRADING HOURS
    # ═══════════════════════════════════════════════════════════════════════
    trading_start_hour: int = 0                  # 24-hour format (0-23)
    trading_end_hour: int = 23                   # 24-hour format (0-23)
    
    def __post_init__(self):
        """Validate all configuration settings"""
        
        # ── Trading Settings Validation ────────────────────────────────────
        if not self.asset:
            raise ValueError("Asset cannot be empty")
        
        if self.min_trade_amount < 1:
            raise ValueError(f"Trade amount must be at least $1, got ${self.min_trade_amount}")
        
        valid_expiries = [1, 2, 5, 10, 15]
        if self.expiry_minutes not in valid_expiries:
            logger.warning(f"Expiry {self.expiry_minutes} min may not be available. "
                          f"Valid: {valid_expiries}")
        
        # ── Risk Management Validation ─────────────────────────────────────
        if self.risk_per_trade <= 0 or self.risk_per_trade > 10:
            logger.warning(f"Risk per trade {self.risk_per_trade}% - recommended: 1-5%")
        
        if self.daily_loss_limit <= 0:
            raise ValueError(f"Daily loss limit must be positive, got ${self.daily_loss_limit}")
        
        if self.daily_profit_target <= 0:
            raise ValueError(f"Daily profit target must be positive, got ${self.daily_profit_target}")
        
        if self.max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses must be at least 1")
        
        if self.min_trade_amount > self.max_trade_amount:
            raise ValueError(f"min_trade_amount (${self.min_trade_amount}) cannot exceed "
                           f"max_trade_amount (${self.max_trade_amount})")
        
        if self.trading_start_hour < 0 or self.trading_start_hour > 23:
            raise ValueError(f"trading_start_hour must be between 0-23, got {self.trading_start_hour}")
        
        if self.trading_end_hour < 0 or self.trading_end_hour > 23:
            raise ValueError(f"trading_end_hour must be between 0-23, got {self.trading_end_hour}")
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TradingConfig':
        """Create configuration from dictionary"""
        return cls(**data)
    
    def display(self):
        """Pretty print configuration"""
        logger.info("="*50)
        logger.info("📊 TRADING CONFIGURATION")
        logger.info("="*50)
        
        logger.info("📈 TRADING SETTINGS:")
        logger.info(f"  Asset:           {self.asset}")
        logger.info(f"  Expiry:          {self.expiry_minutes} minute(s)")
        logger.info(f"  Option Type:     {self.option_type.value.capitalize()}")
        logger.info(f"  Trade Seconds:   {self.trade_seconds}")
        logger.info(f"  Duration:        {self.duration_minutes} minutes")
        
        logger.info("-"*40)
        logger.info("🛡️ RISK MANAGEMENT:")
        logger.info(f"  Risk/Trade:      {self.risk_per_trade}% (${self.min_trade_amount} - ${self.max_trade_amount})")
        logger.info(f"  Daily Profit Target: ${self.daily_profit_target}")
        logger.info(f"  Daily Loss Limit:    ${self.daily_loss_limit}")
        logger.info(f"  Max Daily Trades:    {self.max_daily_trades}")
        logger.info(f"  Max Consecutive Losses: {self.max_consecutive_losses}")
        logger.info(f"  Cool-off Period:     {self.cooloff_minutes} minutes")
        logger.info(f"  Max Drawdown:        {self.max_drawdown_percent}%")
        logger.info(f"  Trading Hours:       {self.trading_start_hour}:00 - {self.trading_end_hour}:00")
        
        logger.info("="*50)
        print("")