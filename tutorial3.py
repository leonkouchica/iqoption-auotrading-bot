"""
TUTORIAL 3: Data Analysis & Visualization for IQ Option Trading Bot
═══════════════════════════════════════════════════════════════════════════
BUILDS UPON: Tutorial 2 (tutorial2.py)

NEW FEATURES ADDED:
  ✅ Trade History CSV Export – Save all trades to CSV file
  ✅ Equity Curve – Track balance over time
  ✅ Win/Loss Distribution – Analyze trade outcomes
  ✅ Drawdown Analysis – Visualize maximum drawdown periods
═══════════════════════════════════════════════════════════════════════════
"""

import time
import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Optional, List

from tradingconfig import TradingConfig
from iqoptionapi.iqclient import IQOptionClient
from iqoptionapi.models import Direction, OptionsTradeParams, OptionType

# Import risk management from Tutorial 2
from tutorial2 import TradingConfig, RiskManager

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
logger = logging.getLogger("autotrading bot")


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
                # 'timestamp': t.timestamp,
                'datetime': t.datetime_obj,
                'asset': t.asset,
                'direction': t.direction,
                'amount': t.amount,
                'expiry': t.expiry_minutes,
                'outcome': t.outcome,
                'pnl': t.pnl,
                'balance_before': t.balance_before,
                'balance_after': t.balance_after,
                # 'hour': t.hour,
                # 'day_of_week': t.day_of_week,
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
        """Generate all visualizations combined into one dashboard image"""
        if not VISUALIZATION_AVAILABLE:
            logger.warning("Visualization libraries not available. Skipping charts.")
            return

        if self.df is None or len(self.df) == 0:
            logger.warning("No trade data to visualize")
            return

        plt.close('all')
        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        fig.suptitle('Trading Performance Dashboard', fontsize=18, fontweight='bold')

        self._draw_equity_curve(axes[0, 0])
        self._draw_drawdown(axes[0, 1])
        self._draw_win_loss_bar(axes[1, 0])
        self._draw_win_loss_pie(axes[1, 1])

        plt.tight_layout(rect=[0, 0, 1, 0.96])
        chart_path = f"{self.config.output_dir}/dashboard.{self.config.save_format}"
        plt.savefig(chart_path, dpi=150)
        plt.close()
        logger.info(f"📊 Dashboard saved: {chart_path}")
    
    # ── helpers: each accepts an Axes, draws into it, returns nothing ──

    def _draw_equity_curve(self, ax):
        """Draw equity curve onto the given Axes"""
        cumulative_pnl = self.df['pnl'].cumsum()
        ax.plot(cumulative_pnl.values, color='steelblue', linewidth=2)
        ax.fill_between(range(len(cumulative_pnl)), 0, cumulative_pnl.values,
                        alpha=0.25, color='steelblue')
        ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        ax.set_title('Equity Curve', fontsize=13, fontweight='bold')
        ax.set_xlabel('Trade Number')
        ax.set_ylabel('Cumulative P&L ($)')
        ax.grid(True, alpha=0.3)
        final_pnl = cumulative_pnl.iloc[-1] if len(cumulative_pnl) > 0 else 0
        ax.annotate(f'Final P&L: ${final_pnl:.2f}',
                    xy=(0.02, 0.95), xycoords='axes fraction',
                    fontsize=11, fontweight='bold',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    def _draw_drawdown(self, ax):
        """Draw drawdown chart onto the given Axes"""
        cumulative = self.df['pnl'].cumsum()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / (running_max.max() if running_max.max() > 0 else 1) * 100
        ax.fill_between(range(len(drawdown)), 0, drawdown.values, color='red', alpha=0.45)
        ax.plot(drawdown.values, color='darkred', linewidth=1)
        ax.set_title('Drawdown Analysis', fontsize=13, fontweight='bold')
        ax.set_xlabel('Trade Number')
        ax.set_ylabel('Drawdown (%)')
        ax.grid(True, alpha=0.3)
        max_dd = drawdown.min()
        ax.annotate(f'Max Drawdown: {max_dd:.1f}%',
                    xy=(0.02, 0.05), xycoords='axes fraction',
                    fontsize=11, fontweight='bold', color='darkred',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    def _draw_win_loss_bar(self, ax):
        """Draw outcome bar chart onto the given Axes"""
        outcomes = self.df['outcome'].value_counts()
        colors = ['#2ecc71' if o == 'win' else '#e74c3c' if o == 'loss' else '#95a5a6'
                  for o in outcomes.index]
        ax.bar(outcomes.index, outcomes.values, color=colors, alpha=0.8)
        ax.set_title('Trade Outcomes', fontsize=13, fontweight='bold')
        ax.set_ylabel('Number of Trades')
        ax.grid(True, alpha=0.3, axis='y')
        for i, v in enumerate(outcomes.values):
            ax.text(i, v + 0.4, str(v), ha='center', fontweight='bold')

    def _draw_win_loss_pie(self, ax):
        """Draw win-rate pie chart onto the given Axes"""
        outcomes = self.df['outcome'].value_counts()
        total = len(self.df)
        win_r  = outcomes.get('win',  0) / total * 100
        loss_r = outcomes.get('loss', 0) / total * 100
        draw_r = outcomes.get('draw', 0) / total * 100
        sizes  = [win_r, loss_r, draw_r]
        labels = [f'Wins\n{win_r:.0f}%', f'Losses\n{loss_r:.0f}%', f'Draws\n{draw_r:.0f}%']
        pie_colors = ['#2ecc71', '#e74c3c', '#95a5a6']
        non_zero = [(s, l, c) for s, l, c in zip(sizes, labels, pie_colors) if s > 0]
        if non_zero:
            s, l, c = zip(*non_zero)
            ax.pie(s, labels=l, colors=c, autopct='', startangle=90)
        ax.set_title('Win Rate Distribution', fontsize=13, fontweight='bold')

    def _draw_pnl_by_hour(self, ax):
        """Draw P&L-by-hour bar chart onto the given Axes"""
        hourly = self.analyze_by_hour()
        if len(hourly) == 0:
            ax.set_visible(False)
            return
        colors = ['#2ecc71' if x > 0 else '#e74c3c' for x in hourly['total_pnl']]
        ax.bar(hourly.index, hourly['total_pnl'], color=colors, alpha=0.8)
        ax.set_title('P&L by Hour of Day', fontsize=13, fontweight='bold')
        ax.set_xlabel('Hour (24-hour format)')
        ax.set_ylabel('Total P&L ($)')
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax.grid(True, alpha=0.3, axis='y')
        for i, (hour, v) in enumerate(zip(hourly.index, hourly['total_pnl'])):
            offset = max(abs(hourly['total_pnl'].max()) * 0.03, 1)
            ax.text(hour, v + (offset if v >= 0 else -offset * 3),
                    f'${v:.0f}', ha='center', fontsize=8, fontweight='bold')
    
    def save_csv(self):
        """Save today's trades to trading_data/daily_records/trades_YYYYMMDD.csv"""
        if self.df is None or len(self.df) == 0:
            return

        # Ensure daily_records sub-directory exists
        daily_dir = Path(self.config.output_dir) / "daily_records"
        daily_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y%m%d")
        csv_path = daily_dir / f"trades_{date_str}.csv"

        if csv_path.exists():
            existing = pd.read_csv(csv_path)
            combined = pd.concat([existing, self.df], ignore_index=True)
            combined.drop_duplicates(subset=['trade_id'], keep='last', inplace=True)
            combined.to_csv(csv_path, index=False)
        else:
            self.df.to_csv(csv_path, index=False)

        logger.info(f"💾 Daily CSV saved: {csv_path}")

    def save_master_stats(self, metrics: Dict):
        """Update master CSV with today's cumulative stats.
        
        If today already has a row, the new session's trades are combined
        with the existing ones so counts, P&L and derived ratios all reflect
        the full day — not just the latest session.
        """
        if not metrics:
            return

        master_path = Path(self.config.output_dir) / "master_stats.csv"
        today       = datetime.now().strftime("%Y-%m-%d")

        # --- Pull raw counts from the current session ---
        s_trades = metrics.get('total_trades', 0)
        s_wins   = metrics.get('wins',   0)
        s_losses = metrics.get('losses', 0)
        s_draws  = metrics.get('draws',  0)
        s_pnl    = metrics.get('total_pnl', 0)
        # avg_win / avg_loss are per-trade averages; back-convert to gross sums
        s_gross_win  = metrics.get('avg_win',  0) * s_wins
        s_gross_loss = abs(metrics.get('avg_loss', 0)) * s_losses  # stored as positive
        s_lwin  = metrics.get('largest_win',  0)
        s_lloss = metrics.get('largest_loss', 0)
        s_maxdd = metrics.get('max_drawdown_percent', 0)

        if master_path.exists():
            master_df = pd.read_csv(master_path)

            if today in master_df['date'].values:
                # ── Combine with the existing day row ──
                idx = master_df.index[master_df['date'] == today][0]
                ex  = master_df.loc[idx]

                # Additive counts
                t_trades = ex['total_trades'] + s_trades
                t_wins   = ex['wins']         + s_wins
                t_losses = ex['losses']       + s_losses
                t_draws  = ex['draws']        + s_draws
                t_pnl    = round(ex['total_pnl'] + s_pnl, 2)

                # Recalculate derived metrics from combined gross figures
                t_gross_win  = ex.get('_gross_win',  ex['avg_win']  * ex['wins'])   + s_gross_win
                t_gross_loss = ex.get('_gross_loss', abs(ex['avg_loss']) * ex['losses']) + s_gross_loss

                t_avg_win  = round(t_gross_win  / t_wins,   2) if t_wins   > 0 else 0
                t_avg_loss = round(-t_gross_loss / t_losses, 2) if t_losses > 0 else 0  # keep negative
                t_win_rate = round(t_wins / t_trades * 100, 2) if t_trades > 0 else 0
                t_pf       = round(t_gross_win / t_gross_loss, 4) if t_gross_loss > 0 else float('inf')
                t_expect   = round(t_pnl / t_trades, 4) if t_trades > 0 else 0
                t_lwin     = round(max(ex['largest_win'],  s_lwin),  2)
                t_lloss    = round(min(ex['largest_loss'], s_lloss), 2)
                t_maxdd    = round(min(ex['max_drawdown_pct'], s_maxdd), 2)  # worst of the day

                master_df.loc[idx, 'last_session']     = datetime.now().strftime("%H:%M:%S")
                master_df.loc[idx, 'total_trades']     = t_trades
                master_df.loc[idx, 'wins']             = t_wins
                master_df.loc[idx, 'losses']           = t_losses
                master_df.loc[idx, 'draws']            = t_draws
                master_df.loc[idx, 'win_rate']         = t_win_rate
                master_df.loc[idx, 'total_pnl']        = t_pnl
                master_df.loc[idx, 'avg_win']          = t_avg_win
                master_df.loc[idx, 'avg_loss']         = t_avg_loss
                master_df.loc[idx, 'largest_win']      = t_lwin
                master_df.loc[idx, 'largest_loss']     = t_lloss
                master_df.loc[idx, 'profit_factor']    = t_pf
                master_df.loc[idx, 'expectancy']       = t_expect
                master_df.loc[idx, 'max_drawdown_pct'] = t_maxdd
                # sharpe_ratio: keep the latest session value (requires full series to recalc)
                master_df.loc[idx, 'sharpe_ratio']     = round(metrics.get('sharpe_ratio', 0), 4)

            else:
                # ── First session of the day – append a new row ──
                new_row = self._build_master_row(today, metrics)
                master_df = pd.concat([master_df, pd.DataFrame([new_row])], ignore_index=True)

        else:
            # ── Brand-new master CSV ──
            new_row    = self._build_master_row(today, metrics)
            master_df  = pd.DataFrame([new_row])

        master_df.to_csv(master_path, index=False)
        logger.info(f"💾 Master stats updated: {master_path}")

    def _build_master_row(self, today: str, metrics: Dict) -> Dict:
        """Build a fresh master-stats row dict from a metrics dict."""
        return {
            'date':             today,
            'last_session':     datetime.now().strftime("%H:%M:%S"),
            'total_trades':     metrics.get('total_trades', 0),
            'wins':             metrics.get('wins',   0),
            'losses':           metrics.get('losses', 0),
            'draws':            metrics.get('draws',  0),
            'win_rate':         round(metrics.get('win_rate',   0), 2),
            'total_pnl':        round(metrics.get('total_pnl',  0), 2),
            'avg_win':          round(metrics.get('avg_win',    0), 2),
            'avg_loss':         round(metrics.get('avg_loss',   0), 2),
            'largest_win':      round(metrics.get('largest_win',  0), 2),
            'largest_loss':     round(metrics.get('largest_loss', 0), 2),
            'profit_factor':    round(metrics.get('profit_factor', 0), 4),
            'expectancy':       round(metrics.get('expectancy',   0), 4),
            'sharpe_ratio':     round(metrics.get('sharpe_ratio', 0), 4),
            'max_drawdown_pct': round(metrics.get('max_drawdown_percent', 0), 2),
        }

    def save_json_report(self, metrics: Dict):
        """Save comprehensive JSON report – fixed filename, overwritten each run"""
        # Safely handle DataFrame operations when df is None or empty
        hourly_analysis = {}
        daily_analysis = {}
        
        if self.df is not None and len(self.df) > 0:
            hourly_analysis = self.analyze_by_hour().to_dict()
            daily_analysis = self.analyze_by_day().to_dict()
        
        report = {
            'generated_at': datetime.now().isoformat(),
            'summary': metrics,
            'hourly_analysis': hourly_analysis,
            'daily_analysis': daily_analysis,
            'total_trades': len(self.trades),
        }
        
        json_path = f"{self.config.output_dir}/performance_report.json"
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
    """Wait for the next minute to start (same as Tutorial 1)"""
    time.sleep(1)
    timestamp = client.message_handler.server_time
    dt = datetime.fromtimestamp(timestamp / 1000)
    seconds = dt.second
    
    if seconds > 29:  # Wait for next minute if we're past :05
        wait_time = 60 - seconds
        logger.info(f"⏰ Waiting {wait_time} seconds for next minute...")
        time.sleep(wait_time)
    
    return True


class TradingBotWithAnalytics:
    """
    Complete trading bot with risk management AND analytics.
    Integrates Tutorial 2 and Tutorial 3 features.
    """
    
    def __init__(self):
        # Risk management (Tutorial 2)
        self.risk_config = TradingConfig()
        
        # Add missing timing attributes if they don't exist
        if not hasattr(self.risk_config, 'allowed_seconds'):
            self.risk_config.allowed_seconds = set(range(0, 60))
        if not hasattr(self.risk_config, 'min_interval_seconds'):
            self.risk_config.min_interval_seconds = 5
        
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
                print(balance)
                self.risk_manager.update_balance(balance)
                self.risk_manager.starting_balance = balance
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
        
        if not self.connect():
            logger.error("Failed to connect. Exiting...")
            return

        # Step 3: Display full config now that we're live
        logger.info("✅ Connected successfully!")
        logger.info("=" * 60)
        logger.info("🚀 TUTORIAL 3: COMPLETE TRADING BOT WITH ANALYTICS")
        logger.info("=" * 60)
        logger.info(f"   📊 Account        : {self.client.appstate.balance_type_str.capitalize()}")
        logger.info(f"   💵 Balance        : ${self.risk_manager.starting_balance:.2f}")
        logger.info(f"   📊 Asset          : {self.asset}")
        logger.info(f"   💰 Risk per trade : {self.risk_config.risk_per_trade}%")
        logger.info(f"   📈 Profit Target  : ${self.risk_config.daily_profit_target}")
        logger.info(f"   🛑 Loss Limit     : ${self.risk_config.daily_loss_limit}")
        logger.info(f"   📁 Analytics dir  : {self.analytics_config.output_dir}/")
        logger.info("=" * 60)
        logger.info("🤖 Bot running  |  Press Ctrl+C to stop")
        logger.info("=" * 60)
        print("")
        
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
            
                wait_for_minute_start(self.client)
                
                signal = get_signal_from_candle(self.client, self.asset)
                
                if signal == Direction.INDECISION:
                    time.sleep(55)
                    continue
                
                self.execute_trade(signal)
                self.risk_manager.print_status()
                time.sleep(.5)
                
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
        
        # Save master stats CSV (NEW)
        self.analyzer.save_master_stats(metrics)

        # Generate charts
        if self.analytics_config.generate_charts and VISUALIZATION_AVAILABLE:
            self.analyzer.generate_charts()
            logger.info(f"📊 Charts saved to {self.analytics_config.output_dir}/")
        
        print("\n✅ Report generation complete!")
        print(f"📁 Check the '{self.analytics_config.output_dir}' folder for:")
        print("   📄 daily_records/trades_YYYYMMDD.csv – Today's trade-by-trade log")
        print("   📄 master_stats.csv                 – Running history (one row per day)")
        print("   📄 performance_report.json          – Latest session metrics (overwritten)")
        print("   📊 dashboard.png                    – Latest dashboard (overwritten)")
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