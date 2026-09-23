"""
Comprehensive Strategy Backtesting & Optimization
Backtest all 45 generated strategies on major crypto and forex pairs
"""

import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
import json
from datetime import datetime, timedelta
import importlib.util
import sys


class SimpleBacktester:
    """Simple backtesting engine for strategy evaluation"""
    
    def __init__(self, initial_capital=10000, commission=0.001):
        self.initial_capital = initial_capital
        self.commission = commission
        
    def run(self, df, signals):
        """
        Run backtest on signals
        
        Args:
            df: DataFrame with OHLCV data
            signals: Series with 1 (long), -1 (short), 0 (no position)
            
        Returns:
            dict with performance metrics
        """
        if len(signals) == 0 or signals.sum() == 0:
            return self._empty_results()
        
        # Forward fill signals to maintain positions
        position = signals.replace(0, np.nan).ffill().fillna(0)
        
        # Calculate returns (entry at next bar's open)
        position_shifted = position.shift(1).fillna(0)
        
        # Market returns
        market_returns = df['close'].pct_change()
        
        # Strategy returns
        position_changes = position_shifted.diff().abs()
        commission_costs = position_changes * self.commission
        
        strategy_returns = (position_shifted * market_returns) - commission_costs
        
        # Cumulative returns
        cumulative_returns = (1 + strategy_returns).cumprod()
        
        # Calculate metrics
        total_return = cumulative_returns.iloc[-1] - 1
        
        # Sharpe ratio (annualized)
        if strategy_returns.std() > 0:
            sharpe = (strategy_returns.mean() / strategy_returns.std()) * np.sqrt(252)
        else:
            sharpe = 0
            
        # Max drawdown
        rolling_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        
        # Win rate
        wins = strategy_returns[strategy_returns > 0]
        losses = strategy_returns[strategy_returns < 0]
        win_rate = len(wins) / (len(wins) + len(losses)) if (len(wins) + len(losses)) > 0 else 0
        
        # Number of trades
        trades = position_changes[position_changes > 0].sum() / 2
        
        return {
            'total_return': total_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'num_trades': int(trades),
            'avg_return_per_trade': total_return / trades if trades > 0 else 0,
            'final_equity': self.initial_capital * (1 + total_return)
        }
    
    def _empty_results(self):
        """Return empty results for strategies that produce no signals"""
        return {
            'total_return': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'win_rate': 0,
            'num_trades': 0,
            'avg_return_per_trade': 0,
            'final_equity': self.initial_capital
        }


def compute_indicators(df):
    """Compute all indicators needed by strategies"""
    df = df.copy()
    
    # Rename columns to lowercase
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
    
    return df


def download_data(symbol, period='2y', interval='1d'):
    """Download historical data"""
    try:
        print(f"  Downloading {symbol}...", end='')
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if len(df) > 0:
            print(f" ✓ ({len(df)} bars)")
            return df
        else:
            print(f" ✗ (no data)")
            return None
    except Exception as e:
        print(f" ✗ ({str(e)})")
        return None


def load_strategy(strategy_path):
    """Dynamically load a strategy module"""
    spec = importlib.util.spec_from_file_location("strategy_module", strategy_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    # Find the strategy function (first function that takes df as parameter)
    for item_name in dir(module):
        item = getattr(module, item_name)
        if callable(item) and not item_name.startswith('_'):
            return item
    
    return None


def main():
    """Main backtesting workflow"""
    
    print("="*80)
    print("COMPREHENSIVE STRATEGY BACKTESTING")
    print("="*80)
    
    # Configuration
    test_assets = {
        'crypto': ['BTC-USD', 'ETH-USD', 'BNB-USD', 'XRP-USD', 'SOL-USD'],
        'forex': ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'AUDUSD=X', 'USDCHF=X']
    }
    
    all_assets = test_assets['crypto'] + test_assets['forex']
    
    strategies_dir = Path('C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/generated_strategies')
    strategy_files = list(strategies_dir.glob('strategy_*.py'))
    
    print(f"\nFound {len(strategy_files)} strategy files")
    print(f"Testing on {len(all_assets)} assets")
    print(f"Total combinations: {len(strategy_files) * len(all_assets)}")
    
    # Download all data first
    print("\n" + "="*80)
    print("PHASE 1: DATA DOWNLOAD")
    print("="*80)
    
    market_data = {}
    for asset in all_assets:
        df = download_data(asset)
        if df is not None and len(df) > 200:  # Need enough data
            df_with_indicators = compute_indicators(df)
            market_data[asset] = df_with_indicators
    
    print(f"\n✓ Downloaded {len(market_data)} assets successfully")
    
    # Run backtests
    print("\n" + "="*80)
    print("PHASE 2: BACKTESTING")
    print("="*80)
    
    backtester = SimpleBacktester(initial_capital=10000, commission=0.001)
    results = []
    
    total_tests = len(strategy_files) * len(market_data)
    current_test = 0
    
    for strategy_file in strategy_files:
        strategy_name = strategy_file.stem
        
        try:
            strategy_func = load_strategy(strategy_file)
            
            if strategy_func is None:
                continue
            
            for asset, df in market_data.items():
                current_test += 1
                
                if current_test % 50 == 0:
                    print(f"Progress: {current_test}/{total_tests} tests completed...")
                
                try:
                    # Generate signals
                    signals = strategy_func(df)
                    
                    # Run backtest
                    metrics = backtester.run(df, signals)
                    
                    # Store results
                    results.append({
                        'strategy': strategy_name,
                        'asset': asset,
                        'sharpe_ratio': metrics['sharpe_ratio'],
                        'total_return': metrics['total_return'],
                        'max_drawdown': metrics['max_drawdown'],
                        'win_rate': metrics['win_rate'],
                        'num_trades': metrics['num_trades'],
                        'final_equity': metrics['final_equity']
                    })
                    
                except Exception as e:
                    # Silent fail for individual strategy-asset combinations
                    pass
        
        except Exception as e:
            print(f"✗ Error loading {strategy_name}: {e}")
            continue
    
    print(f"\n✓ Completed {len(results)} successful backtests")
    
    # Save results
    results_df = pd.DataFrame(results)
    results_path = 'C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/backtest_results_phase1.csv'
    results_df.to_csv(results_path, index=False)
    
    print(f"\n✓ Results saved to: {results_path}")
    
    # Print summary
    print("\n" + "="*80)
    print("PHASE 1 RESULTS SUMMARY")
    print("="*80)
    
    # Top strategies by average Sharpe across all assets
    strategy_performance = results_df.groupby('strategy').agg({
        'sharpe_ratio': ['mean', 'max', 'count'],
        'total_return': 'mean',
        'num_trades': 'mean'
    }).round(3)
    
    strategy_performance.columns = ['_'.join(col).strip() for col in strategy_performance.columns.values]
    strategy_performance = strategy_performance.sort_values('sharpe_ratio_mean', ascending=False)
    
    print("\nTop 10 Strategies by Average Sharpe Ratio:")
    print(strategy_performance.head(10))
    
    # Save summary
    summary_path = 'C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/backtest_summary_phase1.txt'
    with open(summary_path, 'w') as f:
        f.write("PHASE 1 BACKTEST RESULTS SUMMARY\n")
        f.write("="*80 + "\n\n")
        f.write(f"Total Tests: {len(results)}\n")
        f.write(f"Strategies Tested: {len(strategy_files)}\n")
        f.write(f"Assets Tested: {len(market_data)}\n\n")
        f.write("Top 10 Strategies:\n")
        f.write(str(strategy_performance.head(10)))
    
    print(f"\n✓ Summary saved to: {summary_path}")
    print("\n" + "="*80)
    print("PHASE 1 COMPLETE")
    print("="*80)
    
    return results_df


if __name__ == "__main__":
    results = main()
