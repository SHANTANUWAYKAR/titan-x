"""trade journal phase9 fields

Revision ID: 88895bef5a38
Revises: ddccb3b28962
Create Date: 2026-09-13 10:10:09.137584

Hand-trimmed from the raw autogenerate output (same discipline CLAUDE.md
already documents for a prior migration): autogenerate proposed a large
batch of unrelated NOT NULL constraint tightenings on 8 other tables (real
drift between the ORM's Python-side `default=` and the live DB, but
pre-existing, out of scope for this change, and risky to apply blindly --
an ALTER COLUMN ... SET NOT NULL fails outright if any existing row is
already NULL there, which was never checked here) and a repeat of the
already-known "replace the superior 3-column ohlcv composite index with a
worse single-column one" issue. Both removed. Kept: the 6 new `trades`
columns this change actually adds, plus `ix_trades_strategy_name`/
`ix_trades_symbol` -- a real, previously-identified gap (trades.symbol/
trades.strategy_name were declared `index=True` in the ORM but the indexes
were never actually created, see CLAUDE.md's "Top-10 upgrade pass" note)
that autogenerate correctly caught still pending.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '88895bef5a38'
down_revision: Union[str, Sequence[str], None] = 'ddccb3b28962'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('trades', sa.Column('setup', sa.String(length=64), nullable=True))
    op.add_column('trades', sa.Column('timeframe', sa.String(length=10), nullable=True))
    op.add_column('trades', sa.Column('mae_r', sa.Numeric(precision=8, scale=4), nullable=True))
    op.add_column('trades', sa.Column('mfe_r', sa.Numeric(precision=8, scale=4), nullable=True))
    op.add_column('trades', sa.Column('slippage_r', sa.Numeric(precision=8, scale=4), nullable=True))
    op.add_column('trades', sa.Column('screenshot_url', sa.String(length=500), nullable=True))
    # if_not_exists: real bug found 2026-09-14 -- a genuinely FRESH database
    # (init.sql's own baseline DDL, which this migration's own docstring
    # didn't check against) already creates both indexes, since `symbol`/
    # `strategy_name` are declared `index=True` in the ORM and init.sql was
    # generated from those same models. This migration's author checked an
    # already-running, already-drifted database and found them missing
    # THERE -- true for that specific database, not true in general. Idempotent
    # either way now: a no-op on a fresh DB, still creates them on a drifted one.
    op.create_index(op.f('ix_trades_strategy_name'), 'trades', ['strategy_name'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_trades_symbol'), 'trades', ['symbol'], unique=False, if_not_exists=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_trades_symbol'), table_name='trades')
    op.drop_index(op.f('ix_trades_strategy_name'), table_name='trades')
    op.drop_column('trades', 'screenshot_url')
    op.drop_column('trades', 'slippage_r')
    op.drop_column('trades', 'mfe_r')
    op.drop_column('trades', 'mae_r')
    op.drop_column('trades', 'timeframe')
    op.drop_column('trades', 'setup')
