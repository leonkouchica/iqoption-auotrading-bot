import logging
import time
from iqoptionapi.iqapi import IQOptionClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)-12s %(levelname)-6s %(message)s')
logger = logging.getLogger('test_stream')

client = IQOptionClient()
client.connect()
logger.info(f'connected: {client._connected}')

# Inspect available methods
has_start = hasattr(client, 'start_candle_stream')
logger.info(f'IQOptionClient has start_candle_stream: {has_start}')

result = None
try:
    if has_start:
        result = client.start_candle_stream(asset='EURUSD-OTC', candle_size=60)
        logger.info(f'start_candle_stream returned: {result}')
    else:
        # Fallback to candle_manager if present
        cm = getattr(client, 'candle_manager', None)
        logger.info(f'candle_manager present: {cm is not None}')
        if cm and hasattr(cm, 'start_stream'):
            result = cm.start_stream('EURUSD-OTC', 60)
            logger.info(f'candle_manager.start_stream returned: {result}')
        else:
            logger.warning('No start method found for candle subscription')

    # Wait briefly to capture any incoming candle messages via message handler
    time.sleep(5)

except Exception:
    logger.exception('Error while starting candle stream')
finally:
    try:
        client.disconnect()
    except Exception:
        pass
    logger.info('Disconnected')

print('RESULT:', result)
