"""
Package: e24_strategy_research.plugins
Description: Strategy plugins ported from the external repos audited during
    this project (each cloned read-only for reference). Every strategy here
    is a REAL port of logic that exists in the named source repo -- with
    the source file cited in its docstring, adaptations to this platform's
    close-based signal-series model documented, and any bug found in the
    source fixed and called out, never silently copied. Registered into
    e24's STRATEGIES dict (see strategies.py's merge at the bottom of that
    module), so E26 validation, sweep reporting, promotion, and E51 live
    driving all treat them exactly like the built-in archetypes -- same
    unweakened validation bar.

    Full registry of audited reference repos (the links provided by the
    user across this project; groups match the audit sections in CLAUDE.md):

    ICT/SMC group:
    - https://github.com/NadirAliOfficial/STAR-EA-v11.20
    - https://github.com/manuelinfosec/profittown-sniper-smc
    - https://github.com/mahmoud20138/Tradecraft
    - https://github.com/francomascareloai/EA_SCALPER_XAUUSD
    India/option-chain group:
    - https://github.com/pramakrishn/express-option-chain
    - https://github.com/anurag-roy/kite-option-chain
    Journal group:
    - https://github.com/Eleven-Trading/TradeNote
    - https://github.com/tradicted/tradicted-journal
    Risk/prop group:
    - https://github.com/youcefbibo53/PropGuard-Trailing-Equity-Armor
    - https://github.com/bipbopcompany-droid/Risk-Nexus-Command
    Frameworks/research group:
    - https://github.com/freqtrade/freqtrade
    - https://github.com/hummingbot/hummingbot
    - https://github.com/QuantConnect/Lean
    - https://github.com/mementum/backtrader
    - https://github.com/WayneDW/Sentiment-Analysis-in-Event-Driven-Stock-Price-Movement-Prediction
    - https://github.com/je-suis-tm/quant-trading

    Not every repo yields a plugin strategy: the journal/risk/option-chain
    repos were already mined into other parts of the platform (mistake
    tagging, trailing-drawdown guard, NSE option chain -- see CLAUDE.md's
    audit sections), hummingbot is market-making/execution (out of scope
    per Rule 5: no execution engine), Lean/backtrader contributed
    infrastructure lessons (E24's process-parallel search), and the
    sentiment repo's event-driven ML needs labeled news data this
    platform's backtests don't have. The strategies below come from the
    repos whose actual signal logic is portable to an OHLCV series model.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-21
"""

from project_titan_x.engines.e24_strategy_research.plugins.smc_sniper import smc_bos_ob_confluence
from project_titan_x.engines.e24_strategy_research.plugins.ict_star_ea import (
    ict_fvg_retrace,
    ict_fvg_retrace_killzone,
)
from project_titan_x.engines.e24_strategy_research.plugins.freqtrade_sample import freqtrade_rsi_tema_bb
from project_titan_x.engines.e24_strategy_research.plugins.dual_thrust import dual_thrust, heikin_ashi_trend
from project_titan_x.engines.e24_strategy_research.plugins.london_breakout import (
    london_breakout,
    london_breakout_buffered,
)
from project_titan_x.engines.e24_strategy_research.plugins.quant_trading_classics import (
    awesome_oscillator,
    parabolic_sar,
    shooting_star,
)
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library import (
    PDF_LIBRARY_STRATEGIES,
)
from project_titan_x.engines.e24_strategy_research.plugins.style_library import (
    STYLE_LIBRARY_STRATEGIES,
)

PLUGIN_STRATEGIES = {
    "smc_bos_ob_confluence": smc_bos_ob_confluence,
    "ict_fvg_retrace": ict_fvg_retrace,
    "ict_fvg_retrace_killzone": ict_fvg_retrace_killzone,
    "freqtrade_rsi_tema_bb": freqtrade_rsi_tema_bb,
    "dual_thrust": dual_thrust,
    "heikin_ashi_trend": heikin_ashi_trend,
    "london_breakout": london_breakout,
    "london_breakout_buffered": london_breakout_buffered,
    "awesome_oscillator": awesome_oscillator,
    "parabolic_sar": parabolic_sar,
    "shooting_star": shooting_star,
    # 90 user-supplied PDF/DOCX strategy documents, converted 2026-09-12 -- see
    # pdf_strategy_library/__init__.py's own docstring for the full description
    # and each individual module for its exact source document(s) + any
    # interpretive assumption made converting it to this platform's interface.
    **PDF_LIBRARY_STRATEGIES,
}

# The strategies_by_style/ tree, registered 2026-09-14. These had NEVER been
# evaluated by any sweep -- zero of their names appeared in STRATEGIES, so
# every backtest this project ever ran searched a different library and
# these sat on disk as dead code. Two real bugs had to be fixed before they
# could run at all (a silent all-zero return when upper-case indicator
# columns were absent, and 13 files whose function names were not valid
# Python identifiers); 37 further files contain no entry logic whatsoever
# and are skipped. See style_library/__init__.py and _adapter.py.
#
# Added via an explicit collision-safe loop rather than `**` unpacking:
# dict unpacking lets the LAST mapping win, so a name clash would silently
# replace an established, already-validated archetype with a newer,
# less-vetted file -- and the replacement would be invisible (same key,
# different function). Established names win here, and any clash is raised
# rather than merged, because a silent swap of what a validated override
# points at is exactly the kind of change that must never happen quietly.
_clashes = sorted(set(STYLE_LIBRARY_STRATEGIES) & set(PLUGIN_STRATEGIES))
if _clashes:
    raise RuntimeError(
        f"style_library strategy name(s) collide with already-registered archetypes: {_clashes}. "
        "Rename the style_library file(s) -- silently replacing a validated archetype would "
        "change what existing strategy_override.json files resolve to."
    )
PLUGIN_STRATEGIES.update(STYLE_LIBRARY_STRATEGIES)
