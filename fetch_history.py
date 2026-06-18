"""Fetch trade history from IQ Option."""
import logging
from iqoptionapi.iqapi import IQOptionClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)-12s %(levelname)-6s %(message)s')

client = IQOptionClient()
client.connect()
print(f"Connected. Account: {client.appstate.balance_type_str}, Balance: ${client.get_balance():.2f}")

# Get recent trades for all instrument types
print("\nFetching position history...")
positions = client.get_position_history_by_time(
    instrument_type=["digital-option", "binary-option", "turbo-option", "blitz-option"],
)
# Also try paginated
positions2 = client.get_position_history_by_page(
    instrument_type=["digital-option", "binary-option", "turbo-option", "blitz-option"],
    limit=50
)

print(f"\n{'='*70}")
print(f"TRADE HISTORY")
print(f"{'='*70}")

all_positions = positions if positions else []
if positions2:
    all_positions.extend(positions2)

if not all_positions:
    print("No positions found in history.")
else:
    total_pnl = 0
    wins = 0
    losses = 0
    for i, pos in enumerate(all_positions[:50]):
        pnl = pos.get('pnl_realized', pos.get('profit_amount', 0))
        if isinstance(pnl, (int, float)):
            total_pnl += pnl
        if isinstance(pnl, (int, float)) and pnl > 0:
            wins += 1
        elif isinstance(pnl, (int, float)) and pnl < 0:
            losses += 1
        
        print(f"\n#{i+1} | Asset: {pos.get('instrument_underlying', pos.get('active', '?'))}")
        print(f"     Direction: {pos.get('instrument_dir', pos.get('dir', '?'))}")
        print(f"     Amount: ${pos.get('invest', pos.get('sum', 0))}")
        print(f"     PnL: ${pnl}")
        print(f"     Status: {pos.get('status', '?')}")
        print(f"     Open: {pos.get('open_quote', pos.get('value', '?'))}  Close: {pos.get('close_quote', pos.get('exp_value', '?'))}")
    
    print(f"\n{'='*70}")
    print(f"SUMMARY: {len(all_positions)} trades | Wins: {wins} | Losses: {losses} | Total PnL: ${total_pnl:+.2f}")
    print(f"{'='*70}")

client.disconnect()
