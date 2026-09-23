"""phase11_news_events

Revision ID: aa7eb4ae9c3b
Revises: 88895bef5a38
Create Date: 2026-09-13 11:30:13.740687

Hand-trimmed from the raw --autogenerate output, same as
88895bef5a38_trade_journal_phase9_fields.py before it: the raw diff also
proposed NOT NULL tightenings on ~10 unrelated pre-existing columns (drift
between models.py's own Mapped[...] declarations and what's actually live
in Postgres, present before this change and out of scope for it) and,
again, the same previously-flagged "replace idx_ohlcv_symbol_tf_ts with a
narrower ix_ohlcv_symbol" regression (see 88895bef5a38's own docstring).
Kept only the actually-intended change: the new news_events table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'aa7eb4ae9c3b'
down_revision: Union[str, Sequence[str], None] = '88895bef5a38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'news_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('link', sa.String(length=1000), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('source_timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('entities', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('event_type', sa.String(length=30), nullable=False),
        sa.Column('sentiment_label', sa.String(length=10), nullable=True),
        sa.Column('sentiment_score', sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column('market_impact_score', sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_news_events_content_hash'), 'news_events', ['content_hash'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_news_events_content_hash'), table_name='news_events')
    op.drop_table('news_events')
