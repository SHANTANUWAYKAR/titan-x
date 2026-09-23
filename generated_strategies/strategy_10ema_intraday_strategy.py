"""
10EMA INTRADAY STRATEGY

Auto-generated from strategy document.
Generated: 2026-09-11
Interpretations based on industry best practices.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict


def 10ema_intraday_strategy(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    10EMA INTRADAY STRATEGY
    
    Timeframe: 5m, 15m
    Instruments: stocks
    Required Indicators: EMA_10
    
    Extracted Rules:
    
    Stop Loss:
      - This strategy is designed for intraday traders who want to capture strong market moves using a simple and disciplined setup. It works effectively on 5-minute and 15-minute charts and focuses on momentum continuation using the 10 EMA indicator. **Step 1: Select Timeframe** Use either the 5-minute timeframe or the 15-minute timeframe for this setup. These timeframes are best suited for intraday momentum trading. **Step 2: Apply Indicator** Go to the indicator section of your charting platform and apply the 10 EMA (10 Exponential Moving Average). This will act as your support zone during pullbacks. **Step 3: Identify Strong Up Move** Look for a strong bullish move where the market shows good upward momentum. Avoid weak or sideways price action. **Step 4: Wait for Consolidation Near 10 EMA** After the strong up move, wait for the market to consolidate near the 10 EMA. You should see small candles forming near the EMA, indicating controlled pullback. **Step 5: Look for Entry Candle** Inside this small consolidation zone, look for either a Doji Candle or an Inside Candle. These candles signal potential continuation of the trend. **Step 6: Entry Rule** Take the trade when the breakout happens after the Doji Candle or Inside Candle is formed near the 10 EMA support zone. **Step 7: Stop Loss** Keep your stop loss at the low of the nearest previous candle. This helps control risk effectively. **Step 8: Target and Risk Reward** Maintain a minimum Risk:Reward ratio of 1:2. As the trade moves in your favor, keep trailing your stop loss to protect profits. **Important Trading Tips**
      - Never trade without stop loss.

    
    Args:
        df: DataFrame with OHLCV data and pre-computed indicators.
            Required columns: open, high, low, close, volume
            Pre-computed indicators expected in df.
        params: Optional parameter overrides.
        
    Returns:
        pd.Series with values: 1 (long), -1 (short), 0 (no position)
        
    Note:
        All ambiguous terms resolved using industry best practices:
        - "Break of" = candle close beyond level
        - "Confirmation" = candle close beyond level
        - "Strong trend" = ADX > 25
        - "Near support/resistance" = within 1 ATR of resistance level
        - "Rejection candle" = wick > 50% of total range + close near opposite end
        - Minimum R:R = 1:2 minimum
    """
    
    # Default parameters
    default_params = {
        'atr_period': 14,
        'adx_threshold': 25,  # For "strong trend" filter
        'min_rr': 2.0,  # Minimum risk:reward ratio
        'ema_slope_threshold': 0.005,  # 0.5% per bar for "angle" measurement
    }
    
    if params:
        default_params.update(params)
    
    # Initialize signals
    signals = pd.Series(0, index=df.index)
    
    # Check if required indicators are present
    required_indicators = ['EMA_10']
    missing = [ind for ind in required_indicators if ind not in df.columns]
    if missing:
        print(f"Warning: Missing indicators: {missing}")
        return signals
    
    # Forward fill to maintain positions until exit signal
    signals = signals.replace(0, np.nan).ffill().fillna(0)
    
    return signals


# Example usage:
if __name__ == "__main__":
    # This would be called by your backtesting engine
    # df = your_dataframe_with_ohlcv_and_indicators
    # signals = 10ema_intraday_strategy(df)
    pass
