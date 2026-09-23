"""
Advanced Strategy Testing System
- Multi-timeframe backtesting
- Strategy combination analysis
- Confluence-based signals
"""

import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
import json
from itertools import combinations
from datetime import datetime
import importlib.util


class MultiTimeframeBacktester:
    """Backtest strategies across multiple timeframes"""
    
    def __init__(self, initial_capital=10000, commission=0.001):
        self.initial_capital = initial_capital
        self.commission = commission
        
    def run(self, df, signals):
        """Run backtest with detailed metrics"""
        if len(signals) == 0 or signals.sum() == 0:
            return self._empty_results()
        
        position = signals.replace(0, np.nan).ffill().fillna(0)
        position_shifted = position.shift(1).fillna(0)
        
        market_returns = df['close'].pct_change()
        position_changes = position_shifted.diff().abs()
        commission_costs = position_changes * self.commission
        
        strategy_returns = (position_shifted * market_returns) - commission_costs
        cumulative_returns = (1 + strategy_returns).cumprod()
        
        total_return = cumulative_returns.iloc[-1] - 1
        
        if strategy_returns.std() > 0:
            sharpe = (strategy_returns.mean() / strategy_returns.std()) * np.sqrt(252)
        else:
            sharpe = 0
            
        rolling_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        
        wins = strategy_returns[strategy_returns > 0]
        losses = strategy_returns[strategy_returns < 0]
        win_rate = len(wins) / (len(wins) + len(losses)) if (len(wins) + len(losses)) > 0 else 0
        
        trades = position_changes[position_changes > 0].sum() / 2
        
        # Additional metrics
        if len(wins) > 0 and len(losses) > 0:
            avg_win = wins.mean()
            avg_loss = abs(losses.mean())
            profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) if avg_loss > 0 else 0
        else:
            profit_factor = 0
        
        return {
            'total_return': total_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'num_trades': int(trades),
            'profit_factor': profit_factor,
            'final_equity': self.initial_capital * (1 + total_return)
        }
    
    def _empty_results(self):
        return {
            'total_return': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'win_rate': 0,
            'num_trades': 0,
            'profit_factor': 0,
            'final_equity': self.initial_capital
        }


class StrategyCombiner:
    """Combine multiple strategies with confluence logic"""
    
    def __init__(self, mode='unanimous'):
        """
        mode options:
        - 'unanimous': All strategies must agree (AND logic)
        - 'majority': Majority must agree (>50%)
        - 'any': Any strategy signals (OR logic)
        - 'weighted': Weighted scoring based on individual performance
        """
        self.mode = mode
        
    def combine(self, signals_dict, weights=None):
        """
        Combine multiple strategy signals
        
        Args:
            signals_dict: {strategy_name: signal_series}
            weights: Optional dict of weights per strategy
            
        Returns:
            Combined signal series
        """
        if len(signals_dict) == 0:
            return pd.Series(0)
        
        # Stack all signals into DataFrame
        signals_df = pd.DataFrame(signals_dict)
        
        if self.mode == 'unanimous':
            # All must agree for long/short
            long_signals = (signals_df == 1).all(axis=1).astype(int)
            short_signals = (signals_df == -1).all(axis=1).astype(int) * -1
            combined = long_signals + short_signals
            
        elif self.mode == 'majority':
            # Majority voting
            vote_sum = signals_df.sum(axis=1)
            threshold = len(signals_dict) / 2
            combined = pd.Series(0, index=signals_df.index)
            combined[vote_sum > threshold] = 1
            combined[vote_sum < -threshold] = -1
            
        elif self.mode == 'any':
            # Any strategy signals
            long_signals = (signals_df == 1).any(axis=1).astype(int)
            short_signals = (signals_df == -1).any(axis=1).astype(int) * -1
            combined = long_signals + short_signals
            
        elif self.mode == 'weighted':
            if weights is None:
                weights = {k: 1 for k in signals_dict.keys()}
            
            weighted_sum = pd.Series(0.0, index=signals_df.index)
            for strategy, signal in signals_dict.items():
                weighted_sum += signal * weights.get(strategy, 1)
            
            # Threshold at 50% of max possible weight
            max_weight = sum(weights.values())
            threshold = max_weight * 0.5
            
            combined = pd.Series(0, index=signals_df.index)
            combined[weighted_sum > threshold] = 1
            combined[weighted_sum < -threshold] = -1
        
        return combined


def compute_indicators(df):
    """Compute all indicators"""
    df = df.copy()
    df.columns = df.columns.str.lower()
    
    # EMAs
    for period in [3, 5, 9, 10, 15, 20, 50, 200]:
        df[f'EMA_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
    
    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['ATR'] = true_range.rolling(14).mean()
    
    # ADX
    plus_dm = df['high'].diff()
    minus_dm = -df['low'].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    
    tr14 = true_range.rolling(14).sum()
    plus_di = 100 * (plus_dm.rolling(14).sum() / tr14)
    minus_di = 100 * (minus_dm.rolling(14).sum() / tr14)
    
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    df['ADX'] = dx.rolling(14).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # Bollinger Bands
    df['BB_middle'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['BB_upper'] = df['BB_middle'] + (bb_std * 2)
    df['BB_lower'] = df['BB_middle'] - (bb_std * 2)
    
    # VWAP (for intraday)
    if len(df) > 0:
        df['VWAP'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
    
    return df


def load_strategy(strategy_path):
    """Load strategy function from file"""
    spec = importlib.util.spec_from_file_location("strategy_module", strategy_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    for item_name in dir(module):
        item = getattr(module, item_name)
        if callable(item) and not item_name.startswith('_'):
            return item
    return None


def download_data(symbol, period='2y', interval='1d'):
    """Download data for specific timeframe"""
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if len(df) > 100:  # Minimum bars needed
            return df
    except:
        pass
    return None


def main():
    print("="*80)
    print("ADVANCED MULTI-TIMEFRAME & COMBINATION BACKTESTING")
    print("="*80)
    
    # Configuration
    test_assets = {
        'crypto': ['BTC-USD', 'ETH-USD', 'SOL-USD'],
        'forex': ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X']
    }
    
    # Multiple timeframes
    timeframes = {
        '5m': ('5d', '5m'),    # 5 days of 5-minute data
        '15m': ('15d', '15m'),  # 15 days of 15-minute data
        '1h': ('60d', '1h'),    # 60 days of hourly data
        '4h': ('180d', '4h'),   # 180 days of 4-hour data
        '1d': ('2y', '1d')      # 2 years of daily data
    }
    
    all_assets = test_assets['crypto'] + test_assets['forex']
    
    strategies_dir = Path('C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/generated_strategies')
    strategy_files = list(strategies_dir.glob('strategy_*.py'))[:10]  # Test top 10 first
    
    print(f"\nConfiguration:")
    print(f"  Strategies: {len(strategy_files)}")
    print(f"  Assets: {len(all_assets)}")
    print(f"  Timeframes: {list(timeframes.keys())}")
    print(f"  Total tests: {len(strategy_files) * len(all_assets) * len(timeframes)}")
    
    # Phase 1: Individual strategy testing across timeframes
    print("\n" + "="*80)
    print("PHASE 1: MULTI-TIMEFRAME TESTING")
    print("="*80)
    
    results_individual = []
    backtester = MultiTimeframeBacktester()
    
    for strategy_file in strategy_files:
        strategy_name = strategy_file.stem
        strategy_func = load_strategy(strategy_file)
        
        if strategy_func is None:
            continue
        
        for asset in all_assets:
            for tf_name, (period, interval) in timeframes.items():
                try:
                    df = download_data(asset, period, interval)
                    if df is None or len(df) < 100:
                        continue
                    
                    df = compute_indicators(df)
                    signals = strategy_func(df)
                    metrics = backtester.run(df, signals)
                    
                    results_individual.append({
                        'strategy': strategy_name,
                        'asset': asset,
                        'timeframe': tf_name,
                        'sharpe': metrics['sharpe_ratio'],
                        'return': metrics['total_return'],
                        'drawdown': metrics['max_drawdown'],
                        'win_rate': metrics['win_rate'],
                        'trades': metrics['num_trades'],
                        'profit_factor': metrics['profit_factor']
                    })
                    
                    print(f"  ✓ {strategy_name[:30]:30} | {asset:10} | {tf_name:4} | Sharpe: {metrics['sharpe_ratio']:6.2f}")
                    
                except Exception as e:
                    pass
    
    # Save individual results
    df_individual = pd.DataFrame(results_individual)
    df_individual.to_csv('C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/results_individual_multitf.csv', index=False)
    
    print(f"\n✓ Phase 1 complete: {len(results_individual)} tests")
    
    # Phase 2: Strategy Combinations
    print("\n" + "="*80)
    print("PHASE 2: STRATEGY COMBINATIONS")
    print("="*80)
    
    # Find top performing strategies
    top_strategies = df_individual.groupby('strategy')['sharpe'].mean().nlargest(5).index.tolist()
    
    print(f"\nTop 5 strategies for combination testing:")
    for i, strat in enumerate(top_strategies, 1):
        print(f"  {i}. {strat}")
    
    results_combinations = []
    combiner_modes = ['unanimous', 'majority', 'any']
    
    # Test all 2-strategy combinations
    for combo in combinations(top_strategies, 2):
        strat1_name, strat2_name = combo
        
        # Load both strategies
        strat1_file = strategies_dir / f"{strat1_name}.py"
        strat2_file = strategies_dir / f"{strat2_name}.py"
        
        strat1_func = load_strategy(strat1_file)
        strat2_func = load_strategy(strat2_file)
        
        if strat1_func is None or strat2_func is None:
            continue
        
        for asset in all_assets:
            for tf_name, (period, interval) in timeframes.items():
                try:
                    df = download_data(asset, period, interval)
                    if df is None or len(df) < 100:
                        continue
                    
                    df = compute_indicators(df)
                    
                    # Get signals from both strategies
                    signals1 = strat1_func(df)
                    signals2 = strat2_func(df)
                    
                    # Test different combination modes
                    for mode in combiner_modes:
                        combiner = StrategyCombiner(mode=mode)
                        combined_signals = combiner.combine({
                            strat1_name: signals1,
                            strat2_name: signals2
                        })
                        
                        metrics = backtester.run(df, combined_signals)
                        
                        results_combinations.append({
                            'strategy1': strat1_name,
                            'strategy2': strat2_name,
                            'combo_mode': mode,
                            'asset': asset,
                            'timeframe': tf_name,
                            'sharpe': metrics['sharpe_ratio'],
                            'return': metrics['total_return'],
                            'drawdown': metrics['max_drawdown'],
                            'win_rate': metrics['win_rate'],
                            'trades': metrics['num_trades'],
                            'profit_factor': metrics['profit_factor']
                        })
                        
                        if metrics['sharpe_ratio'] > 1.0:
                            print(f"  🔥 {strat1_name[:15]} + {strat2_name[:15]} | {mode:10} | {asset:10} | {tf_name:4} | Sharpe: {metrics['sharpe_ratio']:.2f}")
                
                except Exception as e:
                    pass
    
    # Save combination results
    df_combinations = pd.DataFrame(results_combinations)
    df_combinations.to_csv('C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/results_combinations.csv', index=False)
    
    print(f"\n✓ Phase 2 complete: {len(results_combinations)} combination tests")
    
    # Generate summary report
    print("\n" + "="*80)
    print("GENERATING SUMMARY REPORT")
    print("="*80)
    
    # Best individual strategies per timeframe
    best_by_tf = df_individual.loc[df_individual.groupby('timeframe')['sharpe'].idxmax()]
    
    # Best combinations
    best_combos = df_combinations.nlargest(10, 'sharpe')
    
    # Save summary
    with open('C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/ADVANCED_BACKTEST_SUMMARY.txt', 'w') as f:
        f.write("ADVANCED BACKTESTING RESULTS\n")
        f.write("="*80 + "\n\n")
        
        f.write("BEST STRATEGIES PER TIMEFRAME:\n")
        f.write("-"*80 + "\n")
        for _, row in best_by_tf.iterrows():
            f.write(f"{row['timeframe']:5} | {row['strategy']:40} | {row['asset']:10} | Sharpe: {row['sharpe']:.2f}\n")
        
        f.write("\n\nBEST STRATEGY COMBINATIONS:\n")
        f.write("-"*80 + "\n")
        for _, row in best_combos.iterrows():
            f.write(f"{row['strategy1'][:20]} + {row['strategy2'][:20]}\n")
            f.write(f"  Mode: {row['combo_mode']:10} | {row['asset']:10} | {row['timeframe']:4} | Sharpe: {row['sharpe']:.2f}\n")
    
    print("\n✓ Summary saved")
    print("\n" + "="*80)
    print("ALL PHASES COMPLETE")
    print("="*80)
    
    return df_individual, df_combinations


if __name__ == "__main__":
    df_individual, df_combinations = main()
