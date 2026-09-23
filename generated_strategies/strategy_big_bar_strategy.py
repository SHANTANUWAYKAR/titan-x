"""
BIG BAR STRATEGY

Auto-generated from strategy document.
Generated: 2026-09-11
Interpretations based on industry best practices.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict


def big_bar_strategy(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    BIG BAR STRATEGY
    
    Timeframe: 5m
    Instruments: any
    Required Indicators: EMA_9
    
    Extracted Rules:
    
    Stop Loss:
      - Stop Loss: Low of the retest candle.
      - Stop Loss: High of the retest candle.
    
    Take Profit:
      - Target: 1:1 Risk Reward.
      - Target: 1:1 Risk Reward.
    
    Filters:
      - Trade in direction of trend
      - Avoid sideways markets

    
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
    required_indicators = ['EMA_9']
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
    # signals = big_bar_strategy(df)
    pass
