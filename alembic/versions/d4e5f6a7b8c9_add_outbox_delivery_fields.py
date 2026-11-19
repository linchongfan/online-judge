"""add outbox delivery fields

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-19 12:00:00.000000

Adds the transactional-outbox delivery fields introduced with the
at-least-once dispatcher:

* ``nonce`` — stable per-attempt delivery id (dedup of duplicate results);
* ``next_attempt_at`` — exponential-backoff gate for transient failures.

Without this migration the API processes crash with "Unknown column" against
any database created by the existing migration chain.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('outbox_message', sa.Column('nonce', sa.String(length=64), nullable=True))
    op.add_column(
        'outbox_message',
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('outbox_message', 'next_attempt_at')
    op.drop_column('outbox_message', 'nonce')
