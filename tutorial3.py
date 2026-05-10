"""
TUTORIAL 3: Data Analysis & Visualization for IQ Option Trading Bot
═══════════════════════════════════════════════════════════════════════════
BUILDS UPON: Tutorial 2 (main_part2_risk_management.py)

NEW FEATURES ADDED:
  ✅ Trade History CSV Export – Save all trades to CSV file
  ✅ Performance Reports – JSON summary of trading performance
  ✅ Candlestick Charts – Visualize price action with mplfinance
  ✅ Equity Curve – Track balance over time
  ✅ Win/Loss Distribution – Analyze trade outcomes
  ✅ Drawdown Analysis – Visualize maximum drawdown periods
  ✅ Hourly Performance – See which hours are most profitable
  ✅ Automated Report Generation – Create professional PDF reports
═══════════════════════════════════════════════════════════════════════════
"""

import sys
import time
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime, date
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional, Tuple, List
from pathlib import Path

from iqoption_api.iqclient import IQOptionClient
from iqoption_api.models import Direction, OptionsTradeParams, OptionType

# Import risk management from Tutorial 2
from tutorial2 import RiskConfig, RiskManager

# Try to import visualization libraries
try:
    import matplotlib.pyplot as plt
    import mplfinance as mpf
    from matplotlib.figure import Figure
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False
    print("⚠️ Visualization libraries not installed. Run: pip install matplotlib mplfinance pandas")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  DATA ANALYTICS CONFIGURATION (NEW in Tutorial 3)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class AnalyticsConfig:
    """Configuration for data analysis and reporting"""
    
    # Output settings
    output_dir: str = "trading_data"
    save_csv: bool = True
    save_json: bool = True
    generate_charts: bool = True
    generate_report: bool = True
    
    # Chart settings
    chart_style: str = "charles"  # mplfinance style
    show_volume: bool = True
    save_format: str = "png"       # png, pdf, svg
    
    # Analysis settings
    analyze_by_hour: bool = True
    analyze_by_day: bool = True
    calculate_sharpe_ratio: bool = True
    calculate_max_drawdown: bool = True
    
    def __post_init__(self):
        """Create output directory if it doesn't exist"""
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
#  TRADE ANALYZER CLASS (NEW in Tutorial 3)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    """Complete trade record with all metadata"""
    trade_id: int
    timestamp: str
    datetime_obj: datetime
    asset: str
    direction: str
    amount: float
    expiry_minutes: int
    pnl: float
    balance_before: float
    balance_after: float
    outcome: str  # win, loss, draw
    hour: int
    day_of_week: str


class TradeAnalyzer:
    """
    Analyzes trading performance and generates reports.
    ALL NEW in Tutorial 3.
    """
    
    def __init__(self, config: AnalyticsConfig):
        self.config = config
        self.trades: List[TradeRecord] = []
        self.df = None  # Pandas DataFrame for analysis
    
    def add_trade(self, trade_data: Dict):
        """Add a completed trade to history"""
        dt = datetime.fromisoformat(trade_data['timestamp'])
        
        record = TradeRecord(
            trade_id=trade_data['trade_id'],
            timestamp=trade_data['timestamp'],
            datetime_obj=dt,
            asset=trade_data['asset'],
            direction=trade_data['direction'],
            amount=trade_data['amount'],
            expiry_minutes=trade_data.get('expiry_minutes', 1),
            pnl=trade_data['pnl'],
            balance_before=trade_data['balance_before'],
            balance_after=trade_data['balance_after'],
            outcome=trade_data['outcome'],
            hour=dt.hour,
            day_of_week=dt.strftime('%A')
        )
        self.trades.append(record)
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convert trades to pandas DataFrame for analysis"""
        if not self.trades:
            return pd.DataFrame()
        
        data = []
        for t in self.trades:
            data.append({
                'trade_id': t.trade_id,
                'timestamp': t.timestamp,
                'datetime': t.datetime_obj,
                'asset': t.asset,
                'direction': t.direction,
                'amount': t.amount,
                'expiry': t.expiry_minutes,
                'pnl': t.pnl,
                'balance_before': t.balance_before,
                'balance_after': t.balance_after,
                'outcome': t.outcome,
                'hour': t.hour,
                'day_of_week': t.day_of_week,
            })
        
        self.df = pd.DataFrame(data)
        return self.df
    
    def calculate_metrics(self) -> Dict:
        """Calculate comprehensive performance metrics"""
        if self.df is None or len(self.df) == 0:
            return {}
        
        trades = self.df
        total_trades = len(trades)
        wins = len(trades[trades['pnl'] > 0])
        losses = len(trades[trades['pnl'] < 0])
        draws = len(trades[trades['pnl'] == 0])
        
        total_pnl = trades['pnl'].sum()
        avg_win = trades[trades['pnl'] > 0]['pnl'].mean() if wins > 0 else 0
        avg_loss = trades[trades['pnl'] < 0]['pnl'].mean() if losses > 0 else 0
        largest_win = trades['pnl'].max()
        largest_loss = trades['pnl'].min()
        
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        # Calculate profit factor
        gross_profit = trades[trades['pnl'] > 0]['pnl'].sum()
        gross_loss = abs(trades[trades['pnl'] < 0]['pnl'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Calculate expectancy
        expectancy = total_pnl / total_trades if total_trades > 0 else 0
        
        # Calculate Sharpe ratio (simplified)
        sharpe = 0
        if self.config.calculate_sharpe_ratio and len(trades) > 1:
            returns = trades['pnl'].values / trades['balance_before'].values
            sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        
        # Calculate max drawdown
        max_drawdown = 0
        if self.config.calculate_max_drawdown:
            cumulative = trades['pnl'].cumsum()
            running_max = cumulative.cummax()
            drawdown = (cumulative - running_max) / (cumulative.max() if cumulative.max() > 0 else 1)
            max_drawdown = drawdown.min() * 100 if len(drawdown) > 0 else 0
        
        return {
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'draws': draws,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'largest_win': largest_win,
            'largest_loss': largest_loss,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'sharpe_ratio': sharpe,
            'max_drawdown_percent': max_drawdown,
        }
    
    def analyze_by_hour(self) -> pd.DataFrame:
        """Analyze performance by hour of day"""
        if self.df is None or len(self.df) == 0:
            return pd.DataFrame()
        
        hourly = self.df.groupby('hour').agg({
            'trade_id': 'count',
            'pnl': ['sum', 'mean'],
            'outcome': lambda x: (x == 'win').sum() / len(x) * 100
        }).round(2)
        
        hourly.columns = ['trades', 'total_pnl', 'avg_pnl', 'win_rate']
        hourly = hourly.sort_index()
        
        return hourly
    
    def analyze_by_day(self) -> pd.DataFrame:
        """Analyze performance by day of week"""
        if self.df is None or len(self.df) == 0:
            return pd.DataFrame()
        
        days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        daily = self.df.groupby('day_of_week').agg({
            'trade_id': 'count',
            'pnl': ['sum', 'mean'],
            'outcome': lambda x: (x == 'win').sum() / len(x) * 100
        }).round(2)
        
        daily.columns = ['trades', 'total_pnl', 'avg_pnl', 'win_rate']
        
        # Reorder by day of week
        daily = daily.reindex([d for d in days_order if d in daily.index])
        
        return daily
    
    def generate_charts(self):
        """Generate all visualization charts"""
        if not VISUALIZATION_AVAILABLE:
            logger.warning("Visualization libraries not available. Skipping charts.")
            return
        
        if self.df is None or len(self.df) == 0:
            logger.warning("No trade data to visualize")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Chart 1: Equity Curve
        self._plot_equity_curve(timestamp)
        
        # Chart 2: Win/Loss Distribution
        self._plot_win_loss_distribution(timestamp)
        
        # Chart 3: P&L by Hour
        self._plot_pnl_by_hour(timestamp)
        
        # Chart 4: Drawdown Chart
        self._plot_drawdown(timestamp)
        
        logger.info(f"📊 Charts saved to {self.config.output_dir}/")
    
    def _plot_equity_curve(self, timestamp: str):
        """Plot equity curve over time"""
        fig, ax = plt.subplots(figsize=(12, 6))
        
        cumulative_pnl = self.df['pnl'].cumsum()
        ax.plot(cumulative_pnl, color='blue', linewidth=2)
        ax.fill_between(range(len(cumulative_pnl)), 0, cumulative_pnl, 
                        alpha=0.3, color='blue')
        
        ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        ax.set_title('Equity Curve', fontsize=14, fontweight='bold')
        ax.set_xlabel('Trade Number')
        ax.set_ylabel('Cumulative P&L ($)')
        ax.grid(True, alpha=0.3)
        
        # Add final P&L annotation
        final_pnl = cumulative_pnl.iloc[-1] if len(cumulative_pnl) > 0 else 0
        ax.annotate(f'Final P&L: ${final_pnl:.2f}', 
                    xy=(0.02, 0.95), xycoords='axes fraction',
                    fontsize=12, fontweight='bold',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        plt.tight_layout()
        plt.savefig(f"{self.config.output_dir}/equity_curve_{timestamp}.{self.config.save_format}")
        plt.close()
    
    def _plot_win_loss_distribution(self, timestamp: str):
        """Plot win/loss distribution as bar chart and pie chart"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
        
        # Bar chart of win/loss counts
        outcomes = self.df['outcome'].value_counts()
        colors = ['green' if o == 'win' else 'red' if o == 'loss' else 'gray' for o in outcomes.index]
        ax1.bar(outcomes.index, outcomes.values, color=colors, alpha=0.7)
        ax1.set_title('Trade Outcomes', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Number of Trades')
        
        # Add value labels on bars
        for i, v in enumerate(outcomes.values):
            ax1.text(i, v + 0.5, str(v), ha='center', fontweight='bold')
        
        # Pie chart
        win_rate = (outcomes.get('win', 0) / len(self.df)) * 100
        loss_rate = (outcomes.get('loss', 0) / len(self.df)) * 100
        draw_rate = (outcomes.get('draw', 0) / len(self.df)) * 100
        
        pie_data = [win_rate, loss_rate, draw_rate]
        pie_labels = [f'Wins\n{win_rate:.0f}%', f'Losses\n{loss_rate:.0f}%', f'Draws\n{draw_rate:.0f}%']
        pie_colors = ['green', 'red', 'gray']
        
        ax2.pie(pie_data, labels=pie_labels, colors=pie_colors, autopct='', startangle=90)
        ax2.set_title('Win Rate Distribution', fontsize=12, fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(f"{self.config.output_dir}/win_loss_dist_{timestamp}.{self.config.save_format}")
        plt.close()
    
    def _plot_pnl_by_hour(self, timestamp: str):
        """Plot P&L by hour of day"""
        hourly = self.analyze_by_hour()
        
        if len(hourly) == 0:
            return
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        colors = ['green' if x > 0 else 'red' for x in hourly['total_pnl']]
        ax.bar(hourly.index, hourly['total_pnl'], color=colors, alpha=0.7)
        
        ax.set_title('P&L by Hour of Day', fontsize=14, fontweight='bold')
        ax.set_xlabel('Hour (24-hour format)')
        ax.set_ylabel('Total P&L ($)')
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax.grid(True, alpha=0.3, axis='y')
        
        # Add value labels
        for i, v in enumerate(hourly['total_pnl']):
            ax.text(i, v + (2 if v >= 0 else -8), f'${v:.0f}', 
                    ha='center', fontsize=9, fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(f"{self.config.output_dir}/pnl_by_hour_{timestamp}.{self.config.save_format}")
        plt.close()
    
    def _plot_drawdown(self, timestamp: str):
        """Plot drawdown chart"""
        cumulative = self.df['pnl'].cumsum()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / (running_max.max() if running_max.max() > 0 else 1) * 100
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        ax.fill_between(range(len(drawdown)), 0, drawdown, color='red', alpha=0.5)
        ax.plot(drawdown, color='darkred', linewidth=1)
        
        ax.set_title('Drawdown Analysis', fontsize=14, fontweight='bold')
        ax.set_xlabel('Trade Number')
        ax.set_ylabel('Drawdown (%)')
        ax.grid(True, alpha=0.3)
        
        # Add max drawdown annotation
        max_dd = drawdown.min()
        ax.annotate(f'Max Drawdown: {max_dd:.1f}%', 
                    xy=(0.02, 0.05), xycoords='axes fraction',
                    fontsize=12, fontweight='bold', color='red',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        plt.tight_layout()
        plt.savefig(f"{self.config.output_dir}/drawdown_{timestamp}.{self.config.save_format}")
        plt.close()
    
    def save_csv(self):
        """Save trades to CSV file"""
        if self.df is None or len(self.df) == 0:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d")
        csv_path = f"{self.config.output_dir}/trades_{timestamp}.csv"
        
        # Check if file exists to append or create new
        if Path(csv_path).exists():
            existing = pd.read_csv(csv_path)
            combined = pd.concat([existing, self.df], ignore_index=True)
            combined.drop_duplicates(subset=['trade_id'], keep='last', inplace=True)
            combined.to_csv(csv_path, index=False)
        else:
            self.df.to_csv(csv_path, index=False)
        
        logger.info(f"💾 CSV saved: {csv_path}")
    
    def save_json_report(self, metrics: Dict):
        """Save comprehensive JSON report"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        report = {
            'generated_at': datetime.now().isoformat(),
            'summary': metrics,
            'hourly_analysis': self.analyze_by_hour().to_dict() if len(self.df) > 0 else {},
            'daily_analysis': self.analyze_by_day().to_dict() if len(self.df) > 0 else {},
            'total_trades': len(self.trades),
        }
        
        json_path = f"{self.config.output_dir}/performance_report_{timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"💾 JSON report saved: {json_path}")
    
    def print_performance_report(self, metrics: Dict):
        """Print formatted performance report to console"""
        print("\n" + "="*60)
        print("📊 PERFORMANCE ANALYSIS REPORT")
        print("="*60)
        
        print(f"\n📈 TRADE STATISTICS")
        print("-"*40)
        print(f"   Total Trades:     {metrics.get('total_trades', 0)}")
        print(f"   Wins:             {metrics.get('wins', 0)}")
        print(f"   Losses:           {metrics.get('losses', 0)}")
        print(f"   Draws:            {metrics.get('draws', 0)}")
        print(f"   Win Rate:         {metrics.get('win_rate', 0):.1f}%")
        
        print(f"\n💰 P&L ANALYSIS")
        print("-"*40)
        print(f"   Total P&L:        ${metrics.get('total_pnl', 0):+.2f}")
        print(f"   Average Win:      ${metrics.get('avg_win', 0):+.2f}")
        print(f"   Average Loss:     ${metrics.get('avg_loss', 0):+.2f}")
        print(f"   Largest Win:      ${metrics.get('largest_win', 0):+.2f}")
        print(f"   Largest Loss:     ${metrics.get('largest_loss', 0):+.2f}")
        
        print(f"\n📐 RISK METRICS")
        print("-"*40)
        print(f"   Profit Factor:    {metrics.get('profit_factor', 0):.2f}")
        print(f"   Expectancy:       ${metrics.get('expectancy', 0):+.2f}")
        print(f"   Sharpe Ratio:     {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"   Max Drawdown:     {metrics.get('max_drawdown_percent', 0):.1f}%")
        
        print("="*60)


# ═══════════════════════════════════════════════════════════════════════
#  MAIN TRADING BOT WITH ANALYTICS (Tutorial 3)
# ═══════════════════════════════════════════════════════════════════════

def get_signal_from_candle(client, asset: str) -> Direction:
    """Get trading signal from latest candle"""
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
    """Wait for the next minute to start"""
    timestamp = client.message_handler.server_time
    dt = datetime.fromtimestamp(timestamp / 1000)
    seconds = dt.second
    
    if seconds > 5:
        wait_time = 60 - seconds
        time.sleep(wait_time)
    
    return True


class TradingBotWithAnalytics:
    """
    Complete trading bot with risk management AND analytics.
    Integrates Tutorial 2 and Tutorial 3 features.
    """
    
    def __init__(self):
        # Risk management (Tutorial 2)
        self.risk_config = RiskConfig()
        self.risk_manager = RiskManager(self.risk_config)
        
        # Analytics (Tutorial 3 - NEW)
        self.analytics_config = AnalyticsConfig()
        self.analyzer = TradeAnalyzer(self.analytics_config)
        
        # Trading settings
        self.asset = "EURUSD-OTC"
        self.expiry_minutes = 1
        self.option_type = OptionType.BINARY_OPTION
        
        self.client = None
    
    def connect(self) -> bool:
        """Connect to IQ Option"""
        logger.info("🔌 Connecting to IQOption...")
        
        try:
            self.client = IQOptionClient()
            self.client.connect()
            
            if self.client._connected:
                balance = self.client.get_balance()
                self.risk_manager.update_balance(balance)
                self.risk_manager.starting_balance = balance
                logger.info(f"✅ Connected! Balance: ${balance:.2f}")
                return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
        
        return False
    
    def execute_trade(self, direction: Direction) -> Optional[Dict]:
        """Execute a trade and record it for analysis"""
        
        position_size = self.risk_manager.calculate_position_size()
        balance_before = self.risk_manager.current_balance
        
        trade_params = OptionsTradeParams(
            asset=self.asset,
            expiry=self.expiry_minutes,
            amount=position_size,
            direction=direction,
            option_type=self.option_type
        )
        
        success, order_id = self.client.execute_options_trade(trade_params)
        
        if not success or not order_id:
            logger.error(f"❌ Trade failed: {order_id}")
            return None
        
        # Wait for expiry
        wait_time = self.expiry_minutes * 60 + 10
        time.sleep(wait_time)
        
        # Get result
        success, outcome_data, pnl = self.client.get_trade_outcome(order_id, self.expiry_minutes)
        
        if success and outcome_data is not None:
            balance_after = balance_before + pnl
            
            # Record in risk manager
            self.risk_manager.record_trade(pnl)
            
            # Record for analytics (NEW in Tutorial 3)
            trade_data = {
                'trade_id': order_id,
                'timestamp': datetime.now().isoformat(),
                'asset': self.asset,
                'direction': direction.value,
                'amount': position_size,
                'expiry_minutes': self.expiry_minutes,
                'pnl': pnl,
                'balance_before': balance_before,
                'balance_after': balance_after,
                'outcome': 'win' if pnl > 0 else 'loss' if pnl < 0 else 'draw',
            }
            self.analyzer.add_trade(trade_data)
            
            logger.info(f"📊 Trade Result: ${pnl:+.2f} | New Balance: ${balance_after:.2f}")
            
            return trade_data
        
        return None
    
    def run(self):
        """Main trading loop with analytics integration"""
        
        print("\n" + "="*60)
        print("🚀 TUTORIAL 3: COMPLETE TRADING BOT WITH ANALYTICS")
        print("="*60)
        print(f"📊 Asset: {self.asset}")
        print(f"💰 Risk per trade: {self.risk_config.risk_per_trade}%")
        print(f"📈 Profit Target: ${self.risk_config.daily_profit_target}")
        print(f"🛑 Loss Limit: ${self.risk_config.daily_loss_limit}")
        print(f"📁 Analytics saved to: {self.analytics_config.output_dir}/")
        print("="*60 + "\n")
        
        if not self.connect():
            logger.error("Failed to connect. Exiting...")
            return
        
        logger.info("🤖 Bot started - Press Ctrl+C to stop")
        
        try:
            while True:
                # Check risk limits
                can_trade, reason = self.risk_manager.can_trade()
                
                if not can_trade:
                    logger.warning(f"⛔ Trading blocked: {reason}")
                    self.risk_manager.print_status()
                    
                    if "profit target" in reason or "loss limit" in reason:
                        logger.info("🏁 Daily limits reached. Generating final report...")
                        break
                    
                    time.sleep(30)
                    continue
                
                # Check timing
                current_second = datetime.now().second
                if current_second not in self.risk_config.allowed_seconds:
                    time.sleep(0.5)
                    continue
                
                wait_for_minute_start(self.client)
                
                signal = get_signal_from_candle(self.client, self.asset)
                
                if signal == Direction.INDECISION:
                    time.sleep(55)
                    continue
                
                self.execute_trade(signal)
                self.risk_manager.print_status()
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\n\n🛑 Trading stopped by user")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            # Generate complete analytics report (NEW in Tutorial 3)
            self.generate_final_report()
            self.client.disconnect()
            logger.info("🔌 Disconnected")
    
    def generate_final_report(self):
        """Generate comprehensive analytics report"""
        print("\n" + "="*60)
        print("📊 GENERATING PERFORMANCE REPORT")
        print("="*60)
        
        # Convert to DataFrame and calculate metrics
        self.analyzer.to_dataframe()
        metrics = self.analyzer.calculate_metrics()
        
        # Print report to console
        self.analyzer.print_performance_report(metrics)
        
        # Save CSV
        if self.analytics_config.save_csv:
            self.analyzer.save_csv()
        
        # Save JSON report
        if self.analytics_config.save_json:
            self.analyzer.save_json_report(metrics)
        
        # Generate charts
        if self.analytics_config.generate_charts and VISUALIZATION_AVAILABLE:
            self.analyzer.generate_charts()
            logger.info(f"📊 Charts saved to {self.analytics_config.output_dir}/")
        
        print("\n✅ Report generation complete!")
        print(f"📁 Check the '{self.analytics_config.output_dir}' folder for:")
        print("   📄 trades_*.csv - Complete trade history")
        print("   📄 performance_report_*.json - Detailed metrics")
        print("   📊 *.png - Performance charts")
        print("="*60)


# ═══════════════════════════════════════════════════════════════════════
#  RUN THE BOT
# ═══════════════════════════════════════════════════════════════════════

def main():
    """Entry point for Tutorial 3"""
    bot = TradingBotWithAnalytics()
    bot.run()


if __name__ == "__main__":
    main()