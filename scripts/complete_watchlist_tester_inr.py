"""
ULTIMATE STRATEGY FINDER - COMPLETE WATCHLIST (31 ASSETS)
Testing in Indian Rupees (INR)

YOUR WATCHLIST:
- Forex (4): EURUSD, GBPUSD, USDJPY, USDINR
- Crypto (2): BTCUSD, ETHUSD
- Commodities (3): GOLD, SILVER, CRUDE
- Indices (2): NIFTY50, BANKNIFTY
- Bonds (1): US10Y
- Futures (1): SP500
- US Equities (8): AAPL, MSFT, NVDA, GOOGL, AMZN, TSLA, META, JPM
- India Equities (8): RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, SBIN, BHARTIARTL, ITC

TOTAL: 31 ASSETS

Currency: INR (Indian Rupees)
Initial Capital: ₹10,00,000 (10 Lakhs)
"""

import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
import json
from datetime import datetime
import importlib.util


# Asset symbol mappings for yfinance
WATCHLIST = {
    # Forex (4)
    'EURUSD': {'symbol': 'EURUSD=X', 'category': 'Forex', 'multiplier': 83.5},  # USD to INR
    'GBPUSD': {'symbol': 'GBPUSD=X', 'category': 'Forex', 'multiplier': 83.5},
    'USDJPY': {'symbol': 'USDJPY=X', 'category': 'Forex', 'multiplier': 83.5},
    'USDINR': {'symbol': 'USDINR=X', 'category': 'Forex', 'multiplier': 1.0},  # Already INR
    
    # Crypto (2)
    'BTCUSD': {'symbol': 'BTC-USD', 'category': 'Crypto', 'multiplier': 83.5},
    'ETHUSD': {'symbol': 'ETH-USD', 'category': 'Crypto', 'multiplier': 83.5},
    
    # Commodities (3)
    'GOLD': {'symbol': 'GC=F', 'category': 'Commodity', 'multiplier': 83.5},  # Gold Futures
    'SILVER': {'symbol': 'SI=F', 'category': 'Commodity', 'multiplier': 83.5},
    'CRUDE': {'symbol': 'CL=F', 'category': 'Commodity', 'multiplier': 83.5},  # WTI Crude
    
    # Indices (2)
    'NIFTY50': {'symbol': '^NSEI', 'category': 'Index', 'multiplier': 1.0},  # Already INR
    'BANKNIFTY': {'symbol': '^NSEBANK', 'category': 'Index', 'multiplier': 1.0},  # Already INR
    
    # Bonds (1)
    'US10Y': {'symbol': '^TNX', 'category': 'Bond', 'multiplier': 83.5},
    
    # Futures (1)
    'SP500': {'symbol': 'ES=F', 'category': 'Future', 'multiplier': 83.5},  # E-mini S&P
    
    # US Equities (8)
    'AAPL': {'symbol': 'AAPL', 'category': 'US_Stock', 'multiplier': 83.5},
    'MSFT': {'symbol': 'MSFT', 'category': 'US_Stock', 'multiplier': 83.5},
    'NVDA': {'symbol': 'NVDA', 'category': 'US_Stock', 'multiplier': 83.5},
    'GOOGL': {'symbol': 'GOOGL', 'category': 'US_Stock', 'multiplier': 83.5},
    'AMZN': {'symbol': 'AMZN', 'category': 'US_Stock', 'multiplier': 83.5},
    'TSLA': {'symbol': 'TSLA', 'category': 'US_Stock', 'multiplier': 83.5},
    'META': {'symbol': 'META', 'category': 'US_Stock', 'multiplier': 83.5},
    'JPM': {'symbol': 'JPM', 'category': 'US_Stock', 'multiplier': 83.5},
    
    # India Equities (8) - NSE
    'RELIANCE': {'symbol': 'RELIANCE.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'TCS': {'symbol': 'TCS.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'HDFCBANK': {'symbol': 'HDFCBANK.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'INFY': {'symbol': 'INFY.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'ICICIBANK': {'symbol': 'ICICIBANK.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'SBIN': {'symbol': 'SBIN.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'BHARTIARTL': {'symbol': 'BHARTIARTL.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'ITC': {'symbol': 'ITC.NS', 'category': 'India_Stock', 'multiplier': 1.0},
}


class CompleteWatchlistTester:
    """Test all strategies on complete 31-asset watchlist in INR"""
    
    def __init__(self, initial_capital_inr=1000000):  # 10 lakhs INR
        self.initial_capital = initial_capital_inr
        self.commission = 0.001  # 0.1%
        self.usd_to_inr = 83.5  # Current rate
        self.results = []
        
    def download_data(self, asset_name, symbol, period='2y', interval='1d'):
        """Download and convert to INR if needed"""
        print(f"  Downloading {asset_name} ({symbol})...", end='')
        try:
            df = yf.download(symbol, period=period, interval=interval, progress=False)
            if len(df) > 200:
                # Convert to INR
                multiplier = WATCHLIST[asset_name]['multiplier']
                if multiplier != 1.0:
                    for col in ['Open', 'High', 'Low', 'Close']:
                        if col in df.columns:
                            df[col] = df[col] * multiplier
                
                print(f" ✓ ({len(df)} bars, converted to INR)")
                return self.compute_indicators(df)
            else:
                print(f" ✗ (insufficient data)")
                return None
        except Exception as e:
            print(f" ✗ ({str(e)})")
            return None
    
    def compute_indicators(self, df):
        """Compute all technical indicators"""
        df = df.copy()
        df.columns = df.columns.str.lower()
        
        # EMAs
        for period in [3, 5, 9, 10, 15, 20, 50, 100, 200]:
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
    
    def backtest_inr(self, df, signals):
        """Backtest with INR capital"""
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
        
        # Calculate in INR
        final_capital_inr = self.initial_capital * (1 + total_return)
        profit_inr = final_capital_inr - self.initial_capital
        
        return {
            'sharpe': sharpe,
            'total_return_pct': total_return * 100,
            'profit_inr': profit_inr,
            'final_capital_inr': final_capital_inr,
            'max_drawdown_pct': max_drawdown * 100,
            'win_rate_pct': win_rate * 100,
            'trades': int(trades),
            'profit_factor': profit_factor
        }
    
    def empty_metrics(self):
        return {
            'sharpe': 0,
            'total_return_pct': 0,
            'profit_inr': 0,
            'final_capital_inr': self.initial_capital,
            'max_drawdown_pct': 0,
            'win_rate_pct': 0,
            'trades': 0,
            'profit_factor': 0
        }
    
    def load_strategy(self, strategy_path):
        """Dynamically load strategy"""
        try:
            spec = importlib.util.spec_from_file_location("strat", strategy_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            for name in dir(module):
                obj = getattr(module, name)
                if callable(obj) and name.startswith('strategy_'):
                    return obj
            return None
        except:
            return None
    
    def test_all_on_watchlist(self):
        """Main execution - test all strategies on all 31 assets"""
        
        print("\n" + "="*80)
        print("ULTIMATE WATCHLIST TESTING - 31 ASSETS IN INR")
        print("="*80)
        print(f"Initial Capital: ₹{self.initial_capital:,.0f} ({self.initial_capital/100000:.1f} Lakhs)")
        print(f"USD to INR Rate: {self.usd_to_inr}")
        print("="*80)
        
        all_results = []
        
        # Load all strategies
        strategies_dir = Path('C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/generated_strategies')
        
        strategy_files = {
            # Top combinations
            'EMA Detail + Rejection (UNANIMOUS)': strategies_dir / 'strategy_COMBO_ema_detailed_plus_rejection_UNANIMOUS.py',
            '200 EMA + SMC (MAJORITY)': strategies_dir / 'strategy_COMBO_200ema_plus_smc_MAJORITY.py',
            'Liquidity Sweep + FVG (UNANIMOUS)': strategies_dir / 'strategy_COMBO_liquidity_sweep_plus_fvg_UNANIMOUS.py',
            
            # World famous
            'Turtle Trading': strategies_dir / 'WORLD_FAMOUS_STRATEGIES.py',
            'SuperTrend (India)': strategies_dir / 'WORLD_FAMOUS_STRATEGIES.py',
            'Ichimoku Cloud (Japan)': strategies_dir / 'WORLD_FAMOUS_STRATEGIES.py',
            'Bollinger Squeeze': strategies_dir / 'WORLD_FAMOUS_STRATEGIES.py',
            'Connors RSI': strategies_dir / 'WORLD_FAMOUS_STRATEGIES.py',
            
            # Top single strategies
            '9-15 EMA Detailed': strategies_dir / 'strategy_9_15_ema_detailed_ENHANCED.py',
            '200 EMA Devanshrai': strategies_dir / 'strategy_200ema_devanshrai_strategy.py',
            'EMA Rejection': strategies_dir / 'strategy_ema_rejection_strategy.py',
            'London Breakout': strategies_dir / 'strategy_london_breakout_strategy.py',
            'Asian Session BOS': strategies_dir / 'strategy_asian_session_bos_strategy.py',
        }
        
        # Test each asset
        for asset_name, asset_info in WATCHLIST.items():
            print(f"\n{'='*80}")
            print(f"ASSET: {asset_name} ({asset_info['category']})")
            print(f"{'='*80}")
            
            # Download data
            df = self.download_data(asset_name, asset_info['symbol'])
            
            if df is None:
                continue
            
            asset_results = []
            
            # Test top strategies only (for speed)
            for strategy_name, strategy_path in list(strategy_files.items())[:10]:
                try:
                    strategy_func = self.load_strategy(strategy_path)
                    if strategy_func:
                        signals = strategy_func(df)
                        metrics = self.backtest_inr(df, signals)
                        
                        result = {
                            'asset': asset_name,
                            'category': asset_info['category'],
                            'strategy': strategy_name,
                            **metrics
                        }
                        
                        asset_results.append(result)
                        all_results.append(result)
                        
                        if metrics['sharpe'] > 1.0:
                            print(f"  ✓ {strategy_name:35} | Sharpe: {metrics['sharpe']:5.2f} | Profit: ₹{metrics['profit_inr']:>10,.0f}")
                
                except Exception as e:
                    pass  # Silent fail, continue
            
            # Find best for this asset
            if asset_results:
                best = max(asset_results, key=lambda x: x['sharpe'])
                print(f"\n  🏆 BEST: {best['strategy']} (Sharpe: {best['sharpe']:.2f}, Profit: ₹{best['profit_inr']:,.0f})")
        
        # Save results
        results_df = pd.DataFrame(all_results)
        results_path = 'C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/COMPLETE_WATCHLIST_RESULTS_INR.csv'
        results_df.to_csv(results_path, index=False)
        
        print("\n" + "="*80)
        print("RESULTS SAVED")
        print("="*80)
        print(f"File: {results_path}")
        
        # Generate best-per-asset summary
        self.generate_summary(results_df)
        
        return results_df
    
    def generate_summary(self, results_df):
        """Generate best strategy per asset summary"""
        
        print("\n" + "="*80)
        print("BEST STRATEGY FOR EACH ASSET (INR)")
        print("="*80)
        
        summary = []
        
        for asset in WATCHLIST.keys():
            asset_data = results_df[results_df['asset'] == asset]
            if len(asset_data) > 0:
                best = asset_data.loc[asset_data['sharpe'].idxmax()]
                summary.append({
                    'Asset': asset,
                    'Category': best['category'],
                    'Best_Strategy': best['strategy'],
                    'Sharpe': f"{best['sharpe']:.2f}",
                    'Return_%': f"{best['total_return_pct']:.1f}%",
                    'Profit_INR': f"₹{best['profit_inr']:,.0f}",
                    'Win_Rate': f"{best['win_rate_pct']:.1f}%",
                    'Trades': int(best['trades'])
                })
        
        summary_df = pd.DataFrame(summary)
        summary_path = 'C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/BEST_STRATEGY_PER_ASSET_INR.csv'
        summary_df.to_csv(summary_path, index=False)
        
        print(summary_df.to_string(index=False))
        print(f"\nSummary saved: {summary_path}")


if __name__ == "__main__":
    tester = CompleteWatchlistTester(initial_capital_inr=1000000)  # 10 lakhs
    results = tester.test_all_on_watchlist()
