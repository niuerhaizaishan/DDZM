"""Private resumable expedition runs."""
from alembic import op
import sqlalchemy as sa

revision = '20261022_mr_expedition'
down_revision = '20261021_129'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('mistrealm_expeditions',
        sa.Column('player_id',sa.Uuid(),sa.ForeignKey('mistrealm_players.id'),primary_key=True),
        sa.Column('state',sa.JSON(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))


def downgrade():
    op.drop_table('mistrealm_expeditions')
