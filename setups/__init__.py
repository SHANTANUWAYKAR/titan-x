"""Composed trading setups.

Deliberately separate from engines/e24_strategy_research/strategies.py. Those are
single-rule ARCHETYPES that the 830-candidate parameter sweep searches over, and
that sweep is the thing the synthetic null showed producing winners from pure
noise 150 times out of 150.

A setup here is a different object: a complete trade specification -- direction
rule, confirmation filters, a learned skip-filter, exit barriers, sizing and a
regime gate -- validated by walk-forward rather than selected as the best of a
grid. Keeping them apart stops a setup from ever being fed to that sweep, which
would reintroduce exactly the selection bias it exists to avoid.
"""
