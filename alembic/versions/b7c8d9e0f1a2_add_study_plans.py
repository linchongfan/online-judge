"""add study plans

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-11-07 19:30:00.000000

Adds curated study plans with ordered problems, optional chapter groups and
per-user enrollment. Progress itself is derived from submissions, so no
progress columns are stored.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c8d9e0f1a2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'study_plan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('subtitle', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('accent', sa.String(length=20), nullable=False),
        sa.Column(
            'status',
            sa.Enum('DRAFT', 'PUBLISHED', 'ARCHIVED', name='studyplanstatus', native_enum=False),
            nullable=False,
        ),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_study_plan_status'), 'study_plan', ['status'], unique=False)
    op.create_index(op.f('ix_study_plan_title'), 'study_plan', ['title'], unique=False)

    op.create_table(
        'study_plan_problem',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('problem_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('group_name', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['study_plan.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['problem_id'], ['problem.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plan_id', 'problem_id', name='uq_study_plan_problem'),
    )
    op.create_index(op.f('ix_study_plan_problem_plan_id'), 'study_plan_problem', ['plan_id'], unique=False)
    op.create_index(op.f('ix_study_plan_problem_problem_id'), 'study_plan_problem', ['problem_id'], unique=False)
    op.create_index('ix_study_plan_problem_order', 'study_plan_problem', ['plan_id', 'position'], unique=False)

    op.create_table(
        'study_plan_enrollment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['study_plan.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plan_id', 'user_id', name='uq_study_plan_enrollment'),
    )
    op.create_index(op.f('ix_study_plan_enrollment_plan_id'), 'study_plan_enrollment', ['plan_id'], unique=False)
    op.create_index(op.f('ix_study_plan_enrollment_user_id'), 'study_plan_enrollment', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_study_plan_enrollment_user_id'), table_name='study_plan_enrollment')
    op.drop_index(op.f('ix_study_plan_enrollment_plan_id'), table_name='study_plan_enrollment')
    op.drop_table('study_plan_enrollment')
    op.drop_index('ix_study_plan_problem_order', table_name='study_plan_problem')
    op.drop_index(op.f('ix_study_plan_problem_problem_id'), table_name='study_plan_problem')
    op.drop_index(op.f('ix_study_plan_problem_plan_id'), table_name='study_plan_problem')
    op.drop_table('study_plan_problem')
    op.drop_index(op.f('ix_study_plan_title'), table_name='study_plan')
    op.drop_index(op.f('ix_study_plan_status'), table_name='study_plan')
    op.drop_table('study_plan')
