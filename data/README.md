# data/

**Deliberately empty in the public repository.**

The working copy of this project holds ~1.8 GB of market data, model
artefacts and caches. None of it is published: it is regenerable, some
of it is not mine to redistribute, and four files exceed GitHub's 100 MB
limit outright.

To populate it:

```bash
python scripts/fetch_all_data.py        # OHLCV -> data/processed/
python scripts/resweep_all.py           # backtests -> data/models/
python scripts/build_strategy_leaderboard.py
```

Everything under `data/` is gitignored.
