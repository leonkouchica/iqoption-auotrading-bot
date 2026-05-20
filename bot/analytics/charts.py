import logging

logger = logging.getLogger(__name__)

try:
    import matplotlib.pyplot as plt
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False
    logger.warning("matplotlib not installed. Charts disabled.")


class ChartGenerator:
    def __init__(self, config):
        self.config = config

    def generate(self, df):
        if not VISUALIZATION_AVAILABLE:
            logger.warning("Visualization libraries not available. Skipping charts.")
            return
        if df is None or len(df) == 0:
            logger.warning("No trade data to visualize.")
            return

        plt.close('all')
        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        fig.suptitle('Trading Performance Dashboard', fontsize=18, fontweight='bold')

        self._draw_equity_curve(axes[0, 0], df)
        self._draw_drawdown(axes[0, 1], df)
        self._draw_win_loss_bar(axes[1, 0], df)
        self._draw_win_loss_pie(axes[1, 1], df)

        plt.tight_layout(rect=[0, 0, 1, 0.96])
        path = f"{self.config.output_dir}/dashboard.{self.config.save_format}"
        plt.savefig(path, dpi=150)
        plt.close()
        logger.info(f"📊 Dashboard saved: {path}")

    def _draw_equity_curve(self, ax, df):
        cumulative_pnl = df['pnl'].cumsum()
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

    def _draw_drawdown(self, ax, df):
        cumulative = df['pnl'].cumsum()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / (running_max.max() if running_max.max() > 0 else 1) * 100
        ax.fill_between(range(len(drawdown)), 0, drawdown.values, color='red', alpha=0.45)
        ax.plot(drawdown.values, color='darkred', linewidth=1)
        ax.set_title('Drawdown Analysis', fontsize=13, fontweight='bold')
        ax.set_xlabel('Trade Number')
        ax.set_ylabel('Drawdown (%)')
        ax.grid(True, alpha=0.3)
        ax.annotate(f'Max Drawdown: {drawdown.min():.1f}%',
                    xy=(0.02, 0.05), xycoords='axes fraction',
                    fontsize=11, fontweight='bold', color='darkred',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    def _draw_win_loss_bar(self, ax, df):
        outcomes = df['outcome'].value_counts()
        colors = ['#2ecc71' if o == 'win' else '#e74c3c' if o == 'loss' else '#95a5a6'
                  for o in outcomes.index]
        ax.bar(outcomes.index, outcomes.values, color=colors, alpha=0.8)
        ax.set_title('Trade Outcomes', fontsize=13, fontweight='bold')
        ax.set_ylabel('Number of Trades')
        ax.grid(True, alpha=0.3, axis='y')
        for i, v in enumerate(outcomes.values):
            ax.text(i, v + 0.4, str(v), ha='center', fontweight='bold')

    def _draw_win_loss_pie(self, ax, df):
        outcomes = df['outcome'].value_counts()
        total = len(df)
        win_r  = outcomes.get('win',  0) / total * 100
        loss_r = outcomes.get('loss', 0) / total * 100
        draw_r = outcomes.get('draw', 0) / total * 100
        sizes  = [win_r, loss_r, draw_r]
        labels = [f'Wins\n{win_r:.0f}%', f'Losses\n{loss_r:.0f}%', f'Draws\n{draw_r:.0f}%']
        colors = ['#2ecc71', '#e74c3c', '#95a5a6']
        non_zero = [(s, l, c) for s, l, c in zip(sizes, labels, colors) if s > 0]
        if non_zero:
            s, l, c = zip(*non_zero)
            ax.pie(s, labels=l, colors=c, autopct='', startangle=90)
        ax.set_title('Win Rate Distribution', fontsize=13, fontweight='bold')