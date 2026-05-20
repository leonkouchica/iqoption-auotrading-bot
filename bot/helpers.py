import time
import logging
from datetime import datetime
from iqoptionapi.models import Direction

logger = logging.getLogger(__name__)


def wait_for_minute_start(client):
    time.sleep(1)
    dt = datetime.fromtimestamp(client.message_handler.server_time / 1000)
    seconds = dt.second
    if seconds > 29:
        wait_time = 60 - seconds
        logger.info(f"⏰ Waiting {wait_time} seconds for next minute...")
        time.sleep(wait_time)
    return True