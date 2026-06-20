import logging
from typing import Dict
from datetime import datetime
from iqoptionapi.models import Direction
from dataclasses import dataclass, field, asdict


logger = logging.getLogger(__name__)


def get_trade_decision(candle: Dict) -> Direction:
    """
    Determine the color of a candle

    Args:
        candle: Dictionary containing 'open' and 'close' prices

    Returns:
        Direction enum value
    """
    if candle["close"] > candle["open"]:
        logger.info("Signal -> CALL")
        return Direction.CALL
    elif candle["close"] < candle["open"]:
        logger.info("Signal -> PUT")
        return Direction.PUT
    logger.info("Signal -> INDECISION")
    return Direction.INDECISION


# ANSI color codes for beautiful terminal output
class Colors:
    HEADER    = '\033[95m'
    BLUE      = '\033[94m'
    CYAN      = '\033[96m'
    GREEN     = '\033[92m'
    YELLOW    = '\033[93m'
    RED       = '\033[91m'
    BOLD      = '\033[1m'
    UNDERLINE = '\033[4m'
    END       = '\033[0m'


@dataclass
class TradeRecord:
    """Record of a single trade"""
    trade_id:    int
    timestamp:   str
    asset:       str
    direction:   str
    amount:      float
    expiry:      int
    outcome:     str  = None
    profit_loss: float = 0.00


def print_signal(direction: Direction, candle_data: dict = None):
    """Print beautiful signal output"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}🔔 SIGNAL GENERATED{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")

    if direction == Direction.CALL:
        print(f"{Colors.GREEN}📈 Direction: {Colors.BOLD}CALL (Bullish){Colors.END}")
    elif direction == Direction.PUT:
        print(f"{Colors.RED}📉 Direction: {Colors.BOLD}PUT (Bearish){Colors.END}")
    else:
        print(f"{Colors.YELLOW}⚖️ Direction: {Colors.BOLD}NEUTRAL (No Trade){Colors.END}")
        print(f"{Colors.YELLOW}   No clear signal detected{Colors.END}")

    if candle_data:
        print(f"   Last 1MIN Change: {candle_data.get('change_percent', 0):.2f}%")

    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}\n")


def print_trade_placement(trade_record: TradeRecord):
    """Print beautiful trade placement output"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}💰 TRADE PLACED{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.CYAN}📝 Order ID:   {Colors.BOLD}{trade_record.trade_id}{Colors.END}")
    print(f"{Colors.CYAN}🎯 Asset:      {Colors.BOLD}{trade_record.asset}{Colors.END}")

    if trade_record.direction.upper() == "CALL":
        print(f"{Colors.CYAN}📈 Direction:  {Colors.BOLD}{Colors.GREEN}{trade_record.direction.upper()}{Colors.END}")
    else:
        print(f"{Colors.CYAN}📉 Direction:  {Colors.BOLD}{Colors.RED}{trade_record.direction.upper()}{Colors.END}")

    print(f"{Colors.CYAN}💵 Amount:     {Colors.BOLD}${trade_record.amount:.2f}{Colors.END}")
    print(f"{Colors.CYAN}⏱️  Expiry:     {Colors.BOLD}{trade_record.expiry} minute(s){Colors.END}")
    print(f"{Colors.CYAN}🕐 Time:       {Colors.BOLD}{trade_record.timestamp}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")


def print_trade_outcome(trade_record: TradeRecord):
    """Print beautiful trade outcome output"""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.YELLOW}📊 TRADE RESULT{Colors.END}")
    print(f"{Colors.BOLD}{Colors.YELLOW}{'='*60}{Colors.END}")
    print(f"{Colors.CYAN}📝 Order ID:   {trade_record.trade_id}{Colors.END}")
    print(f"{Colors.CYAN}🎯 Asset:      {trade_record.asset}{Colors.END}")

    if trade_record.direction.upper() == "CALL":
        print(f"{Colors.CYAN}📈 Direction:  {Colors.GREEN}{trade_record.direction.upper()}{Colors.END}")
    else:
        print(f"{Colors.CYAN}📉 Direction:  {Colors.RED}{trade_record.direction.upper()}{Colors.END}")

    if trade_record.profit_loss > 0:
        outcome_emoji = "🎉 WIN"
        outcome_color = Colors.GREEN
    elif trade_record.profit_loss < 0:
        outcome_emoji = "💸 LOSS"
        outcome_color = Colors.RED
    else:
        outcome_emoji = "🤝 BREAKEVEN"
        outcome_color = Colors.YELLOW

    print(f"{Colors.CYAN}🎲 Outcome:    {outcome_color}{Colors.BOLD}{outcome_emoji}{Colors.END}")

    if trade_record.profit_loss > 0:
        pl_display = f"+${trade_record.profit_loss:.2f}"
        pl_color   = Colors.GREEN
    elif trade_record.profit_loss < 0:
        pl_display = f"-${abs(trade_record.profit_loss):.2f}"
        pl_color   = Colors.RED
    else:
        pl_display = "$0.00"
        pl_color   = Colors.YELLOW

    print(f"{Colors.CYAN}💵 P&L:        {pl_color}{Colors.BOLD}{pl_display}{Colors.END}")

    if trade_record.profit_loss != 0:
        bar_length = min(30, int(abs(trade_record.profit_loss) * 2))
        if trade_record.profit_loss > 0:
            bar = f"{Colors.GREEN}{'█' * bar_length}{Colors.END}"
            print(f"{Colors.CYAN}📈 Profit:     {bar} {pl_display}{Colors.END}")
        else:
            bar = f"{Colors.RED}{'█' * bar_length}{Colors.END}"
            print(f"{Colors.CYAN}📉 Loss:       {bar} {pl_display}{Colors.END}")

    print(f"{Colors.BOLD}{Colors.YELLOW}{'='*60}{Colors.END}\n")


def is_current_seconds_between_zero_and_two(timestamp):
    """
    Check if the seconds portion of a timestamp is between 0 and 29 (inclusive).

    Args:
        timestamp: Unix timestamp in milliseconds (like 1775996973735)

    Returns:
        bool: True if seconds are 0–29, False otherwise
    """
    dt = datetime.fromtimestamp(timestamp / 1000)
    return 0 <= dt.second <= 29