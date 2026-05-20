import logging
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional

from bot.analytics.charts import ChartGenerator

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
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
    outcome: str


class TradeAnalyzer:
    def __init__(self, config):
        self.config = config
        self.trades: List[TradeRecord] = []
        self.df: Optional[pd.DataFrame] = None
        self.charts = ChartGenerator(config)

    def add_trade(self, trade_data: Dict):
        dt = datetime.fromisoformat(trade_data['timestamp'])
        self.trades.append(TradeRecord(
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
        ))

    def to_dataframe(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        self.df = pd.DataFrame([{
            'trade_id':       t.trade_id,
            'datetime':       t.datetime_obj,
            'asset':          t.asset,
            'direction':      t.direction,
            'amount':         t.amount,
            'expiry':         t.expiry_minutes,
            'outcome':        t.outcome,
            'pnl':            t.pnl,
            'balance_before': t.balance_before,
            'balance_after':  t.balance_after,
        } for t in self.trades])
        return self.df

    def calculate_metrics(self) -> Dict:
        if self.df is None or len(self.df) == 0:
            return {}
        df = self.df
        total  = len(df)
        wins   = len(df[df['pnl'] > 0])
        losses = len(df[df['pnl'] < 0])
        draws  = len(df[df['pnl'] == 0])
        total_pnl    = df['pnl'].sum()
        gross_profit = df[df['pnl'] > 0]['pnl'].sum()
        gross_loss   = abs(df[df['pnl'] < 0]['pnl'].sum())

        sharpe = 0
        if self.config.calculate_sharpe_ratio and total > 1:
            returns = df['pnl'].values / df['balance_before'].values
            sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

        max_drawdown = 0
        if self.config.calculate_max_drawdown:
            cumulative  = df['pnl'].cumsum()
            running_max = cumulative.cummax()
            drawdown    = (cumulative - running_max) / (cumulative.max() if cumulative.max() > 0 else 1)
            max_drawdown = drawdown.min() * 100

        return {
            'total_trades':         total,
            'wins':                 wins,
            'losses':               losses,
            'draws':                draws,
            'win_rate':             wins / total * 100 if total > 0 else 0,
            'total_pnl':            total_pnl,
            'avg_win':              df[df['pnl'] > 0]['pnl'].mean() if wins > 0 else 0,
            'avg_loss':             df[df['pnl'] < 0]['pnl'].mean() if losses > 0 else 0,
            'largest_win':          df['pnl'].max(),
            'largest_loss':         df['pnl'].min(),
            'profit_factor':        gross_profit / gross_loss if gross_loss > 0 else float('inf'),
            'expectancy':           total_pnl / total if total > 0 else 0,
            'sharpe_ratio':         sharpe,
            'max_drawdown_percent': max_drawdown,
        }

    def save_csv(self):
        if self.df is None or len(self.df) == 0:
            return
        daily_dir = Path(self.config.output_dir) / "daily_records"
        daily_dir.mkdir(parents=True, exist_ok=True)
        csv_path = daily_dir / f"trades_{datetime.now().strftime('%Y%m%d')}.csv"
        if csv_path.exists():
            existing = pd.read_csv(csv_path)
            combined = pd.concat([existing, self.df], ignore_index=True)
            combined.drop_duplicates(subset=['trade_id'], keep='last', inplace=True)
            combined.to_csv(csv_path, index=False)
        else:
            self.df.to_csv(csv_path, index=False)
        logger.info(f"💾 Daily CSV saved: {csv_path}")

    def save_master_stats(self, metrics: Dict):
        if not metrics:
            return
        master_path = Path(self.config.output_dir) / "master_stats.csv"
        today = datetime.now().strftime("%Y-%m-%d")

        s_wins   = metrics.get('wins',   0)
        s_losses = metrics.get('losses', 0)
        s_trades = metrics.get('total_trades', 0)
        s_pnl    = metrics.get('total_pnl', 0)
        s_gross_win  = metrics.get('avg_win',  0) * s_wins
        s_gross_loss = abs(metrics.get('avg_loss', 0)) * s_losses

        if master_path.exists():
            master_df = pd.read_csv(master_path)
            if today in master_df['date'].values:
                idx = master_df.index[master_df['date'] == today][0]
                ex  = master_df.loc[idx]
                t_wins   = ex['wins']         + s_wins
                t_losses = ex['losses']       + s_losses
                t_trades = ex['total_trades'] + s_trades
                t_pnl    = round(ex['total_pnl'] + s_pnl, 2)
                t_gross_win  = ex['avg_win']       * ex['wins']   + s_gross_win
                t_gross_loss = abs(ex['avg_loss'])  * ex['losses'] + s_gross_loss
                updates = {
                    'last_session':     datetime.now().strftime("%H:%M:%S"),
                    'total_trades':     t_trades,
                    'wins':             t_wins,
                    'losses':           t_losses,
                    'draws':            ex['draws'] + metrics.get('draws', 0),
                    'win_rate':         round(t_wins / t_trades * 100, 2) if t_trades > 0 else 0,
                    'total_pnl':        t_pnl,
                    'avg_win':          round(t_gross_win  / t_wins,    2) if t_wins   > 0 else 0,
                    'avg_loss':         round(-t_gross_loss / t_losses,  2) if t_losses > 0 else 0,
                    'largest_win':      round(max(ex['largest_win'],  metrics.get('largest_win',  0)), 2),
                    'largest_loss':     round(min(ex['largest_loss'], metrics.get('largest_loss', 0)), 2),
                    'profit_factor':    round(t_gross_win / t_gross_loss, 4) if t_gross_loss > 0 else float('inf'),
                    'expectancy':       round(t_pnl / t_trades, 4) if t_trades > 0 else 0,
                    'sharpe_ratio':     round(metrics.get('sharpe_ratio', 0), 4),
                    'max_drawdown_pct': round(min(ex['max_drawdown_pct'], metrics.get('max_drawdown_percent', 0)), 2),
                }
                for col, val in updates.items():
                    master_df.loc[idx, col] = val
            else:
                master_df = pd.concat(
                    [master_df, pd.DataFrame([self._build_master_row(today, metrics)])],
                    ignore_index=True
                )
        else:
            master_df = pd.DataFrame([self._build_master_row(today, metrics)])

        master_df.to_csv(master_path, index=False)
        logger.info(f"💾 Master stats updated: {master_path}")

    def _build_master_row(self, today: str, metrics: Dict) -> Dict:
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

    def print_performance_report(self, metrics: Dict):
        print("\n" + "=" * 60)
        print("📊 PERFORMANCE ANALYSIS REPORT")
        print("=" * 60)
        print("\n📈 TRADE STATISTICS")
        print("-" * 40)
        print(f"   Total Trades:  {metrics.get('total_trades', 0)}")
        print(f"   Wins:          {metrics.get('wins', 0)}")
        print(f"   Losses:        {metrics.get('losses', 0)}")
        print(f"   Draws:         {metrics.get('draws', 0)}")
        print(f"   Win Rate:      {metrics.get('win_rate', 0):.1f}%")
        print("\n💰 P&L ANALYSIS")
        print("-" * 40)
        print(f"   Total P&L:     ${metrics.get('total_pnl',    0):+.2f}")
        print(f"   Average Win:   ${metrics.get('avg_win',      0):+.2f}")
        print(f"   Average Loss:  ${metrics.get('avg_loss',     0):+.2f}")
        print(f"   Largest Win:   ${metrics.get('largest_win',  0):+.2f}")
        print(f"   Largest Loss:  ${metrics.get('largest_loss', 0):+.2f}")
        print("\n📐 RISK METRICS")
        print("-" * 40)
        print(f"   Profit Factor: {metrics.get('profit_factor', 0):.2f}")
        print(f"   Expectancy:    ${metrics.get('expectancy',   0):+.2f}")
        print(f"   Sharpe Ratio:  {metrics.get('sharpe_ratio',  0):.2f}")
        print(f"   Max Drawdown:  {metrics.get('max_drawdown_percent', 0):.1f}%")
        print("=" * 60)

    def generate_charts(self):
        self.charts.generate(self.df)