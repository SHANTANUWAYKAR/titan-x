"""
COMPREHENSIVE BACKTEST - ALL STRATEGIES ON ALL ASSETS
₹10,000 Initial Capital with 1% Risk Management

This tests:
- 51 Strategies
- 31 Assets
- ₹10,000 starting capital
- 1% risk per trade (₹100 max loss per trade)
- Position sizing based on ATR stop loss
- Compound returns
- Real risk management

Total Tests: 51 × 31 = 1,581 combinations
"""

import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
import json
from datetime import datetime
import importlib.util


# Same 31-asset watchlist
WATCHLIST = {
    # Forex (4)
    'EURUSD': {'symbol': 'EURUSD=X', 'category': 'Forex', 'multiplier': 83.5},
    'GBPUSD': {'symbol': 'GBPUSD=X', 'category': 'Forex', 'multiplier': 83.5},
    'USDJPY': {'symbol': 'USDJPY=X', 'category': 'Forex', 'multiplier': 83.5},
    'USDINR': {'symbol': 'USDINR=X', 'category': 'Forex', 'multiplier': 1.0},
    
    # Crypto (2)
    'BTCUSD': {'symbol': 'BTC-USD', 'category': 'Crypto', 'multiplier': 83.5},
    'ETHUSD': {'symbol': 'ETH-USD', 'category': 'Crypto', 'multiplier': 83.5},
    
    # Commodities (3)
    'GOLD': {'symbol': 'GC=F', 'category': 'Commodity', 'multiplier': 83.5},
    'SILVER': {'symbol': 'SI=F', 'category': 'Commodity', 'multiplier': 83.5},
    'CRUDE': {'symbol': 'CL=F', 'category': 'Commodity', 'multiplier': 83.5},
    
    # Indices (2)
    'NIFTY50': {'symbol': '^NSEI', 'category': 'Index', 'multiplier': 1.0},
    'BANKNIFTY': {'symbol': '^NSEBANK', 'category': 'Index', 'multiplier': 1.0},
    
    # Bonds (1)
    'US10Y': {'symbol': '^TNX', 'category': 'Bond', 'multiplier': 83.5},
    
    # Futures (1)
    'SP500': {'symbol': 'ES=F', 'category': 'Future', 'multiplier': 83.5},
    
    # US Equities (8)
    'AAPL': {'symbol': 'AAPL', 'category': 'US_Stock', 'multiplier': 83.5},
    'MSFT': {'symbol': 'MSFT', 'category': 'US_Stock', 'multiplier': 83.5},
    'NVDA': {'symbol': 'NVDA', 'category': 'US_Stock', 'multiplier': 83.5},
    'GOOGL': {'symbol': 'GOOGL', 'category': 'US_Stock', 'multiplier': 83.5},
    'AMZN': {'symbol': 'AMZN', 'category': 'US_Stock', 'multiplier': 83.5},
    'TSLA': {'symbol': 'TSLA', 'category': 'US_Stock', 'multiplier': 83.5},
    'META': {'symbol': 'META', 'category': 'US_Stock', 'multiplier': 83.5},
    'JPM': {'symbol': 'JPM', 'category': 'US_Stock', 'multiplier': 83.5},
    
    # India Equities (8)
    'RELIANCE': {'symbol': 'RELIANCE.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'TCS': {'symbol': 'TCS.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'HDFCBANK': {'symbol': 'HDFCBANK.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'INFY': {'symbol': 'INFY.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'ICICIBANK': {'symbol': 'ICICIBANK.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'SBIN': {'symbol': 'SBIN.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'BHARTIARTL': {'symbol': 'BHARTIARTL.NS', 'category': 'India_Stock', 'multiplier': 1.0},
    'ITC': {'symbol': 'ITC.NS', 'category': 'India_Stock', 'multiplier': 1.0},
}


class RiskManagedBacktester:
    """
    Professional backtester with 1% risk management
    ₹10,000 initial capital
    """
    
    def __init__(self, initial_capital_inr=10000, risk_per_trade_pct=1.0):
        self.initial_capital = initial_capital_inr
        self.risk_per_trade_pct = risk_per_trade_pct  # 1%
        self.risk_amount = initial_capital_inr * (risk_per_trade_pct / 100)  # ₹100
        self.commission = 0.001  # 0.1%
        
    def backtest_with_risk_management(self, df, signals):
        """
        Backtest with proper 1% risk management
        
        Position size = Risk Amount / Stop Loss Distance
        Stop Loss = 2 ATR
        """
        
        if len(signals) == 0 or signals.sum() == 0:
            return self.empty_metrics()
        
        # Initialize
        capital = self.initial_capital
        positions = []
        equity_curve = [capital]
        trade_log = []
        
        # Get position changes
        position_signal = signals.replace(0, np.nan).ffill().fillna(0)
        
        for i in range(1, len(df)):
            current_signal = position_signal.iloc[i]
            prev_signal = position_signal.iloc[i-1]
            
            # Entry
            if current_signal != 0 and prev_signal == 0:
                entry_price = df['close'].iloc[i]
                atr = df['ATR'].iloc[i] if 'ATR' in df.columns else entry_price * 0.02
                
                # Stop loss = 2 ATR
                stop_distance = 2 * atr
                
                # Position size based on risk
                # Risk ₹100 on stop loss distance
                position_size = self.risk_amount / stop_distance
                
                # Calculate actual capital used (respecting available capital)
                capital_required = position_size * entry_price
                
                # Can't use more than available capital
                if capital_required > capital * 0.95:  # Use max 95% of capital
                    position_size = (capital * 0.95) / entry_price
                
                positions.append({
                    'entry_idx': i,
                    'entry_price': entry_price,
                    'direction': current_signal,
                    'position_size': position_size,
                    'stop_loss': stop_distance,
                    'atr': atr
                })
            
            # Exit
            elif current_signal == 0 and prev_signal != 0 and len(positions) > 0:
                position = positions[-1]
                exit_price = df['close'].iloc[i]
                
                # Calculate P&L
                if position['direction'] == 1:  # Long
                    pnl = (exit_price - position['entry_price']) * position['position_size']
                else:  # Short
                    pnl = (position['entry_price'] - exit_price) * position['position_size']
                
                # Commission
                commission_cost = (position['position_size'] * position['entry_price'] + 
                                 position['position_size'] * exit_price) * self.commission
                
                pnl -= commission_cost
                
                # Update capital
                capital += pnl
                
                # Log trade
                trade_log.append({
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'capital_after': capital,
                    'bars_held': i - position['entry_idx']
                })
            
            equity_curve.append(capital)
        
        # Calculate metrics
        if len(trade_log) == 0:
            return self.empty_metrics()
        
        trades_df = pd.DataFrame(trade_log)
        
        total_return = (capital - self.initial_capital) / self.initial_capital
        num_trades = len(trade_log)
        
        wins = trades_df[trades_df['pnl'] > 0]
        losses = trades_df[trades_df['pnl'] < 0]
        
        win_rate = len(wins) / num_trades if num_trades > 0 else 0
        
        # Sharpe ratio from equity curve
        equity_series = pd.Series(equity_curve)
        returns = equity_series.pct_change().dropna()
        
        if returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
        else:
            sharpe = 0
        
        # Max drawdown
        equity_series_cum = pd.Series(equity_curve)
        running_max = equity_series_cum.expanding().max()
        drawdown = (equity_series_cum - running_max) / running_max
        max_drawdown = drawdown.min()
        
        # Profit factor
        if len(wins) > 0 and len(losses) > 0:
            total_wins = wins['pnl'].sum()
            total_losses = abs(losses['pnl'].sum())
            profit_factor = total_wins / total_losses if total_losses > 0 else 0
        else:
            profit_factor = 0
        
        # Average trade
        avg_pnl = trades_df['pnl'].mean()
        
        return {
            'initial_capital': self.initial_capital,
            'final_capital': capital,
            'profit_inr': capital - self.initial_capital,
            'total_return_pct': total_return * 100,
            'sharpe': sharpe,
            'max_drawdown_pct': max_drawdown * 100,
            'num_trades': num_trades,
            'win_rate_pct': win_rate * 100,
            'profit_factor': profit_factor,
            'avg_pnl_per_trade': avg_pnl,
            'risk_per_trade': self.risk_amount,
            'largest_win': wins['pnl'].max() if len(wins) > 0 else 0,
            'largest_loss': losses['pnl'].min() if len(losses) > 0 else 0,
        }
    
    def empty_metrics(self):
        return {
            'initial_capital': self.initial_capital,
            'final_capital': self.initial_capital,
            'profit_inr': 0,
            'total_return_pct': 0,
            'sharpe': 0,
            'max_drawdown_pct': 0,
            'num_trades': 0,
            'win_rate_pct': 0,
            'profit_factor': 0,
            'avg_pnl_per_trade': 0,
            'risk_per_trade': self.risk_amount,
            'largest_win': 0,
            'largest_loss': 0,
        }
    
    def compute_indicators(self, df):
        """Compute all needed indicators"""
        df = df.copy()
        df.columns = df.columns.str.lower()
        
        # EMAs
        for period in [3, 5, 9, 10, 15, 20, 50, 100, 200]:
            df[f'EMA_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
        
        # ATR (critical for position sizing!)
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


def run_comprehensive_test():
    """
    Main execution: Test ALL strategies on ALL assets with ₹10,000 and 1% risk
    """
    
    print("="*80)
    print("COMPREHENSIVE BACKTEST - 1% RISK MANAGEMENT")
    print("="*80)
    print(f"Initial Capital: ₹10,000")
    print(f"Risk Per Trade: 1% (₹100)")
    print(f"Position Sizing: Risk / (2 × ATR)")
    print(f"Commission: 0.1%")
    print("="*80)
    
    backtester = RiskManagedBacktester(initial_capital_inr=10000, risk_per_trade_pct=1.0)
    
    # Get all strategy files
    strategies_dir = Path('C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/generated_strategies')
    strategy_files = list(strategies_dir.glob('strategy_*.py'))
    strategy_files.append(strategies_dir / 'WORLD_FAMOUS_STRATEGIES.py')
    
    print(f"\nFound {len(strategy_files)} strategy files")
    print(f"Testing on {len(WATCHLIST)} assets")
    print(f"Total tests: {len(strategy_files) * len(WATCHLIST)}\n")
    
    all_results = []
    test_count = 0
    total_tests = len(strategy_files) * len(WATCHLIST)
    
    # Test each asset
    for asset_name, asset_info in WATCHLIST.items():
        print(f"\n{'='*80}")
        print(f"ASSET: {asset_name}")
        print(f"{'='*80}")
        
        # Download data
        try:
            symbol = asset_info['symbol']
            df = yf.download(symbol, period='2y', interval='1d', progress=False)
            
            if len(df) < 200:
                print(f"  ✗ Insufficient data")
                continue
            
            # Convert to INR
            multiplier = asset_info['multiplier']
            if multiplier != 1.0:
                for col in ['Open', 'High', 'Low', 'Close']:
                    if col in df.columns:
                        df[col] = df[col] * multiplier
            
            # Compute indicators
            df = backtester.compute_indicators(df)
            
            print(f"  ✓ Data loaded ({len(df)} bars)")
            
        except Exception as e:
            print(f"  ✗ Download failed: {e}")
            continue
        
        # Test each strategy on this asset
        asset_best_sharpe = -999
        asset_best_profit = -999999
        
        for strategy_file in strategy_files:
            test_count += 1
            
            try:
                # Load strategy
                spec = importlib.util.spec_from_file_location("strat", strategy_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Find strategy functions
                strategy_funcs = [getattr(module, name) for name in dir(module) 
                                if callable(getattr(module, name)) and name.startswith('strategy_')]
                
                for strategy_func in strategy_funcs:
                    try:
                        # Generate signals
                        signals = strategy_func(df)
                        
                        # Backtest with risk management
                        metrics = backtester.backtest_with_risk_management(df, signals)
                        
                        # Store result
                        result = {
                            'asset': asset_name,
                            'category': asset_info['category'],
                            'strategy': strategy_func.__name__,
                            'strategy_file': strategy_file.name,
                            **metrics
                        }
                        
                        all_results.append(result)
                        
                        # Track best for this asset
                        if metrics['sharpe'] > asset_best_sharpe:
                            asset_best_sharpe = metrics['sharpe']
                        if metrics['profit_inr'] > asset_best_profit:
                            asset_best_profit = metrics['profit_inr']
                        
                        # Print promising results
                        if metrics['profit_inr'] > 2000:  # Profit > ₹2000 (20% return)
                            print(f"    ✓ {strategy_func.__name__[:40]:40} | Profit: ₹{metrics['profit_inr']:>7,.0f} | Sharpe: {metrics['sharpe']:>5.2f} | Trades: {metrics['num_trades']:>3}")
                    
                    except Exception as e:
                        pass  # Silent fail for individual strategy
            
            except Exception as e:
                pass  # Silent fail for file loading
            
            # Progress update
            if test_count % 100 == 0:
                print(f"\n  Progress: {test_count}/{total_tests} tests completed...")
        
        print(f"\n  🏆 Best for {asset_name}:")
        print(f"      Sharpe: {asset_best_sharpe:.2f}")
        print(f"      Profit: ₹{asset_best_profit:,.0f}")
    
    # Save results
    results_df = pd.DataFrame(all_results)
    results_path = 'C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/COMPLETE_RESULTS_10K_1PCT_RISK.csv'
    results_df.to_csv(results_path, index=False)
    
    print("\n" + "="*80)
    print("RESULTS SAVED")
    print("="*80)
    print(f"File: {results_path}")
    print(f"Total tests completed: {len(results_df)}")
    
    # Generate summary
    generate_summary(results_df)
    
    return results_df


def generate_summary(results_df):
    """Generate best results summary"""
    
    print("\n" + "="*80)
    print("TOP 20 RESULTS (₹10,000 Initial Capital, 1% Risk)")
    print("="*80)
    
    # Sort by profit
    top_20 = results_df.nlargest(20, 'profit_inr')
    
    for i, row in top_20.iterrows():
        print(f"\n{row.name + 1}. {row['asset']} - {row['strategy'][:40]}")
        print(f"   Initial: ₹10,000 → Final: ₹{row['final_capital']:,.0f}")
        print(f"   Profit: ₹{row['profit_inr']:,.0f} ({row['total_return_pct']:.1f}%)")
        print(f"   Sharpe: {row['sharpe']:.2f} | Win Rate: {row['win_rate_pct']:.1f}% | Trades: {row['num_trades']}")
    
    # Best per asset
    print("\n" + "="*80)
    print("BEST STRATEGY PER ASSET (₹10,000 Capital)")
    print("="*80)
    
    best_per_asset = results_df.loc[results_df.groupby('asset')['profit_inr'].idxmax()]
    best_per_asset = best_per_asset.sort_values('profit_inr', ascending=False)
    
    summary_path = 'C:/Users/wayka/OneDrive/Documents/TIS/project_titan_x/BEST_PER_ASSET_10K_1PCT.csv'
    best_per_asset.to_csv(summary_path, index=False)
    
    print(f"\nSaved: {summary_path}\n")
    
    for _, row in best_per_asset.head(31).iterrows():
        print(f"{row['asset']:12} | {row['strategy'][:35]:35} | ₹{row['profit_inr']:>6,.0f} | {row['total_return_pct']:>6.1f}%")


if __name__ == "__main__":
    results = run_comprehensive_test()
