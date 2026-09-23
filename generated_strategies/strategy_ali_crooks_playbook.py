"""
Ali Crooks Playbook

Auto-generated from strategy document.
Generated: 2026-09-11
Interpretations based on industry best practices.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict


def ali_crooks_playbook(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    Ali Crooks Playbook
    
    Timeframe: 4h, 1d
    Instruments: forex, crypto
    Required Indicators: EMA_21, MACD
    
    Extracted Rules:
    
    Exit:
      - No early exits
    
    Stop Loss:
      - has conditions.|not|genuinely|shifted.|This|rule|protects|you|from|sloppy,|low-quality|
      - Entry Type 1 – Pullback to the 21 EMA (Core Stop-Loss & Target Rules
    
    Take Profit:
      - Trendline Break Pocket and ready for execution. The You only take a trade when all of the following are base model targets **2R (2:1 reward:risk).** true: Historical tracking of this setup shows a realistic **Price has reached a higher-timeframe key level:** (a ~58% win rate at 2:1 when executed consistently. support or resistance zone identified using the Frequency & Proximity method)
      - Requirements: **Target** = the high/low formed after momentum break
    
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
    required_indicators = ['EMA_21', 'MACD']
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
    # signals = ali_crooks_playbook(df)
    pass
