"""add sdk cost and duration to risk_decisions

Revision ID: e1a2b3c4d5f6
Revises: b64260ecd21f
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, Sequence[str], None] = 'b64260ecd21f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('risk_decisions', sa.Column('total_cost_usd', sa.Numeric(precision=10, scale=4), nullable=True))
    op.add_column('risk_decisions', sa.Column('sdk_duration_ms', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('risk_decisions', 'sdk_duration_ms')
    op.drop_column('risk_decisions', 'total_cost_usd')
