"""
Package: e24_strategy_research.plugins.style_library
Description: Registers the strategy files in strategies_by_style/ into
    e24's STRATEGIES dict, so they face the same E26 walk-forward bar and
    the same Stage 0 synthetic-null percentile as every other archetype.

    WHY THEY WERE NOT ALREADY REGISTERED. They were generated as a
    standalone export, never wired into the engine -- confirmed by direct
    comparison: of the 150 function names in strategies_by_style/, ZERO
    appeared in STRATEGIES. Every sweep this project has ever run searched
    the 119 archetypes in plugins/pdf_strategy_library (a SEPARATE, later
    conversion of the same source PDFs) and none of these. So they were
    dead code: shipped, documented, and never once evaluated.

    TWO REAL BUGS FOUND AND FIXED GETTING HERE (2026-09-14):

    1. Silent zero-trade failure (the user-visible symptom: "no trades in
       intraday on any pair"). Each file guards on UPPER-case indicator
       columns that nothing in the pipeline produces, and returns an
       all-zero Series when they are absent -- no exception, no log line.
       Fixed by _adapter.adapt_frame; see that module's docstring for why
       it aliases E07's real columns rather than recomputing them.
       Measured on real BTC-USD 15m: 0 positions before, 957 after.

    2. Thirteen files had function names that were not valid Python
       identifiers (`def 10ema_intraday_strategy(`, `def 9_15ema_strategy(`,
       `def ema+pivot_intraday_strategy(`) -- the generator stripped the
       `strategy_` prefix from the name while keeping it in the filename.
       Those files could never be imported at all. Renamed to match their
       own file stem, which is the convention every working file already
       follows.

    SCOPE HONESTY. These are per-asset hardcoded rules (e.g.
    strategy_intraday_btcusd tunes its thresholds for BTCUSD), not
    parameterised archetypes -- there is nothing to sweep per strategy, so
    each contributes exactly ONE candidate. Registering them still widens
    the search grid by ~150, and the Stage 0 nulls were calibrated at 167
    candidates per path (research/synthetic_null_GCF_*.json's own
    `candidates_per_path`). A wider grid means more chances for noise to
    produce a winner, so the null percentile floor gets MORE lenient
    exactly as the grid grows. That gap is already real at 723 candidates
    and this makes it larger; it is recorded here rather than silently
    accepted, and the fix is a re-run of the null campaigns at the current
    grid size, not a tweak to this module.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Callable

from project_titan_x.engines.e24_strategy_research.plugins.style_library._adapter import wrap

logger = logging.getLogger(__name__)

# strategies_by_style/ sits at the repo root, beside engines/ -- five
# parents up from this file (style_library -> plugins -> e24_... ->
# engines -> project_titan_x).
_STYLE_DIR = Path(__file__).resolve().parents[4] / "strategies_by_style"

# Boilerplate every generated file carries whether or not it contains any
# real rules: the params dict, the indicator-presence guard, the zero
# initialisation, and a `.replace(0,nan).ffill().fillna(0)` line that is a
# no-op on an all-zero series. A file with NOTHING but these has no
# trading logic at all. See _is_hollow.
_BOILERPLATE_TARGETS = {"default_params", "params", "required_indicators", "required", "missing", "signals"}


def _is_hollow(tree: ast.Module) -> bool:
    """True if no public function in `tree` contains a single statement
    beyond generated boilerplate.

    Deliberately a statement-level AST check and NOT a keyword search. A
    keyword heuristic was tried first and was wrong in both directions: it
    flagged 37 files when only 8 are genuinely empty (because the
    indicator guard's own `ind not in df.columns` comprehension looks like
    real logic), which would have silently dropped ~29 working strategies
    from the registry -- the exact class of invisible loss this package
    exists to fix.
    """
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]:
        for st in fn.body:
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
                continue  # docstring
            if isinstance(st, ast.Return):
                continue
            if isinstance(st, ast.If):
                test = ast.unparse(st.test)
                if test == "params" or "missing" in test:
                    continue  # param override / indicator-presence guard
            if isinstance(st, ast.Assign):
                target = ast.unparse(st.targets[0])
                value = ast.unparse(st.value)
                if target in ("required_indicators", "required", "missing"):
                    continue
                if target in _BOILERPLATE_TARGETS and (
                    "pd.Series(0" in value or "replace(0" in value or value.startswith("{")
                ):
                    continue
            return False  # a real statement
    return True


def _load_strategies() -> dict[str, Callable]:
    """Import every strategy file under strategies_by_style/ and return
    {name: adapted_fn}.

    Deliberately tolerant, and deliberately LOUD about what it skips: a
    single unparseable or unimportable file must not take down the whole
    engine's strategy registry (importing e24 is on the API startup path),
    but a silently missing strategy is exactly the failure mode this whole
    package exists to fix, so every skip is logged with its reason.
    """
    out: dict[str, Callable] = {}
    if not _STYLE_DIR.exists():
        logger.warning("style_library: %s not found -- no strategies registered", _STYLE_DIR)
        return out

    for path in sorted(_STYLE_DIR.rglob("*.py")):
        if path.name.startswith("__"):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except SyntaxError as e:
            logger.warning("style_library: skipping %s -- syntax error line %s: %s", path.name, e.lineno, e.msg)
            continue

        # These files follow three different conventions, all real and all
        # present in the tree -- resolved in this order:
        #   1. a function named exactly like the file stem (most files);
        #   2. `generate_signal`, with compute_*/detect_*/_* helpers
        #      alongside it (every NEW_GEN_CONCEPTS file) -- registered
        #      under the FILE stem, since "generate_signal" repeated 7
        #      times would collide;
        #   3. several `strategy_*` functions in one module, each its own
        #      strategy (WORLD_FAMOUS_STRATEGIES.py holds 5: Turtle,
        #      Connors RSI, Ichimoku, Bollinger squeeze, SuperTrend) --
        #      all registered individually;
        #   4. failing all of that, a lone top-level function.
        # Leading-underscore helpers are never registered.
        public = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        if not public:
            continue

        # HOLLOW-FILE GUARD (added 2026-09-14). Eight files in
        # GENERATED_FROM_PDF/ contain no rules at all -- the converter
        # emitted the params dict, the indicator guard, an `ffill()` over
        # an all-zero series (a no-op) and `return signals`, but never any
        # entry logic. Their docstrings show why: the "extracted rules"
        # are mangled PDF text (e.g. "has conditions.|not|genuinely|
        # shifted.|This|rule|protects"), so there was nothing coherent to
        # convert. They return zeros BY CONSTRUCTION, on any input.
        #
        # Registering them is not harmless: each adds a candidate to every
        # sweep that can never produce a trade -- wasted compute, and it
        # inflates the candidate count the Stage 0 null percentile is
        # measured against, making the bar more lenient for the strategies
        # that do work.
        #
        # All eight are superseded: the same source document was properly
        # converted into plugins/pdf_strategy_library (ali_crooks_playbook
        # -> strategy_ali_crooks_trendline_pocket, big_bar_strategy ->
        # strategy_big_bar_9ema_retest, ...), and those are registered and
        # working. Nothing is lost by skipping these.
        if _is_hollow(tree):
            logger.debug("style_library: skipping %s -- no entry logic generated (hollow file)", path.name)
            continue

        targets: list[tuple[str, str]] = []  # (registered_name, attribute_name)
        if path.stem in public:
            targets = [(path.stem, path.stem)]
        elif "generate_signal" in public:
            targets = [(path.stem, "generate_signal")]
        else:
            strategy_fns = [n for n in public if n.startswith("strategy_")]
            if strategy_fns:
                targets = [(n, n) for n in strategy_fns]
            elif len(public) == 1:
                targets = [(public[0], public[0])]
        if not targets:
            logger.debug("style_library: %s -- no recognisable strategy entry point, skipped", path.name)
            continue

        try:
            spec = importlib.util.spec_from_file_location(f"style_library.{path.stem}", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:  # noqa: BLE001 - a bad file must not break the registry
            logger.warning("style_library: skipping %s -- import failed: %s", path.name, e)
            continue

        for reg_name, attr in targets:
            fn = getattr(module, attr, None)
            if not callable(fn):
                continue
            # Some entry points take a REQUIRED second argument (e.g.
            # LEGENDARY_TRADERS' `strategy_..._fundamental_break(df, asset)`).
            # E24 calls archetypes as strat_fn(enriched, **params) with no
            # positional extras, so a required second parameter cannot be
            # satisfied -- register it and it would raise on every
            # candidate. Skipped loudly instead.
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            required_extra = [
                p for p in list(sig.parameters.values())[1:]
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]
            if required_extra:
                logger.warning(
                    "style_library: skipping %s.%s -- needs required arg(s) %s beyond the dataframe",
                    path.name, attr, [p.name for p in required_extra],
                )
                continue
            # Name collisions would silently REPLACE an existing archetype
            # in the merged STRATEGIES dict -- these files were verified to
            # have zero overlap with the registered names, so a collision
            # means something changed and is worth surfacing, not merging over.
            if reg_name in out:
                logger.warning("style_library: duplicate strategy name %r (%s) -- keeping first", reg_name, path.name)
                continue
            out[reg_name] = wrap(fn, reg_name)

    return out


STYLE_LIBRARY_STRATEGIES: dict[str, Callable] = _load_strategies()
