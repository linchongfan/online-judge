"""remember auth session policy

Revision ID: a1b2c3d4e5f6
Revises: 8f0268c24c37
Create Date: 2026-11-04 10:00:00.000000

Adds a flag recording whether the user asked to stay logged in, so refresh
can avoid silently extending a one-day session into a long-lived one.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '8f0268c24c37'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('auth_session', sa.Column('remember', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('auth_session', 'remember')
