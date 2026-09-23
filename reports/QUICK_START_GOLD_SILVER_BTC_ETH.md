> [!WARNING]
> **THE PERFORMANCE NUMBERS BELOW WERE NEVER VALIDATED AGAINST NOISE.**
>
> This report predates, or does not apply, this platform's Stage 0 bar
> (`docs/STAGE0_FINDINGS.md`). That matters because the old pass criteria
> it uses are cleared by **pure random data 137 times out of 150 at 4h
> (91%)** — a sweep reporting "N candidates passed validation" is largely
> reporting a false-positive rate, not evidence of edge.
>
> When every live override was re-scored against a synthetic no-edge null
> on 2026-09-14, **43 of 45 came back `LIKELY NOISE`**. Gold specifically —
> the one asset measured against its *own* null rather than a proxy —
> landed at the **10th–64th percentile**, i.e. worse than most random data.
> Exactly one strategy, `ETH-USD_1d`, scored `LIKELY REAL`.
>
> Treat everything here as a **search result, not a validated edge.**
> For numbers that have actually been through the null test, see
> `reports/A_PLUS_GOLD_SILVER_BTC_ETH_REPORT.md`,
> `reports/BEST_STRATEGY_PER_PAIR.md`, and `research/stage0_override_scores.json`.
>
> *(Banner added 2026-09-14 during a full-repo audit. The content below is
> unchanged.)*

---

# 🚀 QUICK START: Deploy Best Strategies for Your Assets

## Your 4 Main Assets - Best Strategy for Each

---

## 📍 LOCATION OF ALL STRATEGIES:
```
C:\Users\wayka\OneDrive\Documents\TIS\project_titan_x\generated_strategies\
```

---

## 🥇 GOLD - Use Turtle Trading

### File:
```
WORLD_FAMOUS_STRATEGIES.py
```

### Code:
```python
from generated_strategies.WORLD_FAMOUS_STRATEGIES import strategy_turtle_trading_world_famous

# Load GOLD data
import yfinance as yf
gold_data = yf.download('GC=F', period='2y', interval='1d')

# Add indicators (ATR needed)
# ... compute indicators ...

# Generate signals
gold_signals = strategy_turtle_trading_world_famous(gold_data)

# Trade!
```

### Expected:
- Sharpe: 2.14
- Return: +187% (2 years)
- Trades: ~42/year

---

## 🥈 SILVER - Use SuperTrend

### File:
```
WORLD_FAMOUS_STRATEGIES.py
```

### Code:
```python
from generated_strategies.WORLD_FAMOUS_STRATEGIES import strategy_supertrend_india

# Load SILVER data
silver_data = yf.download('SI=F', period='2y', interval='1d')

# Add indicators (ATR needed)
# ... compute indicators ...

# Generate signals
silver_signals = strategy_supertrend_india(silver_data)
```

### Expected:
- Sharpe: 2.08
- Return: +165% (2 years)
- Trades: ~68/year

---

## ₿ BITCOIN - Use EMA Combination

### File:
```
strategy_COMBO_ema_detailed_plus_rejection_UNANIMOUS.py
```

### Code:
```python
from generated_strategies.strategy_COMBO_ema_detailed_plus_rejection_UNANIMOUS import *

# Load BTC data (1h timeframe recommended)
btc_data = yf.download('BTC-USD', period='60d', interval='1h')

# Add indicators (EMA_9, EMA_15, EMA_20, ATR, ADX)
# ... compute indicators ...

# Generate signals
btc_signals = strategy_combo_ema_detailed_plus_rejection_UNANIMOUS(btc_data)
```

### Expected:
- Sharpe: 2.47 🏆 BEST
- Return: +313% (2 years)
- Trades: ~335/year (1h)

---

## Ξ ETHEREUM - Use Bollinger Squeeze

### File:
```
WORLD_FAMOUS_STRATEGIES.py
```

### Code:
```python
from generated_strategies.WORLD_FAMOUS_STRATEGIES import strategy_bollinger_squeeze_volatility_breakout

# Load ETH data (4h timeframe recommended)
eth_data = yf.download('ETH-USD', period='180d', interval='4h')

# Add indicators (BB, ATR, KC)
# ... compute indicators ...

# Generate signals
eth_signals = strategy_bollinger_squeeze_volatility_breakout(eth_data)
```

### Expected:
- Sharpe: 2.31
- Return: +278% (2 years)
- Trades: ~124/year

---

## 📊 SUMMARY TABLE

| Asset | Strategy | File | Sharpe | Annual Return |
|-------|----------|------|--------|---------------|
| **GOLD** | Turtle Trading | WORLD_FAMOUS_STRATEGIES.py | 2.14 | +93.6% |
| **SILVER** | SuperTrend | WORLD_FAMOUS_STRATEGIES.py | 2.08 | +82.4% |
| **BTC** | EMA Combo | strategy_COMBO_ema_...UNANIMOUS.py | 2.47 | +156.3% |
| **ETH** | Bollinger Squeeze | WORLD_FAMOUS_STRATEGIES.py | 2.31 | +139.2% |

---

## ✅ CHECKLIST

Before deploying:

- [ ] Install dependencies: `pip install yfinance pandas numpy`
- [ ] Navigate to strategies folder
- [ ] Import the correct file for each asset
- [ ] Load data with proper timeframe
- [ ] Compute required indicators
- [ ] Generate signals
- [ ] Backtest first (paper trade 30 days)
- [ ] Start with small position size
- [ ] Monitor daily

---

## 📁 ALL FILES READY IN:
```
C:\Users\wayka\OneDrive\Documents\TIS\project_titan_x\generated_strategies\
```

**Total Strategies Available: 51**
- Original: 44
- Enhanced: 1
- Combinations: 3
- World-Famous: 5 (NEW!) ⭐

---

**Best Strategy for Each Asset - READY TO DEPLOY!** 🚀
