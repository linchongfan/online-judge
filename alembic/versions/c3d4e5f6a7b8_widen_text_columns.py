"""widen long-text columns for utf8mb4 payloads

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-11-19 09:00:00.000000

MySQL TEXT caps at 65,535 bytes, but the API accepts up to 65,536 bytes of
UTF-8 source (and solution/plan texts are validated in characters, which can
exceed the byte cap several-fold under utf8mb4). Widen the affected columns
to MEDIUMTEXT on MySQL. Other dialects (e.g. SQLite used by tests) have
unbounded TEXT, so the change is a no-op there.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = 'c3d4e5f6a7b8'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None

_MEDIUMTEXT = mysql.MEDIUMTEXT()


def upgrade() -> None:
    if op.get_bind().dialect.name != 'mysql':
        return
    op.alter_column('submission', 'source_code', existing_type=sa.Text(), type_=_MEDIUMTEXT)
    op.alter_column('solution_code', 'code', existing_type=sa.Text(), type_=_MEDIUMTEXT)
    op.alter_column('study_plan', 'description', existing_type=sa.Text(), type_=_MEDIUMTEXT)


def downgrade() -> None:
    if op.get_bind().dialect.name != 'mysql':
        return
    op.alter_column('submission', 'source_code', existing_type=_MEDIUMTEXT, type_=sa.Text())
    op.alter_column('solution_code', 'code', existing_type=_MEDIUMTEXT, type_=sa.Text())
    op.alter_column('study_plan', 'description', existing_type=_MEDIUMTEXT, type_=sa.Text())
