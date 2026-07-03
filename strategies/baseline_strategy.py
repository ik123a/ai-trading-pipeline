"""
Baseline Strategy for NautilusTrader
Implements SMA crossover as the simplest benchmark.
"""
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators.average.ma_factory import MovingAverageType
from nautilus_trader.indicators.average.simple_moving_average import SimpleMovingAverage


class BaselineStrategyConfig(StrategyConfig):
    """Configuration for baseline strategy."""
    instrument_id: str = "AAPL.SIM"
    bar_type: str = "AAPL.SIM-1-DAY-LAST-INTERNAL"
    short_window: int = 50
    long_window: int = 200
    trade_size: int = 100  # shares


class BaselineStrategy(Strategy):
    """Simple SMA crossover strategy for baseline metrics."""
    
    def __init__(self, config: BaselineStrategyConfig):
        super().__init__(config)
        
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.trade_size = config.trade_size
        
        # SMA indicators
        self.sma_short = SimpleMovingAverage(config.short_window)
        self.sma_long = SimpleMovingAverage(config.long_window)
        
        # Track last crossover signal
        self.last_signal = None  # 'buy' or 'sell'
        
    def on_start(self):
        """Subscribe to bar data when strategy starts."""
        self.subscribe_bars(self.bar_type)
        self.log.info(f"✅ Baseline strategy started: {self.instrument_id}")
        
    def on_bar(self, bar: Bar):
        """Process each bar and generate signals."""
        # Update indicators
        self.sma_short.update_raw(bar.close.as_double())
        self.sma_long.update_raw(bar.close.as_double())
        
        # Need both indicators initialized
        if not self.sma_short.initialized or not self.sma_long.initialized:
            return
        
        short_val = self.sma_short.value
        long_val = self.sma_long.value
        
        # Generate signals
        if short_val > long_val and self.last_signal != 'buy':
            self.log.info(f"🟢 BUY signal: SMA({self.sma_short.period})={short_val:.2f} > SMA({self.sma_long.period})={long_val:.2f}")
            self._enter_long()
            self.last_signal = 'buy'
            
        elif short_val < long_val and self.last_signal != 'sell':
            self.log.info(f"🔴 SELL signal: SMA({self.sma_short.period})={short_val:.2f} < SMA({self.sma_long.period})={long_val:.2f}")
            self._close_position()
            self.last_signal = 'sell'
    
    def _enter_long(self):
        """Submit a market order to go long."""
        order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(self.trade_size),
        )
        self.submit_order(order)
    
    def _close_position(self):
        """Close any existing position."""
        position = self.cache.position(self.instrument_id)
        if position and position.net_qty > 0:
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.SELL,
                quantity=Quantity.from_int(self.trade_size),
            )
            self.submit_order(order)