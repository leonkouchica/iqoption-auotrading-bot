import sys
import time
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from iqoptionapi.iqclient import IQOptionClient
from iqoptionapi.models import Direction, OptionsTradeParams, OptionType
from _utilities import Colors, print_signal, print_trade_outcome, \
    print_trade_placement, TradeRecord


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TradingConfig:
    """
    Configuration class for trading bot with all settings.
    Using dataclass provides type hints, defaults, and easy serialization.
    """
    
    # ===== Trading Settings =====
    asset: str = "EURUSD-OTC"           # Trading asset (e.g., EURUSD-OTC, BTCUSD-OTC)
    trade_amount: float = 10.0          # Amount per trade in USD
    expiry_minutes: int = 1             # Trade expiry (1, 2, 5, 10, 15 minutes)
    option_type: str = OptionType.BINARY_OPTION         # 'binary' or 'digital'
    
    # ===== Timing Settings =====
    duration_minutes: int = 3000        # How long to run (0 = unlimited)
    trade_seconds: Tuple[int, ...] = (0, 1, 2)  # Seconds of minute to trade
    
    # ===== Risk Management =====
    max_risk_per_trade: float = 2.0     # Max % of balance to risk per trade
    daily_loss_limit: float = 50.0      # Stop trading if daily loss exceeds this
    daily_profit_limit: float = 100.0   # Stop trading if daily profit exceeds this
    max_daily_trades: int = 30          # Maximum trades per day
    max_consecutive_losses: int = 3     # Stop after this many losses in a row
    max_drawdown_percent: float = 10.0  # Stop if drawdown exceeds this %
    
    def __post_init__(self):
        """Validate configuration after initialization"""
        # Validate asset
        if not self.asset:
            raise ValueError("Asset cannot be empty")
        
        # Validate trade amount
        if self.trade_amount < 1:
            raise ValueError(f"Trade amount must be at least $1, got ${self.trade_amount}")
        
        # Validate expiry
        valid_expiries = [1, 2, 5, 10, 15]
        if self.expiry_minutes not in valid_expiries:
            logger.warning(f"Expiry {self.expiry_minutes} min may not be available. "
                          f"Valid: {valid_expiries}")
        
        # Validate risk limits
        if self.max_risk_per_trade <= 0 or self.max_risk_per_trade > 100:
            raise ValueError(f"Risk per trade must be between 1-100%, got {self.max_risk_per_trade}%")
        
        if self.daily_loss_limit <= 0:
            raise ValueError(f"Daily loss limit must be positive, got ${self.daily_loss_limit}")
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TradingConfig':
        """Create configuration from dictionary"""
        return cls(**data)
    
    def display(self):
        """Pretty print configuration"""
        logger.info("="*50)
        logger.info("📊 TRADING CONFIGURATION")
        logger.info("="*50)
        logger.info("TRADING SETTINGS:")
        logger.info(f"  Asset:           {self.asset}")
        logger.info(f"  Trade Amount:    ${self.trade_amount}")
        logger.info(f"  Expiry:          {self.expiry_minutes} minute(s)")
        logger.info(f"  Option Type:     {self.option_type.value.capitalize()}")
        logger.info(f"  Trade Seconds:   {self.trade_seconds}")
        logger.info(f"  Duration:        {self.duration_minutes} minutes")
        logger.info("-"*30)
        logger.info("RISK MANAGEMENT:")
        logger.info(f"  Risk/Trade:      {self.max_risk_per_trade}%")
        logger.info(f"  Daily Loss Lim:  ${self.daily_loss_limit}")
        logger.info(f"  Daily Profit Lim: ${self.daily_profit_limit}")
        logger.info(f"  Max Daily Trades: {self.max_daily_trades}")
        logger.info(f"  Max Consec Loss: {self.max_consecutive_losses}")
        logger.info(f"  Max Drawdown:    {self.max_drawdown_percent}%")
        logger.info("="*50)



class TradingBot:
    """
    Trading bot that uses dataclass configuration for all settings
    """
    
    def __init__(self, config: TradingConfig = None):
        # self.email = email
        # self.password = password
        
        # Use provided config or create default
        self.config = config or TradingConfig()
        
        self.client = None
        self.trade_count = 0
        self.wins = 0
        self.losses = 0

    def connect(self) -> bool:
        logger.info("🔌 Connecting to IQOption...")
        
        try:
            self.client = IQOptionClient()
            self.client.connect()

            if self.client._connected:
                balance = self.client.get_balance()
                logger.info(f"✅ Connected successfully! 💰 Account Balance: ${balance:.2f}")
            return True
        except Exception as e:
            logger.error(f"Error getting signal: {e}")

    def wait_for_minute_start(self):
        """
        Check if the seconds portion of a timestamp is 0.
        
        Args:
            timestamp: Unix timestamp in milliseconds (like 1775996973735)
        
        """
        # Convert milliseconds to seconds and create datetime object
        timestamp = self.client.message_handler.server_time
        dt = datetime.fromtimestamp(timestamp / 1000)
        # Get the current seconds (0-59)
        seconds = dt.second
        if seconds > 25:
            wait_time = 60 - seconds
            # logger.info(f"⏰ Waiting {wait_time} seconds for next minute...")
            time.sleep(wait_time)
        
        # logger.info("🎯 New minute started! Ready to trade...")
        return True

    def get_signal(self) -> Direction:
        """Get trading signal from candle"""
        try:
            candles = self.client.get_candles(
                asset_name=self.config.asset,
                count=1
            )
            
            if candles:
                candle = candles[-1]
                candle_data = {
                    'open': candle['open'],
                    'close': candle['close'],
                    'change_percent': ((candle['close'] - candle['open']) / candle['open']) * 100
                }
                
                if candle['close'] > candle['open']:
                    print_signal(Direction.CALL, candle_data)
                    return Direction.CALL
                elif candle['close'] < candle['open']:
                    print_signal(Direction.PUT, candle_data)
                    return Direction.PUT
                print_signal(Direction.INDECISION, candle_data)
                return Direction.INDECISION
        except Exception as e:
            logger.error(f"Error getting signal: {e}")
        
        return Direction.INDECISION
    
    def execute_trade(self, direction: Direction) -> Optional[TradeRecord]:
        """Execute a trade with current configuration"""

        trade_params = OptionsTradeParams(
            asset=self.config.asset,
            expiry=self.config.expiry_minutes,
            amount=self.config.trade_amount,
            direction=direction,
            option_type=self.config.option_type
        )

        # Execute
        success, order_id = self.client.execute_options_trade(trade_params)
        
        if not success or not order_id:
            logger.error(f"❌ Trade failed: {order_id}")
            return None
        
        self.trade_count += 1
        trade_record = TradeRecord(
            trade_id=order_id,
            timestamp=datetime.now().isoformat(),
            asset=self.config.asset,
            direction=direction.value,
            amount=self.config.trade_amount,
            expiry=self.config.expiry_minutes,
            outcome='pending'
        )
        
        print_trade_placement(trade_record)
        return trade_record
        
    def wait_for_trade_result(self, trade_record: TradeRecord) -> Tuple[bool, Optional[float]]:
        # Get result
        success, outcome_data, pnl = self.client.get_trade_outcome(
            trade_record.trade_id, 
            self.config.expiry_minutes
        )
        
        if success and outcome_data:
            trade_record.profit_loss = pnl
            trade_record.outcome = 'win' if pnl > 0 else 'loss' if pnl < 0 else 'breakeven'
            
            # Update statistics
            if pnl > 0:
                self.wins += 1
            elif pnl < 0:
                self.losses += 1
            
            # Print formatted outcome
            print_trade_outcome(trade_record)
            
            # Print summary statistics
            win_rate = (self.wins / self.trade_count * 100) if self.trade_count > 0 else 0
            print(f"\n{Colors.BOLD}{Colors.CYAN}📈 Session Stats: ", end="")
            print(f"Trades: {self.trade_count} | ", end="")
            print(f"{Colors.GREEN}Wins: {self.wins}{Colors.END} | ", end="")
            print(f"{Colors.RED}Losses: {self.losses}{Colors.END} | ", end="")
            print(f"Win Rate: {win_rate:.1f}%")
            
            return trade_record

    def run(self):
        """Main trading loop using configuration"""
        try:
            if not self.connect():
                sys.exit()

            end_time = time.time() + self.config.duration_minutes
            
            print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.END}")
            print(f"{Colors.BOLD}{Colors.GREEN}🚀 TRADING BOT STARTED{Colors.END}")
            print(f"{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.END}")
            print(f"{Colors.CYAN}Asset: {self.config.asset}{Colors.END}")
            print(f"{Colors.CYAN}Amount per trade: ${self.config.trade_amount}{Colors.END}")
            print(f"{Colors.CYAN}Expiry: {self.config.expiry_minutes} minute(s){Colors.END}")
            print(f"{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.END}\n")
        
            while time.time() < end_time:
                if self.wait_for_minute_start():
                    signal = self.get_signal()
                    if signal != Direction.INDECISION:
                        trade_record = self.execute_trade(signal)
                        if trade_record != None:
                            self.wait_for_trade_result(trade_record)
                    else:
                        logger.info("No signal, waiting...")
                        time.sleep(55)
        except KeyboardInterrupt:
            print(f"\n\n{Colors.BOLD}{Colors.YELLOW}{'='*60}{Colors.END}")
            print(f"{Colors.BOLD}{Colors.YELLOW}🛑 TRADING STOPPED BY USER{Colors.END}")
            print(f"{Colors.BOLD}{Colors.YELLOW}{'='*60}{Colors.END}")
            print(f"{Colors.CYAN}Final Statistics:{Colors.END}")
            print(f"  Total Trades: {self.trade_count}")
            print(f"  Wins: {Colors.GREEN}{self.wins}{Colors.END}")
            print(f"  Losses: {Colors.RED}{self.losses}{Colors.END}")
            if self.trade_count > 0:
                win_rate = (self.wins / self.trade_count * 100)
                net_pnl = (self.wins * self.config.trade_amount * 0.75) - (self.losses * self.config.trade_amount)
                print(f"  Win Rate: {win_rate:.1f}%")
                print(f"  Net P&L: {Colors.GREEN if net_pnl > 0 else Colors.RED}${net_pnl:.2f}{Colors.END}")
            print(f"{Colors.BOLD}{Colors.YELLOW}{'='*60}{Colors.END}\n")
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(1)
        
        # Disconnect
        self.client.disconnect()
        logger.info("🔌 Disconnected")


def main():
    """Run the configurable trading bot"""
    
    # Option 1: Use a preset configuration
    config = TradingConfig()
    
    # Run bot with selected configuration
    bot = TradingBot(config)
    bot.run()


if __name__ == "__main__":
    main()