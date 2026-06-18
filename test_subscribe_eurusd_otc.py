import logging
from iqoptionapi.iqapi import IQOptionClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)-12s %(levelname)-6s %(message)s')
logger = logging.getLogger('test')

try:
    client = IQOptionClient()
    client.connect()
    logger.info(f'connected: {client._connected}')
    candles = client.get_candles(asset_name='EURUSD-OTC', count=3, timeframe=60)
    logger.info(f'candles received: {len(candles) if candles else 0}')
    print(candles)
except Exception as e:
    logger.exception('Error fetching candles')
finally:
    try:
        client.disconnect()
    except Exception:
        pass
