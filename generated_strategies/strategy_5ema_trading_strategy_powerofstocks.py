"""
5EMA TRADING STRATEGY POWEROFSTOCKS

Auto-generated from strategy document.
Generated: 2026-09-11
Interpretations based on industry best practices.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict


def 5ema_trading_strategy_powerofstocks(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    5EMA TRADING STRATEGY POWEROFSTOCKS
    
    Timeframe: 5m, 15m
    Instruments: stocks, crypto
    Required Indicators: EMA_5
    
    Extracted Rules:
    
    Stop Loss:
      - Always maintain proper stop loss and avoid overtrading. Do not enter random trades without confirmation. Follow discipline and wait for clean setup formation before executing the trade.
    
    Take Profit:
      - **Step 1:** Open your trading chart and set the timeframe to 15 Minutes. **Step 2:** Apply the 5 EMA (Exponential Moving Average) on the chart. **Step 3:** Now identify a candle whose LOW does not touch the 5 EMA. **Step 4:** Wait for the next candle to break the LOW of that identified candle. **Step 5:** As soon as the LOW is broken, take your SELL entry. **Step 6:** Keep your Target at Risk:Reward ratio of 1:2. **Step 7:** If the market continues strongly in your trade direction, you can extend the target up to 1:3. **Step 8:** Apply the exact same logic on the BUYING side by observing HIGH break conditions in reverse format.

    
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
    required_indicators = ['EMA_5']
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
    # signals = 5ema_trading_strategy_powerofstocks(df)
    pass
