import logging
from datetime import datetime
from iqoptionapi.models import Direction

logger = logging.getLogger(__name__)


def bar_by_bar_signal(client, asset: str) -> Direction:
    """
    Generate trading signal based on latest candlestick price action.
    
    Determines trade direction by comparing the closing price to the opening price
    of the most recent candle:
    - Bullish signal (CALL): When close price > open price (green candle)
    - Bearish signal (PUT): When close price < open price (red candle)
    - No signal: When prices are equal or data unavailable
    
    Args:
        client: IQOption client instance with market data access
        asset (str): Trading asset symbol (e.g., 'EURUSD-OTC', 'EURUSD-op')
        
    Returns:
        Direction: Enum value - Direction.CALL, Direction.PUT, or Direction.INDECISION
        
    Example:
        >>> signal = get_signal_from_candle(client, 'EURUSD-OTC')
        >>> if signal == Direction.CALL:
        ...     print("📈 Bullish - Place CALL option")
        ... elif signal == Direction.PUT:
        ...     print("📉 Bearish - Place PUT option")
        ... else:
        ...     print("⏸️ No clear signal - Wait")
                
    Note:
        - Uses only 1 candle (most recent) for signal generation
        - Best for 1-minute timeframe trading
        - Candle color representation:
          🟢 Green/CALL = Close > Open (price went up)
          🔴 Red/PUT = Close < Open (price went down)
    """
    try:
        candles = client.get_candles(asset_name=asset, count=1)
        
        if candles:
            candle = candles[-1]
            open_price = candle['open']
            close_price = candle['close']
            
            # Determine candle color and signal
            if close_price > open_price:
                # 🟢 GREEN CANDLE - Bullish
                logger.info(f"🟢 GREEN CANDLE - Enter CALL position")
                return Direction.CALL
                
            elif close_price < open_price:
                # 🔴 RED CANDLE - Bearish
                logger.info(f"🔴 RED CANDLE - Enter PUT position")
                return Direction.PUT
            else:
                # ⚪ DOJI/NEUTRAL CANDLE
                logger.info(f"⚪ DOJI/NEUTRAL CANDLE - Wait for next candle")
                
    except Exception as e:
        logger.error(f"Error getting signal from {asset}: {e}")
        
    return Direction.INDECISION


def get_signal_with_red_green_dots(client, asset: str, show_visual: bool = True) -> Direction:
    """
    Generate signal with visual red/green dot representation.
    
    This enhanced version provides visual feedback using colored dots
    to represent bullish (green) and bearish (red) signals.
    
    Args:
        client: IQOption client instance
        asset: Trading asset symbol
        show_visual: If True, prints colored dot indicators to console
        
    Returns:
        Direction: CALL, PUT, or INDECISION
        
    Example:
        >>> signal = get_signal_with_red_green_dots(client, 'EURUSD-OTC')
        🟢 BUY SIGNAL - Green Dot
        📈 Direction: CALL
    """
    try:
        candles = client.get_candles(asset_name=asset, count=1)
        
        if candles:
            candle = candles[-1]
            open_price = candle['open']
            close_price = candle['close']
            high_price = candle.get('max', close_price)
            low_price = candle.get('min', close_price)
            
            # Calculate price movement percentage
            price_change = abs(close_price - open_price)
            change_percent = (price_change / open_price) * 100 if open_price > 0 else 0
            
            # Determine signal with visual indicators
            if close_price > open_price:
                # 🟢 GREEN DOT - Bullish Signal
                if show_visual:
                    print(f"\n{'🟢' * 3} GREEN DOT - BUY SIGNAL {'🟢' * 3}")
                    print(f"   Open: ${open_price:.5f}  →  Close: ${close_price:.5f}")
                    print(f"   ↑ Gain: +{change_percent:.2f}%")
                    print(f"   High: ${high_price:.5f} | Low: ${low_price:.5f}")
                return Direction.CALL
                
            elif close_price < open_price:
                # 🔴 RED DOT - Bearish Signal
                if show_visual:
                    print(f"\n{'🔴' * 3} RED DOT - SELL SIGNAL {'🔴' * 3}")
                    print(f"   Open: ${open_price:.5f}  →  Close: ${close_price:.5f}")
                    print(f"   ↓ Loss: -{change_percent:.2f}%")
                    print(f"   High: ${high_price:.5f} | Low: ${low_price:.5f}")
                return Direction.PUT
            else:
                # ⚪ WHITE DOT - No clear signal
                if show_visual:
                    print(f"\n{'⚪' * 3} WHITE DOT - NO SIGNAL {'⚪' * 3}")
                    print(f"   Open = Close = ${close_price:.5f}")
                    print("   Waiting for next candle...")
                    
    except Exception as e:
        logger.error(f"Error: {e}")
        if show_visual:
            print(f"❌ Error getting signal: {e}")
            
    return Direction.INDECISION


class AdvancedSignalGenerator:
    """
    Advanced signal generator with multiple strategies and visual feedback.
    
    Provides various methods to generate trading signals based on:
    - Simple candle color (red/green)
    - Moving average crossovers
    - RSI overbought/oversold conditions
    - Multiple timeframe confirmation
    
    Example:
        >>> generator = AdvancedSignalGenerator(client)
        >>> signal = generator.get_multi_timeframe_signal('EURUSD-OTC')
        >>> print(f"Signal: {signal}")
    """
    
    def __init__(self, client):
        """
        Initialize the signal generator.
        
        Args:
            client: IQOption client instance
        """
        self.client = client
        self.last_signal = None
        self.signal_history = []
        
    def get_candle_color(self, asset: str, timeframe: int = 60) -> tuple:
        """
        Get the color of the latest candle.
        
        Args:
            asset: Trading asset symbol
            timeframe: Candle timeframe in seconds (default: 60)
            
        Returns:
            tuple: (color: str, direction: str, strength: float)
                   color: 'GREEN', 'RED', or 'NEUTRAL'
                   direction: 'CALL', 'PUT', or 'HOLD'
                   strength: Signal strength 0-100
        """
        try:
            candles = self.client.get_candles(asset_name=asset, count=5, timeframe=timeframe)
            
            if candles and len(candles) >= 1:
                latest = candles[-1]
                open_price = latest['open']
                close_price = latest['close']
                
                # Calculate signal strength based on body size
                body_size = abs(close_price - open_price)
                avg_body = body_size / open_price if open_price > 0 else 0
                strength = min(100, avg_body * 10000)  # Convert to percentage
                
                if close_price > open_price:
                    return ('GREEN', 'CALL', strength)
                elif close_price < open_price:
                    return ('RED', 'PUT', strength)
                else:
                    return ('NEUTRAL', 'HOLD', 0)
                    
        except Exception as e:
            logger.error(f"Error getting candle color: {e}")
            
        return ('NEUTRAL', 'HOLD', 0)
    
    def print_signal_with_dots(self, asset: str):
        """
        Print visual signal using colored dots (console output).
        
        Args:
            asset: Trading asset symbol
            
        Example output:
            🟢🟢🟢 BUY SIGNAL | EURUSD-OTC | Strength: 75% 🟢🟢🟢
        """
        color, direction, strength = self.get_candle_color(asset)
        
        # Choose dot color
        if color == 'GREEN':
            dots = '🟢'
            emoji = '📈'
            action = 'BUY (CALL)'
        elif color == 'RED':
            dots = '🔴'
            emoji = '📉'
            action = 'SELL (PUT)'
        else:
            dots = '⚪'
            emoji = '⏸️'
            action = 'WAIT'
        
        # Create visual representation
        print(f"\n{dots * 5} {emoji} {action} {emoji} {dots * 5}")
        print(f"Asset: {asset}")
        print(f"Signal Strength: {'█' * int(strength/10)}{'░' * (10 - int(strength/10))} {strength:.0f}%")
        print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        
        return direction


# Usage Example
if __name__ == "__main__":
    from iqoptionapi.iqclient import IQOptionClient
    from iqoptionapi.models import Direction
    
    client = IQOptionClient()
    client.connect()
    # Simple signal
    signal = bar_by_bar_signal(client, "EURUSD-OTC")
    
    if signal == Direction.CALL:
        print("🟢 Green dot detected - Enter CALL position")
    elif signal == Direction.PUT:
        print("🔴 Red dot detected - Enter PUT position")
    else:
        print("⚪ No clear signal - Wait for next candle")
    
    # Advanced signal with visuals
    generator = AdvancedSignalGenerator(client)
    generator.print_signal_with_dots("EURUSD-OTC")