"""
MASTER BACKTEST — YOUTUBE_DECODED + NEW_GEN_CONCEPTS
=====================================================
• 10 strategies  x  29 assets  x  6 timeframes  =  1,740 tests
• Capital : ₹10,000  |  Risk : 1 %  |  Commission : 0.1 %
• Outputs :
    MASTER_BACKTEST_RESULTS.csv              — one row per test
    BACKTEST_SUMMARY_BY_ASSET_AND_STYLE.html — interactive dashboard
"""

import sys, importlib.util, traceback, warnings
from pathlib import Path

import numpy  as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── paths ────────────────────────────────────────────────────────────────────
ROOT   = Path(__file__).resolve().parents[1]
SBS    = ROOT / "strategies_by_style"
OUT    = ROOT / "reports"

# inject strategy folders into sys.path so relative imports work
for folder in ["YOUTUBE_DECODED", "NEW_GEN_CONCEPTS"]:
    p = str(SBS / folder)
    if p not in sys.path:
        sys.path.insert(0, p)

# ── strategy registry ────────────────────────────────────────────────────────
STRATEGIES = {
    # YOUTUBE DECODED
    "Swappy_3C_Scalping": {
        "file":  SBS / "YOUTUBE_DECODED" / "strategy_swappy_3c_scalping.py",
        "fn":    "strategy_swappy_3c_scalping",
        "style": "Intraday",
        "source":"YouTube @SwappyTrading0101",
    },
    "GautamJha_Liquidity_Breakout": {
        "file":  SBS / "YOUTUBE_DECODED" / "strategy_gautam_jha_liquidity_breakout.py",
        "fn":    "strategy_gautam_jha_liquidity_breakout",
        "style": "Intraday",
        "source":"YouTube @gautammjhaa",
    },
    "UmarPunjabi_Gold_London": {
        "file":  SBS / "YOUTUBE_DECODED" / "strategy_umar_punjabi_gold_london.py",
        "fn":    "strategy_umar_punjabi_gold_london",
        "style": "Intraday",
        "source":"YouTube @UmarPunjabiLive",
    },
    # NEW GEN CONCEPTS
    "VolumeProfile_POC": {
        "file":  SBS / "NEW_GEN_CONCEPTS" / "strategy_volume_profile_poc.py",
        "fn":    "generate_signal",
        "style": "Swing",
        "source":"New-Gen: Volume Profile",
    },
    "Footprint_Delta_CVD": {
        "file":  SBS / "NEW_GEN_CONCEPTS" / "strategy_footprint_delta.py",
        "fn":    "generate_signal",
        "style": "Intraday",
        "source":"New-Gen: Footprint/CVD",
    },
    "GEX_Gamma_Exposure": {
        "file":  SBS / "NEW_GEN_CONCEPTS" / "strategy_gex_gamma_exposure.py",
        "fn":    "generate_signal",
        "style": "Intraday",
        "source":"New-Gen: GEX Proxy",
    },
    "Heatmap_Liquidity": {
        "file":  SBS / "NEW_GEN_CONCEPTS" / "strategy_heatmap_liquidity.py",
        "fn":    "generate_signal",
        "style": "Intraday",
        "source":"New-Gen: Liquidity Heatmap",
    },
    "TPO_Market_Profile": {
        "file":  SBS / "NEW_GEN_CONCEPTS" / "strategy_tpo_market_profile.py",
        "fn":    "generate_signal",
        "style": "Swing",
        "source":"New-Gen: TPO/Market Profile",
    },
    "VWAP_Bands": {
        "file":  SBS / "NEW_GEN_CONCEPTS" / "strategy_vwap_bands.py",
        "fn":    "generate_signal",
        "style": "Intraday",
        "source":"New-Gen: VWAP ±2σ Bands",
    },
    "CVD_Composite_Flagship": {
        "file":  SBS / "NEW_GEN_CONCEPTS" / "strategy_cvd_composite.py",
        "fn":    "generate_signal",
        "style": "Swing",
        "source":"New-Gen: CVD+VWAP+VolProfile+Liquidity",
    },
}

# ── asset universe ────────────────────────────────────────────────────────────
ASSETS = {
    "EURUSD":     {"cat":"Forex",        "ann_vol":0.07,  "drift":0.02,  "inr":83.5},
    "GBPUSD":     {"cat":"Forex",        "ann_vol":0.09,  "drift":0.03,  "inr":83.5},
    "USDJPY":     {"cat":"Forex",        "ann_vol":0.08,  "drift":-0.02, "inr":83.5},
    "USDINR":     {"cat":"Forex",        "ann_vol":0.05,  "drift":0.04,  "inr":1.0},
    "BTCUSD":     {"cat":"Crypto",       "ann_vol":0.65,  "drift":0.30,  "inr":83.5},
    "ETHUSD":     {"cat":"Crypto",       "ann_vol":0.70,  "drift":0.25,  "inr":83.5},
    "GOLD":       {"cat":"Commodity",    "ann_vol":0.15,  "drift":0.12,  "inr":83.5},
    "SILVER":     {"cat":"Commodity",    "ann_vol":0.25,  "drift":0.08,  "inr":83.5},
    "CRUDE":      {"cat":"Commodity",    "ann_vol":0.35,  "drift":0.05,  "inr":83.5},
    "NIFTY50":    {"cat":"Index",        "ann_vol":0.18,  "drift":0.14,  "inr":1.0},
    "BANKNIFTY":  {"cat":"Index",        "ann_vol":0.22,  "drift":0.12,  "inr":1.0},
    "SP500":      {"cat":"Index",        "ann_vol":0.16,  "drift":0.10,  "inr":83.5},
    "US10Y":      {"cat":"Bond",         "ann_vol":0.08,  "drift":-0.04, "inr":83.5},
    "AAPL":       {"cat":"US_Stock",     "ann_vol":0.28,  "drift":0.18,  "inr":83.5},
    "MSFT":       {"cat":"US_Stock",     "ann_vol":0.25,  "drift":0.20,  "inr":83.5},
    "NVDA":       {"cat":"US_Stock",     "ann_vol":0.55,  "drift":0.45,  "inr":83.5},
    "GOOGL":      {"cat":"US_Stock",     "ann_vol":0.28,  "drift":0.15,  "inr":83.5},
    "AMZN":       {"cat":"US_Stock",     "ann_vol":0.32,  "drift":0.18,  "inr":83.5},
    "TSLA":       {"cat":"US_Stock",     "ann_vol":0.60,  "drift":0.22,  "inr":83.5},
    "META":       {"cat":"US_Stock",     "ann_vol":0.35,  "drift":0.25,  "inr":83.5},
    "JPM":        {"cat":"US_Stock",     "ann_vol":0.22,  "drift":0.12,  "inr":83.5},
    "RELIANCE":   {"cat":"India_Stock",  "ann_vol":0.22,  "drift":0.14,  "inr":1.0},
    "TCS":        {"cat":"India_Stock",  "ann_vol":0.20,  "drift":0.12,  "inr":1.0},
    "HDFCBANK":   {"cat":"India_Stock",  "ann_vol":0.24,  "drift":0.10,  "inr":1.0},
    "INFY":       {"cat":"India_Stock",  "ann_vol":0.22,  "drift":0.11,  "inr":1.0},
    "ICICIBANK":  {"cat":"India_Stock",  "ann_vol":0.26,  "drift":0.13,  "inr":1.0},
    "SBIN":       {"cat":"India_Stock",  "ann_vol":0.30,  "drift":0.15,  "inr":1.0},
    "BHARTIARTL": {"cat":"India_Stock",  "ann_vol":0.25,  "drift":0.16,  "inr":1.0},
    "ITC":        {"cat":"India_Stock",  "ann_vol":0.18,  "drift":0.08,  "inr":1.0},
}

# timeframe → (n_bars, bars_per_year, style_label, freq_str for DatetimeIndex)
TIMEFRAMES = {
    "1m":  (1200, 252*390, "Intraday", "1min"),
    "5m":  (1200, 252*78,  "Intraday", "5min"),
    "15m": (1200, 252*26,  "Intraday", "15min"),
    "1h":  (1000, 252*7,   "Swing",    "1h"),
    "4h":  (800,  252*2,   "Swing",    "4h"),
    "1d":  (504,  252,     "Positional","1D"),
}

CAPITAL    = 10_000.0
RISK_PCT   = 0.01
COMMISSION = 0.001


# ── synthetic data ────────────────────────────────────────────────────────────
def make_ohlcv(n: int, ann_vol: float, drift: float,
               bpy: int, seed: int) -> pd.DataFrame:
    rng      = np.random.default_rng(seed)
    bar_vol  = ann_vol / np.sqrt(bpy)
    bar_mu   = drift   / bpy
    log_ret  = rng.normal(bar_mu, bar_vol, n)
    close    = 1000.0 * np.exp(np.cumsum(log_ret))
    intra    = bar_vol * 0.5
    open_    = close * np.exp(rng.normal(0, intra * 0.3, n))
    high     = np.maximum(close, open_) * np.exp(np.abs(rng.normal(0, intra, n)))
    low      = np.minimum(close, open_) / np.exp(np.abs(rng.normal(0, intra, n)))
    volume   = np.abs(rng.normal(1e6, 3e5, n)) + 1.0
    # realistic UTC timestamps so session filters work
    freq_map = {252*390:"1min",252*78:"5min",252*26:"15min",252*7:"1h",252*2:"4h",252:"1D"}
    freq     = freq_map.get(bpy, "1h")
    idx      = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open":open_,"high":high,"low":low,
                         "close":close,"volume":volume}, index=idx)


# ── indicator engine ──────────────────────────────────────────────────────────
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c  = df["close"]
    for p in [9, 20, 50, 200]:
        df[f"EMA_{p}"] = c.ewm(span=p, adjust=False).mean()
    hl  = df["high"] - df["low"]
    hc  = (df["high"] - c.shift(1)).abs()
    lc  = (df["low"]  - c.shift(1)).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()
    pdm = df["high"].diff().clip(lower=0)
    ndm = (-df["low"].diff()).clip(lower=0)
    tr14 = tr.rolling(14).sum().replace(0, np.nan)
    pdi  = 100 * pdm.rolling(14).sum() / tr14
    ndi  = 100 * ndm.rolling(14).sum() / tr14
    dx   = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    df["ADX"] = dx.rolling(14).mean()
    d = c.diff()
    g = d.clip(lower=0).rolling(14).mean()
    l = (-d.clip(upper=0)).rolling(14).mean()
    df["RSI"] = 100 - 100 / (1 + g / l.replace(0, np.nan))
    df["MACD"]        = c.ewm(12, adjust=False).mean() - c.ewm(26, adjust=False).mean()
    df["MACD_signal"] = df["MACD"].ewm(9, adjust=False).mean()
    df["BB_middle"]   = c.rolling(20).mean()
    std = c.rolling(20).std()
    df["BB_upper"]    = df["BB_middle"] + 2 * std
    df["BB_lower"]    = df["BB_middle"] - 2 * std
    return df.dropna()


# ── backtest ──────────────────────────────────────────────────────────────────
def backtest(df: pd.DataFrame, signals: pd.Series, bpy: int) -> dict:
    if signals is None or signals.abs().sum() == 0:
        return _empty()
    signals = signals.reindex(df.index).fillna(0)
    # next-bar open fill (no same-bar look-ahead)
    exec_sig = signals.shift(1).fillna(0)

    cap   = CAPITAL
    eq    = [cap]
    trades= []
    pos   = 0
    ep = sz = 0.0

    for i in range(1, len(df)):
        cur  = int(exec_sig.iloc[i])
        prev = int(exec_sig.iloc[i-1])

        if pos == 0 and cur != 0:
            pos = cur
            ep  = df["open"].iloc[i]           # fill at open (next bar)
            atr = max(float(df["ATR"].iloc[i]), ep * 0.001)
            sz  = (cap * RISK_PCT) / (2 * atr)  # risk-based sizing

        elif pos != 0 and (cur == 0 or cur != pos):
            xp   = df["open"].iloc[i]
            pnl  = pos * (xp - ep) * sz
            pnl -= sz * (ep + xp) * COMMISSION
            cap += pnl
            trades.append({"pnl": pnl})
            pos  = 0

        eq.append(cap)

    if not trades:
        return _empty()

    eq_s  = pd.Series(eq)
    ret_s = eq_s.pct_change().dropna()
    t     = pd.DataFrame(trades)
    wins  = t[t.pnl > 0]
    loss  = t[t.pnl < 0]

    sharpe  = float((ret_s.mean() / (ret_s.std() + 1e-12)) * np.sqrt(bpy))
    down    = ret_s[ret_s < 0]
    sortino = float((ret_s.mean() / (down.std() + 1e-12)) * np.sqrt(bpy)) if len(down) > 1 else 0.0
    roll_max= eq_s.cummax()
    dd_pct  = ((eq_s - roll_max) / roll_max * 100).min()
    calmar  = float(((cap - CAPITAL) / CAPITAL) / (abs(dd_pct / 100) + 1e-9))
    pf      = wins.pnl.sum() / (abs(loss.pnl.sum()) + 1e-9) if len(loss) else 0.0

    return {
        "final_capital_inr": round(cap, 2),
        "profit_inr":        round(cap - CAPITAL, 2),
        "return_pct":        round((cap - CAPITAL) / CAPITAL * 100, 2),
        "sharpe":            round(sharpe,  3),
        "sortino":           round(sortino, 3),
        "calmar":            round(calmar,  3),
        "max_dd_pct":        round(dd_pct,  2),
        "win_rate_pct":      round(len(wins) / len(t) * 100, 1),
        "profit_factor":     round(pf, 3),
        "num_trades":        len(t),
        "avg_trade_inr":     round(t.pnl.mean(), 2),
        "dd_ok":             dd_pct > -15.0,
    }


def _empty():
    return {"final_capital_inr":CAPITAL,"profit_inr":0,"return_pct":0,
            "sharpe":0,"sortino":0,"calmar":0,"max_dd_pct":0,
            "win_rate_pct":0,"profit_factor":0,"num_trades":0,
            "avg_trade_inr":0,"dd_ok":True}


# ── strategy loader ───────────────────────────────────────────────────────────
_fn_cache: dict = {}

def load_strategy_fn(name: str):
    if name in _fn_cache:
        return _fn_cache[name]
    meta = STRATEGIES[name]
    # use the strategy NAME as the module name so each file gets its own namespace
    spec = importlib.util.spec_from_file_location(f"strat_{name}", str(meta["file"]))
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn   = getattr(mod, meta["fn"])
    _fn_cache[name] = fn
    return fn


# ── grade helper ─────────────────────────────────────────────────────────────
def grade(r: dict) -> str:
    s = 0
    if r["return_pct"]    > 100: s += 20
    elif r["return_pct"]  > 50:  s += 15
    elif r["return_pct"]  > 25:  s += 10
    if r["max_dd_pct"]    > -10: s += 20
    elif r["max_dd_pct"]  > -15: s += 15
    if r["sharpe"]        > 2.5: s += 20
    elif r["sharpe"]      > 2.0: s += 15
    elif r["sharpe"]      > 1.5: s += 10
    if r["win_rate_pct"]  > 65:  s += 20
    elif r["win_rate_pct"]> 60:  s += 15
    elif r["win_rate_pct"]> 55:  s += 10
    if r["profit_factor"] > 2.5: s += 20
    elif r["profit_factor"]> 2.0: s += 15
    elif r["profit_factor"]> 1.5: s += 10
    for g, t in [("A+",90),("A",80),("B+",70),("B",60),("C",50)]:
        if s >= t:
            return g
    return "F"


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
def main():
    rows   = []
    total  = len(STRATEGIES) * len(ASSETS) * len(TIMEFRAMES)
    done   = 0
    errors = 0

    print("=" * 70)
    print("RUNNING MASTER BACKTEST")
    print(f"  Strategies : {len(STRATEGIES)}")
    print(f"  Assets     : {len(ASSETS)}")
    print(f"  Timeframes : {len(TIMEFRAMES)}")
    print(f"  Total tests: {total}")
    print(f"  Capital    : ₹{CAPITAL:,.0f}  |  Risk: 1%  |  Comm: 0.1%")
    print("=" * 70)

    for asset, ainfo in ASSETS.items():
        for tf, (n_bars, bpy, tf_style, freq) in TIMEFRAMES.items():
            seed = abs(hash(asset + tf)) % (2**31)
            raw  = make_ohlcv(n_bars, ainfo["ann_vol"], ainfo["drift"], bpy, seed)
            df   = add_indicators(raw)

            for strat_name, smeta in STRATEGIES.items():
                done += 1
                try:
                    fn  = load_strategy_fn(strat_name)
                    sig = fn(df)
                    res = backtest(df, sig, bpy)
                except Exception:
                    res    = _empty()
                    errors += 1

                g = grade(res)
                rows.append({
                    "strategy":          strat_name,
                    "source":            smeta["source"],
                    "strategy_style":    smeta["style"],
                    "asset":             asset,
                    "category":          ainfo["cat"],
                    "timeframe":         tf,
                    "tf_style":          tf_style,
                    "final_capital_inr": res["final_capital_inr"],
                    "profit_inr":        res["profit_inr"],
                    "return_pct":        res["return_pct"],
                    "sharpe":            res["sharpe"],
                    "sortino":           res["sortino"],
                    "calmar":            res["calmar"],
                    "max_dd_pct":        res["max_dd_pct"],
                    "win_rate_pct":      res["win_rate_pct"],
                    "profit_factor":     res["profit_factor"],
                    "num_trades":        res["num_trades"],
                    "avg_trade_inr":     res["avg_trade_inr"],
                    "dd_under_15pct":    "✅" if res["dd_ok"] else "❌",
                    "grade":             g,
                })

                if done % 100 == 0:
                    print(f"  [{done:>4}/{total}]  {asset:<12} {tf:<4}  {strat_name[:35]:<35}  "
                          f"ret={res['return_pct']:>7.1f}%  sh={res['sharpe']:>5.2f}  "
                          f"dd={res['max_dd_pct']:>6.1f}%  {g}")

    df_out = pd.DataFrame(rows)
    csv_path = OUT / "MASTER_BACKTEST_RESULTS.csv"
    df_out.to_csv(csv_path, index=False)
    print(f"\n✅  CSV saved → {csv_path}  ({len(df_out)} rows, {errors} errors)")
    return df_out


# ── HTML dashboard ─────────────────────────────────────────────────────────────
GRADE_COLOR = {"A+":"#00c851","A":"#28a745","B+":"#90ee90",
               "B":"#ffc107","C":"#fd7e14","F":"#dc3545"}

def build_html(df: pd.DataFrame):
    # ── best per asset ──
    best = (df.loc[df.groupby("asset")["sharpe"].idxmax()]
              .sort_values("sharpe", ascending=False)
              .reset_index(drop=True))

    # ── best per strategy ──
    strat_best = (df.loc[df.groupby("strategy")["sharpe"].idxmax()]
                    .sort_values("sharpe", ascending=False)
                    .reset_index(drop=True))

    # ── top 30 overall ──
    top30 = df.nlargest(30, "sharpe").reset_index(drop=True)

    # ── pivot: strategy vs timeframe (mean sharpe) ──
    pivot = df.pivot_table(values="sharpe", index="strategy",
                           columns="timeframe", aggfunc="mean").round(2)
    pivot_cols = ["1m","5m","15m","1h","4h","1d"]
    pivot = pivot.reindex(columns=[c for c in pivot_cols if c in pivot.columns])

    def row_color(grade_val):
        return GRADE_COLOR.get(grade_val, "#ffffff")

    def fmt_pct(v):
        color = "#00c851" if v >= 0 else "#dc3545"
        return f'<span style="color:{color};font-weight:600">{v:+.1f}%</span>'

    def fmt_sharpe(v):
        if v >= 2.0:   c = "#00c851"
        elif v >= 1.5: c = "#ffc107"
        elif v >= 0:   c = "#fd7e14"
        else:          c = "#dc3545"
        return f'<span style="color:{c};font-weight:600">{v:.3f}</span>'

    def fmt_dd(v):
        c = "#00c851" if v > -10 else ("#ffc107" if v > -15 else "#dc3545")
        return f'<span style="color:{c}">{v:.1f}%</span>'

    def table_rows(sub_df, cols):
        out = []
        for _, r in sub_df.iterrows():
            g   = r.get("grade","–")
            bg  = row_color(g)
            cells = []
            for c in cols:
                v = r[c]
                if c == "return_pct":         cell = fmt_pct(v)
                elif c in ("sharpe","sortino","calmar"): cell = fmt_sharpe(float(v))
                elif c == "max_dd_pct":       cell = fmt_dd(float(v))
                elif c == "grade":
                    cell = f'<span style="background:{bg};padding:2px 8px;border-radius:4px;font-weight:700">{v}</span>'
                elif c == "dd_under_15pct":   cell = str(v)
                elif c == "profit_inr":
                    color="#00c851" if float(v)>=0 else "#dc3545"
                    cell = f'<span style="color:{color}">₹{float(v):,.0f}</span>'
                else:
                    cell = str(v)
                cells.append(f"<td>{cell}</td>")
            out.append("<tr>" + "".join(cells) + "</tr>")
        return "\n".join(out)

    def pivot_html(piv):
        cols = list(piv.columns)
        def shade(v):
            if pd.isna(v): return "#2a2a2a","–"
            if v >= 2.0:   bg="#004d1a"; fc="#00c851"
            elif v >= 1.5: bg="#4d3800"; fc="#ffc107"
            elif v >= 0:   bg="#3a1f00"; fc="#fd7e14"
            else:          bg="#4d0000"; fc="#dc3545"
            return bg, f'<span style="color:{fc}">{v:.2f}</span>'
        rows = []
        for idx_val, row in piv.iterrows():
            cells = [f'<td style="font-weight:600;white-space:nowrap">{idx_val}</td>']
            for c in cols:
                bg, txt = shade(row.get(c, np.nan))
                cells.append(f'<td style="background:{bg};text-align:center">{txt}</td>')
            rows.append("<tr>" + "".join(cells) + "</tr>")
        header = "<tr><th>Strategy</th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
        return header + "\n".join(rows)

    # ── per-asset details (grouped) ──
    cat_order = ["Crypto","Commodity","Index","Forex","Bond","US_Stock","India_Stock"]
    df_sorted = df.sort_values(["category","asset","sharpe"], ascending=[True,True,False])

    asset_sections = []
    for cat in cat_order:
        sub = df_sorted[df_sorted["category"] == cat]
        if sub.empty:
            continue
        rows_html = []
        for asset in sub["asset"].unique():
            asub = sub[sub["asset"] == asset].sort_values("sharpe", ascending=False)
            for _, r in asub.iterrows():
                g  = r["grade"]
                bg = row_color(g)
                rows_html.append(f"""
                <tr>
                  <td><b>{r['asset']}</b></td>
                  <td>{r['strategy']}</td>
                  <td>{r['timeframe']}</td>
                  <td>{r['tf_style']}</td>
                  <td>{fmt_pct(r['return_pct'])}</td>
                  <td>{fmt_sharpe(r['sharpe'])}</td>
                  <td>{fmt_sharpe(r['sortino'])}</td>
                  <td>{fmt_dd(r['max_dd_pct'])}</td>
                  <td>{r['win_rate_pct']:.1f}%</td>
                  <td>{r['profit_factor']:.2f}</td>
                  <td>₹{r['profit_inr']:,.0f}</td>
                  <td>{r['num_trades']}</td>
                  <td>{r['dd_under_15pct']}</td>
                  <td><span style="background:{bg};padding:2px 8px;border-radius:4px;font-weight:700">{g}</span></td>
                </tr>""")
        cat_label = cat.replace("_"," ")
        asset_sections.append(f"""
        <h3 style="color:#a0c4ff;margin-top:24px">📂 {cat_label}</h3>
        <table>
          <thead><tr>
            <th>Asset</th><th>Strategy</th><th>TF</th><th>TF Style</th>
            <th>Return</th><th>Sharpe</th><th>Sortino</th><th>Max DD</th>
            <th>Win%</th><th>PF</th><th>Profit ₹</th><th>Trades</th>
            <th>DD&lt;15%</th><th>Grade</th>
          </tr></thead>
          <tbody>{"".join(rows_html)}</tbody>
        </table>""")

    # ── summary cards ──
    total_tests  = len(df)
    a_plus       = (df["grade"] == "A+").sum()
    a_grade      = (df["grade"] == "A").sum()
    dd_ok        = (df["dd_under_15pct"] == "✅").sum()
    best_row     = df.loc[df["sharpe"].idxmax()]
    best_profit  = df.loc[df["profit_inr"].idxmax()]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Master Backtest — YouTube Decoded + New-Gen Concepts</title>
<style>
  :root {{
    --bg:#0d1117; --card:#161b22; --border:#30363d;
    --text:#c9d1d9; --head:#58a6ff; --muted:#8b949e;
    --green:#3fb950; --yellow:#d29922; --red:#f85149;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ background:var(--bg); color:var(--text); font-family:'Segoe UI',sans-serif; padding:20px }}
  h1 {{ color:var(--head); font-size:1.6rem; margin-bottom:4px }}
  h2 {{ color:var(--head); font-size:1.2rem; margin:28px 0 10px }}
  h3 {{ color:#a0c4ff; font-size:1rem; margin:18px 0 8px }}
  .subtitle {{ color:var(--muted); font-size:.85rem; margin-bottom:24px }}
  .cards {{ display:flex; flex-wrap:wrap; gap:14px; margin-bottom:28px }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:10px;
           padding:16px 22px; min-width:160px; flex:1 }}
  .card .val {{ font-size:1.5rem; font-weight:700; color:var(--green) }}
  .card .lbl {{ font-size:.75rem; color:var(--muted); margin-top:4px }}
  table {{ width:100%; border-collapse:collapse; font-size:.78rem; margin-bottom:20px }}
  thead tr {{ background:#21262d }}
  th {{ padding:8px 10px; text-align:left; color:var(--head);
        border-bottom:1px solid var(--border); white-space:nowrap }}
  td {{ padding:6px 10px; border-bottom:1px solid var(--border); vertical-align:middle }}
  tr:hover td {{ background:#1c2128 }}
  .section {{ background:var(--card); border:1px solid var(--border);
              border-radius:10px; padding:18px; margin-bottom:22px; overflow-x:auto }}
  .note {{ color:var(--muted); font-size:.75rem; margin-top:8px }}
  .pill {{ display:inline-block; padding:2px 10px; border-radius:12px;
           font-size:.72rem; font-weight:600 }}
</style>
</head>
<body>

<h1>🚀 Master Backtest Results</h1>
<p class="subtitle">YouTube Decoded Strategies + New-Generation Concepts &nbsp;|&nbsp;
   Capital: ₹10,000 &nbsp;|&nbsp; Risk: 1% per trade &nbsp;|&nbsp; Commission: 0.1% &nbsp;|&nbsp;
   {total_tests:,} total tests</p>

<!-- SUMMARY CARDS -->
<div class="cards">
  <div class="card"><div class="val">{total_tests:,}</div><div class="lbl">Total Tests Run</div></div>
  <div class="card"><div class="val">{a_plus}</div><div class="lbl">A+ Grade Results</div></div>
  <div class="card"><div class="val">{a_grade}</div><div class="lbl">A Grade Results</div></div>
  <div class="card"><div class="val">{dd_ok}</div><div class="lbl">DD Under 15% ✅</div></div>
  <div class="card"><div class="val" style="color:#ffc107">{best_row['asset']} {best_row['timeframe']}</div>
       <div class="lbl">Best Sharpe: {best_row['sharpe']:.2f} — {best_row['strategy'][:25]}</div></div>
  <div class="card"><div class="val" style="color:#00c851">₹{best_profit['profit_inr']:,.0f}</div>
       <div class="lbl">Best Profit — {best_profit['asset']} {best_profit['timeframe']} {best_profit['strategy'][:20]}</div></div>
</div>

<!-- STRATEGY vs TIMEFRAME HEATMAP -->
<div class="section">
  <h2>🔥 Strategy × Timeframe Heatmap (Mean Sharpe)</h2>
  <p class="note">Average Sharpe across all 29 assets for each strategy/timeframe combination</p>
  <table><thead>{pivot_html(pivot)}</thead></table>
</div>

<!-- TOP 30 OVERALL -->
<div class="section">
  <h2>🏆 Top 30 Results (by Sharpe)</h2>
  <table>
    <thead><tr>
      <th>#</th><th>Asset</th><th>Strategy</th><th>TF</th><th>Style</th>
      <th>Return</th><th>Sharpe</th><th>Max DD</th><th>Win%</th><th>PF</th>
      <th>Profit ₹</th><th>Trades</th><th>Grade</th>
    </tr></thead>
    <tbody>
      {"".join(f'''<tr>
        <td>{i+1}</td>
        <td><b>{r['asset']}</b></td>
        <td>{r['strategy']}</td>
        <td>{r['timeframe']}</td>
        <td>{r['tf_style']}</td>
        <td>{fmt_pct(r['return_pct'])}</td>
        <td>{fmt_sharpe(r['sharpe'])}</td>
        <td>{fmt_dd(r['max_dd_pct'])}</td>
        <td>{r['win_rate_pct']:.1f}%</td>
        <td>{r['profit_factor']:.2f}</td>
        <td>₹{r['profit_inr']:,.0f}</td>
        <td>{r['num_trades']}</td>
        <td><span style="background:{row_color(r['grade'])};padding:2px 8px;border-radius:4px;font-weight:700">{r['grade']}</span></td>
      </tr>''' for i,(_,r) in enumerate(top30.iterrows()))}
    </tbody>
  </table>
</div>

<!-- BEST STRATEGY PER ASSET -->
<div class="section">
  <h2>🎯 Best Strategy per Asset (highest Sharpe)</h2>
  <table>
    <thead><tr>
      <th>Asset</th><th>Category</th><th>Best Strategy</th><th>TF</th>
      <th>Return</th><th>Sharpe</th><th>Max DD</th><th>Win%</th>
      <th>Profit ₹</th><th>Trades</th><th>DD&lt;15%</th><th>Grade</th>
    </tr></thead>
    <tbody>
      {table_rows(best, ["asset","category","strategy","timeframe",
                          "return_pct","sharpe","max_dd_pct","win_rate_pct",
                          "profit_inr","num_trades","dd_under_15pct","grade"])}
    </tbody>
  </table>
</div>

<!-- BEST TIMEFRAME PER STRATEGY -->
<div class="section">
  <h2>📊 Best Asset+Timeframe per Strategy</h2>
  <table>
    <thead><tr>
      <th>Strategy</th><th>Source</th><th>Best Asset</th><th>Best TF</th>
      <th>Return</th><th>Sharpe</th><th>Max DD</th><th>Win%</th>
      <th>Profit ₹</th><th>Grade</th>
    </tr></thead>
    <tbody>
      {table_rows(strat_best, ["strategy","source","asset","timeframe",
                                "return_pct","sharpe","max_dd_pct","win_rate_pct",
                                "profit_inr","grade"])}
    </tbody>
  </table>
</div>

<!-- ALL RESULTS BY ASSET & CATEGORY -->
<div class="section">
  <h2>📁 All Results — By Asset & Trading Style</h2>
  {"".join(asset_sections)}
</div>

<p class="note" style="margin-top:20px">
  ⚠️ Results use synthetic OHLCV data with realistic volatility/drift per asset.
  All signals execute at next-bar open (no look-ahead). 1% risk per trade, 0.1% commission, compounded.
  Produced: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')} IST
</p>
</body></html>"""

    html_path = OUT / "BACKTEST_SUMMARY_BY_ASSET_AND_STYLE.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"✅  HTML saved → {html_path}")
    return html_path


if __name__ == "__main__":
    results_df = main()
    build_html(results_df)
    print("\n🎉  COMPLETE — both output files ready.")
