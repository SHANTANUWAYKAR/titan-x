# PROJECT TITAN-X — Approved YouTube Knowledge Sources

Pasted verbatim by the project owner, 2026-08-20. This is the authoritative
channel allowlist and extraction-governance policy for
`youtube_pipeline/` — same "authoritative document supersedes" precedent
as `MASTER_PROMPT.md` (see `CLAUDE.md` Rule 1). `channel_queue.json` was
reconciled against this document on 2026-08-20 (see that file's own
`_comment`); `scripts/channel_discovery.py`'s `classify_educational()`
already implements the content-type exclusion rules below and cites this
policy by name.

---

Process ONLY educational and research content.

Ignore:
- Live streams (unless educational)
- Shorts
- Market predictions
- Daily signals
- Giveaway videos
- Clickbait
- Entertainment content
- Sponsored content with no educational value

==========================================================
FOREX & MARKET STRUCTURE
==========================================================

- Mind Math Money
- No Nonsense Forex
- TradingNut
- Tradeciety
- Trading Rush
- The Secret Mindset

Extract:

- Market Structure
- Liquidity
- Trend Analysis
- Risk Management
- Trading Psychology
- Position Sizing
- Execution
- Session Analysis

==========================================================
MACRO ECONOMICS
==========================================================

- Real Vision
- Macro Voices
- Eurodollar University
- Forward Guidance

Extract:

- Business Cycles
- Liquidity
- Inflation
- Interest Rates
- Yield Curves
- Central Banks
- Currency Markets
- Risk-On / Risk-Off

==========================================================
QUANTITATIVE FINANCE
==========================================================

- QuantInsti
- Hudson & Thames
- The Quant Scientist
- QuantConnect

Extract:

- Factor Models
- Alpha Research
- Feature Engineering
- Portfolio Optimization
- Statistical Arbitrage
- Backtesting
- Machine Learning

==========================================================
OPTIONS & DERIVATIVES
==========================================================

- tastytrade
- projectfinance
- Option Alpha

Extract:

- Greeks
- Volatility
- IV
- Option Pricing
- Risk Hedging
- Volatility Trading

==========================================================
INVESTING
==========================================================

- The Plain Bagel
- Patrick Boyle
- Aswath Damodaran
- New Money
- Everything Money

Extract:

- Valuation
- DCF
- Business Analysis
- Financial Statements
- Capital Allocation
- Moats

==========================================================
CRYPTO
==========================================================

- Coin Bureau
- Bankless
- Glassnode

Extract:

- On-chain Analysis
- Stablecoins
- Exchange Flows
- Liquidity
- Market Cycles

==========================================================
INDIAN MARKETS
==========================================================

- Zerodha Varsity
- NSE India
- BSE India

Extract:

- Indian Equity Markets
- Futures & Options
- Risk Management
- Regulations

==========================================================
TRADING PSYCHOLOGY
==========================================================

- Chat With Traders

Extract:

- Emotional Control
- Discipline
- Performance
- Decision Making
- Trading Habits

==========================================================
MACHINE LEARNING & AI
==========================================================

- Machine Learning Street Talk
- DeepLearningAI
- StatQuest with Josh Starmer
- Two Minute Papers

Extract:

- Machine Learning
- Statistics
- AI
- Deep Learning
- Feature Engineering
- Model Validation

==========================================================
DATA ENGINEERING & SOFTWARE
==========================================================

- ArjanCodes
- ByteByteGo
- Hussein Nasser
- Tech With Tim

Extract:

- System Design
- APIs
- Event-Driven Architecture
- Microservices
- Databases
- Distributed Systems

==========================================================
MATHEMATICS & STATISTICS
==========================================================

- 3Blue1Brown
- StatQuest with Josh Starmer
- MIT OpenCourseWare

Extract:

- Probability
- Linear Algebra
- Calculus
- Statistics
- Bayesian Thinking
- Optimization

==========================================================
KNOWLEDGE EXTRACTION RULES
==========================================================

For every video:

Extract:

- Definitions
- Core Concepts
- Mental Models
- Frameworks
- Trading Rules
- Entry Logic
- Exit Logic
- Position Sizing
- Portfolio Rules
- Risk Rules
- Market Regimes
- Indicators
- Psychology
- Failure Conditions
- Supporting Evidence
- Limitations
- Best Practices
- Historical Examples
- Actionable Insights

Store:

- Raw Transcript
- Clean Transcript
- Structured JSON
- Embeddings (Qdrant)
- Knowledge Graph
- Evidence Graph
- Source Attribution
- Video URL
- Timestamp References

Automatically classify every extracted concept into the appropriate
Titan-X engine(s).

If a concept belongs to multiple engines, store it once and create
relationships instead of duplicating data.

Never lose source attribution.

Always preserve the original timestamp and transcript segment.

Update the Knowledge Graph and Evidence Graph after processing every
video.

Generate an Engine Distribution Report showing how much knowledge was
added to each Titan-X engine.
