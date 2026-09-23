# Dependency & License Audit — PROJECT TITAN-X

**docs/UPGRADE_BRIEF.md Phase 14 (mandatory).** Two parts: (1) a
consolidated, at-a-glance summary of the reference-repository license
audit `docs/REPOSITORY_INTELLIGENCE.md` already did per-repo (Groups
A-E, 15 repos) — nothing re-derived, just made scannable in one table;
(2) a genuinely new audit this session had not done before: this
platform's OWN installed Python dependencies (`requirements.txt`,
`pyproject.toml`), checked against real package metadata
(`importlib.metadata`, License-Expression/Classifier fields, and the
actual bundled LICENSE text where metadata was ambiguous) rather than
assumed from a package's reputation.

**Titan-X's own stated stack license: MIT/Apache** (per the brief). Per
the brief's own instruction: **flag every GPL/AGPL/proprietary repo or
dependency before integrating** — several of these were already
integrated before this pass, so "before integrating" below means "flag
now, retroactively, since the audit wasn't done at dependency-add time."

## Part 1 — Reference repositories (consolidated from REPOSITORY_INTELLIGENCE.md)

All 15 repos already have a full per-repo entry with License/Decision
fields (`docs/REPOSITORY_INTELLIGENCE.md`) and none needed correction on
review. Consolidated here for one-glance scanning:

| Repository | License | Commercial use | Copyleft? | Decision |
|---|---|---|---|---|
| NadirAliOfficial/STAR-EA-v11.20 | MIT | Yes | No | `ADAPT` (concepts only, MQL→Python) |
| manuelinfosec/profittown-sniper-smc | **None** (all rights reserved) | No | N/A | `REJECT` (also: mislabeled BOS logic) |
| mahmoud20138/Tradecraft | MIT | Yes | No | `ADAPT` (concepts only) |
| francomascareloai/EA_SCALPER_XAUUSD | **PolyForm Noncommercial 1.0.0** | **No** | No | `INSPIRE ONLY` (killzone-tiering idea only) |
| je-suis-tm/quant-trading | Apache-2.0 | Yes | No | Reuse permitted in principle |
| freqtrade/freqtrade | **GPL-3.0** | Yes (as GPL) | **Yes — copyleft** | `INSPIRE ONLY`; rule reimplemented from scratch, no source copied |
| mementum/backtrader | **GPL-3.0** | Yes (as GPL) | **Yes — copyleft** | `INSPIRE ONLY`, declined (E26 has no measurable gap to close) |
| QuantConnect/Lean | Apache-2.0 | Yes | No | Declined on cost/benefit, not license |
| WayneDW/Sentiment-Analysis | MIT | Yes | No | `REJECT` (E09's FinBERT already superior) |
| youcefbibo53/PropGuard-Trailing-Equity-Armor | None | No | N/A | `REJECT` — **confirmed malware** |
| bipbopcompany-droid/Risk-Nexus-Command | None | No | N/A | `REJECT` — **confirmed malware**, same mechanism as PropGuard |
| Eleven-Trading/TradeNote | **GPL-3.0** | Yes (as GPL) | **Yes — copyleft** | `INSPIRE ONLY`; `TradeTag.category` reimplemented from concept |
| tradicted/tradicted-journal | MIT | Yes | No | `INSPIRE ONLY`; `TradeTag.negative` reimplemented from concept |
| pramakrishn/express-option-chain | MIT | Yes | No | Reference only, no code taken |
| anurag-roy/kite-option-chain | MIT | Yes | No | Reference only, no code taken |

**3 of 15 are GPL-3.0** (freqtrade, backtrader, TradeNote) — all three
already correctly handled: zero source code copied from any of them,
every reused idea reimplemented from the concept alone, and each entry's
own "Compatibility"/"Potential reuse" fields already state the copyleft
block explicitly. **1 is PolyForm Noncommercial** (EA_SCALPER_XAUUSD) —
already correctly restricted to `INSPIRE ONLY` (an idea, not code). **2
are confirmed malware**, unrelated to licensing — already `REJECT`ed.

No action needed here; this table is a consolidation, not a correction.

## Part 2 — This platform's OWN dependencies (new audit)

Checked directly against installed package metadata
(`importlib.metadata.metadata()`'s `License`/`License-Expression` fields,
falling back to the bundled `LICENSE`/`LICENSE.md` file text when
metadata was ambiguous or the package uses a non-SPDX license string) —
not assumed from the package's reputation or PyPI page description.

### Clean (permissive — MIT/BSD/Apache-2.0, no flags)

The large majority of the dependency tree: `fastapi`, `uvicorn`,
`sqlalchemy`, `alembic`, `asyncpg`, `redis`, `qdrant-client`, `pandas`,
`polars`, `numpy`, `scipy`, `pyarrow`, `duckdb`, `yfinance`, `ta`, `ccxt`,
`nselib` (Apache-2.0, verified via its own LICENSE file — not just the
PyPI badge), `hmmlearn`, `ruptures`, `statsmodels`, `scikit-learn`,
`pydantic`, `pydantic-settings`, `python-jose`, `passlib`, `httpx`,
`python-multipart`, `structlog`, `tenacity`, `aiohttp`, `websockets`,
`feedparser`, `sentence-transformers`, `faiss-cpu`, `beautifulsoup4`,
`newspaper3k`, `lxml_html_clean`, `transformers`, `vaderSentiment`,
`textblob`, `trafilatura`, `unstructured`, `chromadb`, `langchain`,
`langchain-community`, `llama-index-core` (+ its two plugin packages),
`networkx`, `rank-bm25`, `yt-dlp` (Unlicense), `youtube-transcript-api`,
`pytest` (+ plugins), `starlette`, `ruff`, `purgedcv`, `skfolio` (BSD),
`mlfinpy` (MIT — the deliberate, already-documented substitute for
GPL/commercial `mlfinlab`), `quantstats`, `tsfresh`, `PyPortfolioOpt`,
`Riskfolio-Lib` (BSD), `mutmut`, `dvc`, `torch`, `langgraph`, `cvxpy`
(Apache-2.0), `arch` (NCSA — permissive, MIT-equivalent in practice).

### Flagged — real, previously-unflagged copyleft/restrictive licenses

| Package | Real license | Used by | Risk for THIS platform | Recommendation |
|---|---|---|---|---|
| **pymupdf** | **AGPL-3.0 OR Artifex Commercial License** (dual) | E01 Knowledge, PDF ingestion | AGPL's network-use clause triggers on distributing/hosting a modified/derivative work for others — Titan-X is not distributed, sold, or hosted as a service to third parties (Rule 5, loopback-bound by default, single-user research tool). Practically low risk **today**. | Do not distribute this platform (or a hosted version of it) to any third party while pymupdf stays AGPL-licensed without a paid Artifex commercial license. If that posture ever changes, swap to `pypdf` or keep using `pdfplumber` (already a dependency, MIT) for the PDF path. |
| **ebooklib** | **AGPL-3.0-or-later** | E01 Knowledge, EPUB ingestion | Same AGPL network-use consideration as pymupdf; EPUB ingestion is a narrow, non-core feature. | Same as above — low risk while private/non-distributed; revisit if this platform is ever shared or hosted. |
| **wbdata** | **GPL-2.0-or-later** | E04 Macro Intelligence, World Bank indicators | GPL's copyleft trigger is about DISTRIBUTING a combined/derivative work; Titan-X calls wbdata's public API as a library, doesn't vendor or modify its source, and isn't distributed. Low practical risk, but real and previously unflagged. | No immediate action; if this platform is ever open-sourced or redistributed, either keep wbdata (dynamic linking to a GPL library from a separate, non-distributed program is broadly accepted, if legally contested in edge cases) or replace with a direct World Bank API client. |
| **finta** | **LGPLv3+** | Confirmed live: `engines/e07_technical/engine.py` (`from finta import TA as FintaTA`) | LGPL is materially weaker than GPL/AGPL: using an unmodified LGPL library from separate code is standard, permitted practice. | No action needed; noted for completeness since the brief asks about "dependency licenses" broadly, not only GPL/AGPL. |
| **vectorbt** | **Apache-2.0 WITH Commons Clause** ("fair-code," not plain Apache-2.0 — verified from the actual bundled LICENSE.md, not the PyPI-reported "Apache-2.0" shorthand) | Declared in requirements.txt; confirmed via grep **not imported anywhere in `engines/`, `core/`, or `api/`** — installed but currently unused. | Commons Clause forbids **selling** the software, defined broadly as offering a paid product/service whose value derives substantially from it (including paid hosting). Moot today since it's not even wired in. | If it's ever actually wired in: do not build a paid product or paid hosted service around this platform while vectorbt stays a real dependency, without contacting the author for a license exception (a contact path is stated directly in vectorbt's own LICENSE.md). No issue for internal/personal research use. Otherwise, consider whether it's needed in requirements.txt at all. |
| **backtrader** | **GPL-3.0-or-later** | Reference/comparison-only per its own requirements.txt comment ("E26 is this platform's own validated backtesting laboratory, not replaced by this") | None currently — installed for comparison, not imported into any live engine; consistent with the Group B repo audit above (same repo, same GPL flag, same "no code taken" conclusion). | No action; keep it comparison-only as already documented. |
| **hypothesis** | **MPL-2.0** | Test-only (property-based testing, per Phase 17's own testing plan) | MPL is a weak, file-level copyleft that only triggers on modifying MPL-licensed files themselves; a test-only dependency never distributed as part of the product carries no practical risk. | No action. |
| **psycopg2-binary** | **LGPL with the PostgreSQL project's own explicit linking exception** | E02/core.database, the Postgres driver | This is the standard, extremely common case explicitly designed to make LGPL safe for ordinary use (the exception exists specifically so applications can link against it without becoming LGPL themselves). | No action — verified fine, not a real concern despite the LGPL label. |

### Unresolved (needs one follow-up check, not fabricated here)

- **pandas-ta**: PyPI/package metadata points to `pandas-ta.dev/legal/license/`
  rather than embedding a resolvable SPDX identifier or bundled LICENSE
  file text in this environment; not independently re-verified this pass
  rather than guessed. Recommend a direct check of that page (or the
  GitHub repo's LICENSE file) before the next dependency review, though
  historically this project has been MIT-licensed.

## Bottom line

**No dependency here requires immediate action.** Every flagged license
(AGPL x2, GPL x1 beyond the already-known reference-only backtrader,
Apache+Commons-Clause x1) is a real, previously-unflagged finding, but
every one of them is low-risk **specifically because of how this platform
is actually used today**: a private, single-user, non-distributed,
non-hosted, no-execution-engine research tool (Rule 5). The risk in every
flagged row is conditional on a FUTURE change to that posture
(open-sourcing, distributing, or selling/hosting this platform or a
derivative of it) — worth re-reading this table if that ever becomes a
real plan, not worth acting on today.
