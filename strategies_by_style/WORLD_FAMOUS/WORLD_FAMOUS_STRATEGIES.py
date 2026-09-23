"""
WORLD'S BEST TRADING STRATEGIES - COMPREHENSIVE COLLECTION
Testing on: GOLD, SILVER, BTC, ETH

This module implements proven strategies from around the world:
1. Turtle Trading (Richard Dennis, USA)
2. Mean Reversion (Larry Connors, USA)
3. Ichimoku Cloud (Japan)
4. Donchian Breakout (Richard Donchian, USA)
5. Keltner Channel (Chester Keltner, USA)
6. Bollinger Band Squeeze (John Bollinger, USA)
7. ADX + Parabolic SAR (J. Welles Wilder, USA)
8. Williams %R (Larry Williams, USA)
9. Stochastic + MACD (George Lane, USA)
10. RSI Divergence (Andrew Cardwell, USA)
11. Moving Average Ribbon (Various, Japan)
12. Price Action Breakout (Al Brooks, USA)
13. Wyckoff Method (Richard Wyckoff, USA)
14. Elliott Wave Trading (Ralph Elliott, USA)
15. Fibonacci + EMA (Leonardo Fibonacci, Italy)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict


# ============================================================================
# STRATEGY 1: TURTLE TRADING (Richard Dennis - Chicago)
# ============================================================================

def strategy_turtle_trading_world_famous(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    Turtle Trading System - Richard Dennis & William Eckhardt
    Origin: Chicago, USA (1983)
    
    One of the most famous trading systems in history.
    Turned $1,600 into $100+ million.
    
    Rules:
    - Entry: 20-day breakout (new high/low)
    - Exit: 10-day opposite breakout
    - Position sizing: 2% risk per trade
    - Pyramid: Add positions on 0.5 ATR moves
    
    Best for: Trending markets, commodities
    """
    default_params = {
        'entry_breakout': 20,
        'exit_breakout': 10,
        'atr_period': 20,
    }
    if params:
        default_params.update(params)
    
    signals = pd.Series(0, index=df.index)
    
    try:
        # Calculate breakout levels
        high_20 = df['high'].rolling(default_params['entry_breakout']).max()
        low_20 = df['low'].rolling(default_params['entry_breakout']).min()
        
        high_10 = df['high'].rolling(default_params['exit_breakout']).max()
        low_10 = df['low'].rolling(default_params['exit_breakout']).min()
        
        # Entry signals
        long_entry = df['close'] > high_20.shift(1)
        short_entry = df['close'] < low_20.shift(1)
        
        # Exit signals
        long_exit = df['close'] < low_10.shift(1)
        short_exit = df['close'] > high_10.shift(1)
        
        signals[long_entry] = 1
        signals[short_entry] = -1
        signals[long_exit & (signals.shift(1) == 1)] = 0
        signals[short_exit & (signals.shift(1) == -1)] = 0
        
        signals = signals.replace(0, np.nan).ffill().fillna(0)
        
    except Exception as e:
        print(f"Error in Turtle Trading: {e}")
    
    return signals


# ============================================================================
# STRATEGY 2: CONNORS RSI MEAN REVERSION (Larry Connors - USA)
# ============================================================================

def strategy_connors_rsi_mean_reversion(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    Connors RSI Mean Reversion
    Origin: Larry Connors, USA
    
    Combines RSI, streak RSI, and magnitude RSI
    Excellent for mean reversion in liquid markets
    
    Best for: Stocks, indices, crypto with high volume
    """
    default_params = {
        'rsi_period': 2,
        'oversold': 10,
        'overbought': 90,
        'ema_trend': 200,
    }
    if params:
        default_params.update(params)
    
    signals = pd.Series(0, index=df.index)
    
    try:
        # Short-term RSI(2)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=default_params['rsi_period']).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=default_params['rsi_period']).mean()
        rs = gain / loss
        rsi2 = 100 - (100 / (1 + rs))
        
        # Trend filter
        if 'EMA_200' in df.columns:
            uptrend = df['close'] > df['EMA_200']
            downtrend = df['close'] < df['EMA_200']
        else:
            ema_200 = df['close'].ewm(span=200).mean()
            uptrend = df['close'] > ema_200
            downtrend = df['close'] < ema_200
        
        # Entry signals
        long_signal = (rsi2 < default_params['oversold']) & uptrend
        short_signal = (rsi2 > default_params['overbought']) & downtrend
        
        # Exit: RSI returns to middle
        exit_long = rsi2 > 50
        exit_short = rsi2 < 50
        
        signals[long_signal] = 1
        signals[short_signal] = -1
        signals[exit_long & (signals.shift(1) == 1)] = 0
        signals[exit_short & (signals.shift(1) == -1)] = 0
        
        signals = signals.replace(0, np.nan).ffill().fillna(0)
        
    except Exception as e:
        print(f"Error in Connors RSI: {e}")
    
    return signals


# ============================================================================
# STRATEGY 3: ICHIMOKU CLOUD (Japan)
# ============================================================================

def strategy_ichimoku_cloud_japanese(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    Ichimoku Kinko Hyo (Ichimoku Cloud)
    Origin: Goichi Hosoda, Japan (1960s)
    
    Complete trading system in one indicator
    Popular in Asia, now worldwide
    
    Best for: Trending markets, forex, crypto
    """
    default_params = {
        'tenkan': 9,
        'kijun': 26,
        'senkou_b': 52,
    }
    if params:
        default_params.update(params)
    
    signals = pd.Series(0, index=df.index)
    
    try:
        # Tenkan-sen (Conversion Line)
        high_tenkan = df['high'].rolling(default_params['tenkan']).max()
        low_tenkan = df['low'].rolling(default_params['tenkan']).min()
        tenkan = (high_tenkan + low_tenkan) / 2
        
        # Kijun-sen (Base Line)
        high_kijun = df['high'].rolling(default_params['kijun']).max()
        low_kijun = df['low'].rolling(default_params['kijun']).min()
        kijun = (high_kijun + low_kijun) / 2
        
        # Senkou Span A (Leading Span A)
        senkou_a = ((tenkan + kijun) / 2).shift(default_params['kijun'])
        
        # Senkou Span B (Leading Span B)
        high_senkou = df['high'].rolling(default_params['senkou_b']).max()
        low_senkou = df['low'].rolling(default_params['senkou_b']).min()
        senkou_b = ((high_senkou + low_senkou) / 2).shift(default_params['kijun'])
        
        # Entry signals
        # Long: Tenkan crosses above Kijun AND price above cloud
        tk_cross_up = (tenkan > kijun) & (tenkan.shift(1) <= kijun.shift(1))
        above_cloud = (df['close'] > senkou_a) & (df['close'] > senkou_b)
        
        # Short: Tenkan crosses below Kijun AND price below cloud
        tk_cross_down = (tenkan < kijun) & (tenkan.shift(1) >= kijun.shift(1))
        below_cloud = (df['close'] < senkou_a) & (df['close'] < senkou_b)
        
        signals[tk_cross_up & above_cloud] = 1
        signals[tk_cross_down & below_cloud] = -1
        
        # Exit on opposite cross
        signals[tk_cross_down & (signals.shift(1) == 1)] = 0
        signals[tk_cross_up & (signals.shift(1) == -1)] = 0
        
        signals = signals.replace(0, np.nan).ffill().fillna(0)
        
    except Exception as e:
        print(f"Error in Ichimoku: {e}")
    
    return signals


# ============================================================================
# STRATEGY 4: BOLLINGER BAND SQUEEZE (John Bollinger - USA)
# ============================================================================

def strategy_bollinger_squeeze_volatility_breakout(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    Bollinger Band Squeeze Strategy
    Origin: John Bollinger, USA
    
    Identifies low volatility periods followed by breakouts
    "The squeeze" = bands narrow = big move coming
    
    Best for: All markets, especially volatile assets
    """
    default_params = {
        'bb_period': 20,
        'bb_std': 2,
        'kc_period': 20,
        'kc_mult': 1.5,
    }
    if params:
        default_params.update(params)
    
    signals = pd.Series(0, index=df.index)
    
    try:
        # Bollinger Bands
        if 'BB_middle' in df.columns:
            bb_middle = df['BB_middle']
            bb_upper = df['BB_upper']
            bb_lower = df['BB_lower']
        else:
            bb_middle = df['close'].rolling(default_params['bb_period']).mean()
            bb_std = df['close'].rolling(default_params['bb_period']).std()
            bb_upper = bb_middle + (bb_std * default_params['bb_std'])
            bb_lower = bb_middle - (bb_std * default_params['bb_std'])
        
        # Keltner Channels
        if 'ATR' in df.columns:
            atr = df['ATR']
        else:
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = ranges.max(axis=1)
            atr = true_range.rolling(14).mean()
        
        kc_middle = df['close'].rolling(default_params['kc_period']).mean()
        kc_upper = kc_middle + (atr * default_params['kc_mult'])
        kc_lower = kc_middle - (atr * default_params['kc_mult'])
        
        # Squeeze: BB inside KC
        squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)
        squeeze_off = (bb_upper >= kc_upper) | (bb_lower <= kc_lower)
        
        # Breakout direction
        momentum = df['close'] - df['close'].rolling(default_params['bb_period']).mean()
        
        # Entry: Squeeze just released
        squeeze_release = squeeze_on.shift(1) & squeeze_off
        
        long_signal = squeeze_release & (momentum > 0)
        short_signal = squeeze_release & (momentum < 0)
        
        signals[long_signal] = 1
        signals[short_signal] = -1
        
        # Exit: Opposite signal or momentum reversal
        exit_long = (momentum < 0) & (momentum.shift(1) > 0)
        exit_short = (momentum > 0) & (momentum.shift(1) < 0)
        
        signals[exit_long & (signals.shift(1) == 1)] = 0
        signals[exit_short & (signals.shift(1) == -1)] = 0
        
        signals = signals.replace(0, np.nan).ffill().fillna(0)
        
    except Exception as e:
        print(f"Error in Bollinger Squeeze: {e}")
    
    return signals


# ============================================================================
# STRATEGY 5: SUPERTREND (India)
# ============================================================================

def strategy_supertrend_india(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """
    SuperTrend Indicator
    Origin: India
    
    Popular in Indian markets, now global
    ATR-based trailing stop
    
    Best for: Trending markets, intraday trading
    """
    default_params = {
        'atr_period': 10,
        'multiplier': 3,
    }
    if params:
        default_params.update(params)
    
    signals = pd.Series(0, index=df.index)
    
    try:
        # Calculate ATR
        if 'ATR' in df.columns:
            atr = df['ATR']
        else:
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = ranges.max(axis=1)
            atr = true_range.rolling(default_params['atr_period']).mean()
        
        # Basic Upper and Lower Bands
        hl2 = (df['high'] + df['low']) / 2
        basic_upper = hl2 + (default_params['multiplier'] * atr)
        basic_lower = hl2 - (default_params['multiplier'] * atr)
        
        # Calculate Final Bands
        final_upper = basic_upper.copy()
        final_lower = basic_lower.copy()
        
        for i in range(1, len(df)):
            # Upper band
            if basic_upper.iloc[i] < final_upper.iloc[i-1] or df['close'].iloc[i-1] > final_upper.iloc[i-1]:
                final_upper.iloc[i] = basic_upper.iloc[i]
            else:
                final_upper.iloc[i] = final_upper.iloc[i-1]
            
            # Lower band
            if basic_lower.iloc[i] > final_lower.iloc[i-1] or df['close'].iloc[i-1] < final_lower.iloc[i-1]:
                final_lower.iloc[i] = basic_lower.iloc[i]
            else:
                final_lower.iloc[i] = final_lower.iloc[i-1]
        
        # SuperTrend
        supertrend = pd.Series(0.0, index=df.index)
        for i in range(1, len(df)):
            if supertrend.iloc[i-1] == final_upper.iloc[i-1]:
                supertrend.iloc[i] = final_lower.iloc[i] if df['close'].iloc[i] <= final_upper.iloc[i] else final_upper.iloc[i]
            else:
                supertrend.iloc[i] = final_upper.iloc[i] if df['close'].iloc[i] >= final_lower.iloc[i] else final_lower.iloc[i]
        
        # Signals
        long_signal = df['close'] > supertrend
        short_signal = df['close'] < supertrend
        
        signals[long_signal] = 1
        signals[short_signal] = -1
        
    except Exception as e:
        print(f"Error in SuperTrend: {e}")
    
    return signals


# Add more strategies...
# (Continue with 10 more world-famous strategies)


if __name__ == "__main__":
    """
    WORLD'S BEST STRATEGIES COLLECTION
    
    Implemented:
    1. ✅ Turtle Trading (USA - Richard Dennis)
    2. ✅ Connors RSI (USA - Larry Connors)
    3. ✅ Ichimoku Cloud (Japan - Goichi Hosoda)
    4. ✅ Bollinger Squeeze (USA - John Bollinger)
    5. ✅ SuperTrend (India)
    
    Coming:
    6. Keltner Channel Breakout
    7. ADX + Parabolic SAR
    8. Williams %R
    9. Stochastic + MACD
    10. RSI Divergence
    11. Moving Average Ribbon
    12. Price Action Breakout
    13. Wyckoff Method
    14. Elliott Wave
    15. Fibonacci Retracement
    
    These will be tested on:
    - GOLD (GC=F, XAU/USD)
    - SILVER (SI=F, XAG/USD)
    - BTC (BTC-USD)
    - ETH (ETH-USD)
    """
    pass
