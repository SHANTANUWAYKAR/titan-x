"""phase16_option_chain_oi_snapshots

Revision ID: fead6f0f4306
Revises: aa7eb4ae9c3b
Create Date: 2026-09-13 17:13:16.814637

Hand-trimmed from the raw --autogenerate output, same as every migration
since 88895bef5a38: the raw diff also proposed NOT NULL tightenings on
~10 unrelated pre-existing columns (drift between models.py's own
Mapped[...] declarations and what's actually live in Postgres, present
before this change and out of scope for it). Kept only the actually-
intended change: the new option_chain_oi_snapshots table
(docs/UPGRADE_ROADMAP.md P1 item 5).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fead6f0f4306'
down_revision: Union[str, Sequence[str], None] = 'aa7eb4ae9c3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'option_chain_oi_snapshots',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('expiry', sa.Date(), nullable=False),
        sa.Column('strike', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('option_type', sa.String(length=2), nullable=False),
        sa.Column('oi', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'expiry', 'strike', 'option_type', 'captured_at'),
    )
    op.create_index(op.f('ix_option_chain_oi_snapshots_captured_at'), 'option_chain_oi_snapshots', ['captured_at'], unique=False)
    op.create_index(op.f('ix_option_chain_oi_snapshots_symbol'), 'option_chain_oi_snapshots', ['symbol'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_option_chain_oi_snapshots_symbol'), table_name='option_chain_oi_snapshots')
    op.drop_index(op.f('ix_option_chain_oi_snapshots_captured_at'), table_name='option_chain_oi_snapshots')
    op.drop_table('option_chain_oi_snapshots')
