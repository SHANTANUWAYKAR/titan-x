"""
Package: research
Description: Sandbox for exploratory strategy and market research.

    DELIBERATELY SEPARATE from engines/. Nothing in the live platform
    imports this package: no engine, no API route, and no promoted
    strategy override depends on anything here. That isolation is the
    point -- work in here can be rewritten, thrown away, or proven wrong
    without touching a single thing that produces a live signal.

    The one-way dependency rule: research/ may import from engines/, but
    engines/ must NEVER import from research/. If something in here earns
    its place, it gets PORTED into engines/ deliberately (with its own
    tests and a real validation sweep), not wired up from here.

    Contents:
      ict_smc_confluence.py  -- a combined ICT/SMC strategy built on the
                                real detectors in e07_technical
                                (structure/BOS/CHoCH, liquidity sweeps,
                                order blocks, FVGs, killzones, CVD).
      news_impact.py         -- event-study analysis of how price actually
                                behaved after past news, per symbol.

    Same evidence standard as the rest of the project applies here: E26's
    unweakened validation bar, real market data, and honest reporting of
    a negative result.
Author: Shantanu Waykar
Version: 1.0.0
"""
