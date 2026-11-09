"""Independent accessory ownership and idempotent purchases; never grant bundled items."""
from alembic import op
import sqlalchemy as sa

revision = '20261027_107'
down_revision = '20261021_106'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('workstation_accessories',
        sa.Column('user_id',sa.Uuid(),sa.ForeignKey('users.id'),primary_key=True),
        sa.Column('accessory_number',sa.Integer(),primary_key=True),
        sa.Column('equipped',sa.Boolean(),nullable=False))
    op.create_table('workstation_accessory_purchases',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('inbound_message_id',sa.Uuid(),sa.ForeignKey('inbound_messages.id'),nullable=False,unique=True),
        sa.Column('user_id',sa.Uuid(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('group_chat_id',sa.Uuid(),sa.ForeignKey('group_chats.id'),nullable=False),
        sa.Column('accessory_number',sa.Integer(),nullable=False),
        sa.Column('price',sa.Integer(),nullable=False),
        sa.Column('result',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint('price >= 0',name='ck_workstation_accessory_price'))
    op.create_index('ix_workstation_accessory_purchases_user_id','workstation_accessory_purchases',['user_id'])


def downgrade():
    op.drop_index('ix_workstation_accessory_purchases_user_id',table_name='workstation_accessory_purchases')
    op.drop_table('workstation_accessory_purchases')
    op.drop_table('workstation_accessories')
