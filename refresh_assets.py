"""Refresh asset list from IQ Option API."""
import os, sys

# Change to the instruments directory so files are written to the right place
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'iqoptionapi', 'instruments'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from iqoptionapi.iqapi import IQOptionClient

client = IQOptionClient()
client.connect()

print("Fetching live assets from IQ Option...")
client.market_manager.save_underlying_assests_to_file()

print("Done. iqoptionapi/instruments/options_assests.py and marginal_assests.py regenerated.")
client.disconnect()
