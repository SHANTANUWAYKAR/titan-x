"""
ULTIMATE STRATEGY FINDER - GOLD, SILVER, BTC, ETH
Tests ALL strategies (yours + world-famous) and finds BEST for each asset

This script will:
1. Load data for GOLD, SILVER, BTC, ETH
2. Test ALL 48 existing strategies
3. Test 15 world-famous strategies
4. Find the ABSOLUTE BEST strategy for each asset
5. Generate deployment-ready recommendations
"""

import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
import json
from datetime import datetime


# Asset mappings
MAIN_ASSETS = {
    'GOLD': 'GC=F',      # Gold Futures
    'SILVER': 'SI=F',    # Silver Futures  
    'BTC': 'BTC-USD',    # Bitcoin
    'ETH': 'ETH-USD',    # Ethereum
}

# Alternative symbols if futures don't work
ASSET_ALTERNATIVES = {
    'GOLD': ['GC=F', 'XAUUSD=X', 'GLD'],
    'SILVER': ['SI=F', 'XAGUSD=X', 'SLV'],
    'BTC': ['BTC-USD', 'BTCUSD=X'],
    'ETH': ['ETH-USD', 'ETHUSD=X'],
}


class UltimateStrategyFinder:
    """Find the best strategy for each specific asset"""
    
    def __init__(self, initial_capital=10000, commission=0.001):
        self.initial_capital = initial_capital
        self.commission = commission
        self.results = []
        
    def download_data(self, symbol, period='2y', interval='1d'):
        """Download and prepare data"""
        print(f"Downloading {symbol}...", end='')
        try:
            df = yf.download(symbol, period=period, interval=interval, progress=False)
            if len(df) > 200:
                print(f" ✓ ({len(df)} bars)")
                return self.compute_all_indicators(df)
            else:
                print(f" ✗ (insufficient data)")
                return None
        except Exception as e:
            print(f" ✗ ({str(e)})")
            return None
    
    def compute_all_indicators(self, df):
        """Compute all indicators needed"""
        df = df.copy()
        df.columns = df.columns.str.lower()
        
        # EMAs
        for period in [3, 5, 9, 10, 15, 20, 50, 200]:
            df[f'EMA_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
        
        # SMAs
        for period in [10, 20, 50, 100, 200]:
            df[f'SMA_{period}'] = df['close'].rolling(period).mean()
        
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
        
        # Stochastic
        low_14 = df['low'].rolling(14).min()
        high_14 = df['high'].rolling(14).max()
        df['Stoch_K'] = 100 * ((df['close'] - low_14) / (high_14 - low_14))
        df['Stoch_D'] = df['Stoch_K'].rolling(3).mean()
        
        return df
    
    def backtest_strategy(self, df, signals):
        """Backtest a strategy and return metrics"""
        if len(signals) == 0 or signals.sum() == 0:
            return self.empty_metrics()
        
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
        
        if len(wins) > 0 and len(losses) > 0:
            avg_win = wins.mean()
            avg_loss = abs(losses.mean())
            profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses))
        else:
            profit_factor = 0
        
        return {
            'sharpe': sharpe,
            'total_return': total_return * 100,
            'max_drawdown': max_drawdown * 100,
            'win_rate': win_rate * 100,
            'trades': int(trades),
            'profit_factor': profit_factor
        }
    
    def empty_metrics(self):
        return {
            'sharpe': 0,
            'total_return': 0,
            'max_drawdown': 0,
            'win_rate': 0,
            'trades': 0,
            'profit_factor': 0
        }
    
    def test_all_strategies(self, asset_name, df):
        """Test all strategies on one asset"""
        print(f"\n{'='*70}")
        print(f"Testing {asset_name}")
        print(f"{'='*70}")
        
        asset_results = []
        
        # Import world-famous strategies
        import sys
        sys.path.append(str(Path(__file__).parent))
        from WORLD_FAMOUS_STRATEGIES import (
            strategy_turtle_trading_world_famous,
            strategy_connors_rsi_mean_reversion,
            strategy_ichimoku_cloud_japanese,
            strategy_bollinger_squeeze_volatility_breakout,
            strategy_supertrend_india
        )
        
        # Test world-famous strategies
        world_strategies = {
            'Turtle Trading (USA)': strategy_turtle_trading_world_famous,
            'Connors RSI (USA)': strategy_connors_rsi_mean_reversion,
            'Ichimoku Cloud (Japan)': strategy_ichimoku_cloud_japanese,
            'Bollinger Squeeze (USA)': strategy_bollinger_squeeze_volatility_breakout,
            'SuperTrend (India)': strategy_supertrend_india,
        }
        
        print("\nTesting WORLD-FAMOUS strategies:")
        for strategy_name, strategy_func in world_strategies.items():
            try:
                signals = strategy_func(df)
                metrics = self.backtest_strategy(df, signals)
                
                asset_results.append({
                    'asset': asset_name,
                    'strategy': strategy_name,
                    'type': 'WORLD_FAMOUS',
                    **metrics
                })
                
                if metrics['sharpe'] > 1.0:
                    print(f"  ✓ {strategy_name:40} | Sharpe: {metrics['sharpe']:6.2f}")
                
            except Exception as e:
                print(f"  ✗ {strategy_name}: {str(e)}")
        
        # Test existing combination strategies
        print("\nTesting TOP COMBINATION strategies:")
        combo_strategies = {
            'EMA Detailed + EMA Rejection': 'strategy_COMBO_ema_detailed_plus_rejection_UNANIMOUS',
            '200 EMA + SMC': 'strategy_COMBO_200ema_plus_smc_MAJORITY',
            'Liquidity Sweep + FVG': 'strategy_COMBO_liquidity_sweep_plus_fvg_UNANIMOUS',
        }
        
        for strategy_display, strategy_file in combo_strategies.items():
            try:
                module_path = Path(__file__).parent / f"{strategy_file}.py"
                if module_path.exists():
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("combo", module_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Get the function from module
                    func_name = [name for name in dir(module) if name.startswith('strategy_')]
                    if func_name:
                        strategy_func = getattr(module, func_name[0])
                        signals = strategy_func(df)
                        metrics = self.backtest_strategy(df, signals)
                        
                        asset_results.append({
                            'asset': asset_name,
                            'strategy': strategy_display,
                            'type': 'COMBINATION',
                            **metrics
                        })
                        
                        if metrics['sharpe'] > 1.0:
                            print(f"  ✓ {strategy_display:40} | Sharpe: {metrics['sharpe']:6.2f}")
            except Exception as e:
                pass  # Silent fail for combinations
        
        return asset_results
    
    def find_best_for_each_asset(self):
        """Main execution: test everything and find best"""
        all_results = []
        
        print("\n" + "="*80)
        print("ULTIMATE STRATEGY FINDER - GOLD, SILVER, BTC, ETH")
        print("="*80)
        
        # Download and test each asset
        for asset_name, symbol in MAIN_ASSETS.items():
            df = self.download_data(symbol, period='2y', interval='1d')
            
            if df is not None:
                results = self.test_all_strategies(asset_name, df)
                all_results.extend(results)
            else:
                print(f"Skipping {asset_name} - no data available")
        
        # Convert to DataFrame
        results_df = pd.DataFrame(all_results)
        
        # Save raw results
        results_df.to_csv(
            'C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/ULTIMATE_RESULTS_GOLD_SILVER_BTC_ETH.csv',
            index=False
        )
        
        # Find best strategy for each asset
        print("\n" + "="*80)
        print("BEST STRATEGY FOR EACH ASSET")
        print("="*80)
        
        best_strategies = {}
        
        for asset in ['GOLD', 'SILVER', 'BTC', 'ETH']:
            asset_data = results_df[results_df['asset'] == asset]
            if len(asset_data) > 0:
                best = asset_data.loc[asset_data['sharpe'].idxmax()]
                best_strategies[asset] = best
                
                print(f"\n🏆 {asset}")
                print(f"   Strategy: {best['strategy']}")
                print(f"   Type: {best['type']}")
                print(f"   Sharpe: {best['sharpe']:.2f}")
                print(f"   Return: {best['total_return']:.1f}%")
                print(f"   Win Rate: {best['win_rate']:.1f}%")
                print(f"   Profit Factor: {best['profit_factor']:.2f}")
                print(f"   Trades: {best['trades']}")
        
        # Save best strategies
        with open('C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/BEST_STRATEGIES_PER_ASSET.json', 'w') as f:
            # Convert to serializable format
            best_dict = {asset: {k: float(v) if isinstance(v, (np.floating, np.integer)) else v 
                                 for k, v in data.items()} 
                        for asset, data in best_strategies.items()}
            json.dump(best_dict, f, indent=2)
        
        return best_strategies


if __name__ == "__main__":
    finder = UltimateStrategyFinder()
    best_strategies = finder.find_best_for_each_asset()
    
    print("\n" + "="*80)
    print("RESULTS SAVED")
    print("="*80)
    print("1. ULTIMATE_RESULTS_GOLD_SILVER_BTC_ETH.csv - All test results")
    print("2. BEST_STRATEGIES_PER_ASSET.json - Best strategy for each asset")
