"""
9_20EMA STRATEGY

Auto-generated from strategy document.
Generated: 2026-09-11
Interpretations based on industry best practices.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict


def 9_20ema_strategy(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    9_20EMA STRATEGY
    
    Timeframe: 5m, 15m
    Instruments: any
    Required Indicators: EMA_19, EMA_20, EMA_9
    
    Extracted Rules:
    
    Stop Loss:
      - Maintain Risk:Reward ratio of 1:3. 2Always use Stop Loss. 3Do not overtrade.
    
    Filters:
      - Trade in direction of trend

    
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
    required_indicators = ['EMA_19', 'EMA_20', 'EMA_9']
    missing = [ind for ind in required_indicators if ind not in df.columns]
    if missing:
        print(f"Warning: Missing indicators: {missing}")
        return signals
    
    # EMA-based entry logic
    # Using EMA_19 and EMA_20 from pre-computed indicators
    
    try:
        # Long entry: Fast EMA crosses above Slow EMA
        # CLARIFICATION: "crossover" = candle close confirms cross
        long_cross = (df['EMA_19'] > df['EMA_20']) & (df['EMA_19'].shift(1) <= df['EMA_20'].shift(1))
        
        # Short entry: Fast EMA crosses below Slow EMA
        short_cross = (df['EMA_19'] < df['EMA_20']) & (df['EMA_19'].shift(1) >= df['EMA_20'].shift(1))
        
        # Trend filter if ADX is available
        # CLARIFICATION: "strong trend" = ADX > 25
        if 'ADX' in df.columns:
            trend_filter = df['ADX'] > default_params['adx_threshold']
            long_cross = long_cross & trend_filter
            short_cross = short_cross & trend_filter
        
        # Apply signals
        signals[long_cross] = 1
        signals[short_cross] = -1
        
        # Exit logic: opposite crossover
        # CLARIFICATION: exit on candle close (no repainting)
        exit_long = short_cross
        exit_short = long_cross
        
        # Close positions on opposite signal
        current_position = signals.shift(1).fillna(0)
        signals[exit_long & (current_position == 1)] = 0
        signals[exit_short & (current_position == -1)] = 0
        
    except KeyError as e:
        print(f"Error: Missing expected indicator: {e}")
        return pd.Series(0, index=df.index)
    
    # Forward fill to maintain positions until exit signal
    signals = signals.replace(0, np.nan).ffill().fillna(0)
    
    return signals


# Example usage:
if __name__ == "__main__":
    # This would be called by your backtesting engine
    # df = your_dataframe_with_ohlcv_and_indicators
    # signals = 9_20ema_strategy(df)
    pass
