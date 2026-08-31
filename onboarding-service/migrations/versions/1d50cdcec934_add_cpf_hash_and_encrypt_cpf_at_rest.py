"""add cpf_hash and encrypt cpf at rest

Revision ID: 1d50cdcec934
Revises: aae1cb64efdf
Create Date: 2026-08-26 18:40:52.517014

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.crypto import compute_blind_index, decrypt_value, encrypt_value

# revision identifiers, used by Alembic.
revision: str = '1d50cdcec934'
down_revision: Union[str, Sequence[str], None] = 'aae1cb64efdf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    op.add_column('onboardings', sa.Column('cpf_hash', sa.String(), nullable=True))

    # Backfill: os registros existentes tem `cpf` em texto puro (issues
    # #2/#3, antes desta migration). Le, criptografa e calcula o
    # cpf_hash, e regrava os dois - so a partir daqui `cpf` passa a ser
    # sempre ciphertext (ver app/core/crypto.py e app/models/onboarding.py).
    rows = connection.execute(sa.text("SELECT id, cpf FROM onboardings")).fetchall()
    for row in rows:
        plaintext_cpf = row.cpf
        connection.execute(
            sa.text("UPDATE onboardings SET cpf = :cpf, cpf_hash = :cpf_hash WHERE id = :id"),
            {
                "cpf": encrypt_value(plaintext_cpf),
                "cpf_hash": compute_blind_index(plaintext_cpf),
                "id": row.id,
            },
        )

    op.alter_column('onboardings', 'cpf_hash', nullable=False)

    op.drop_index(op.f('ix_onboardings_cpf_unique_not_deleted'), table_name='onboardings', postgresql_where='(deleted_at IS NULL)')
    op.create_index('ix_onboardings_cpf_hash_unique_not_deleted', 'onboardings', ['cpf_hash'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))

    # `check_documento_reciclado` e `check_padrao_mula`
    # (app/services/onboarding_risk.py) rodam em todo POST /v1/onboarding e
    # filtram documento_numero / ip_origem / dispositivo_id + created_at +
    # deleted_at IS NULL sem indice - com a tabela crescendo (populador de
    # volume/dataset de fraude), viram sequential scan e explicam a
    # latencia p95 fora do padrao histórico (issue #59). Indices parciais
    # (deleted_at IS NULL, unica leitura relevante) cobrem os dois casos;
    # o de documento_numero tambem restringe por status='aprovado', unico
    # valor que `check_documento_reciclado` consulta.
    op.create_index(
        'ix_onboardings_documento_numero_aprovado_created_at',
        'onboardings',
        ['documento_numero', 'created_at'],
        unique=False,
        postgresql_where=sa.text("status = 'aprovado' AND deleted_at IS NULL"),
    )
    op.create_index(
        'ix_onboardings_ip_origem_created_at',
        'onboardings',
        ['ip_origem', 'created_at'],
        unique=False,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )
    op.create_index(
        'ix_onboardings_dispositivo_id_created_at',
        'onboardings',
        ['dispositivo_id', 'created_at'],
        unique=False,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_onboardings_dispositivo_id_created_at', table_name='onboardings', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_onboardings_ip_origem_created_at', table_name='onboardings', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index(
        'ix_onboardings_documento_numero_aprovado_created_at',
        table_name='onboardings',
        postgresql_where=sa.text("status = 'aprovado' AND deleted_at IS NULL"),
    )

    connection = op.get_bind()

    op.drop_index('ix_onboardings_cpf_hash_unique_not_deleted', table_name='onboardings', postgresql_where=sa.text('deleted_at IS NULL'))

    # Decifra `cpf` de volta para texto puro antes de derrubar o cpf_hash,
    # restaurando o estado anterior a esta migration.
    rows = connection.execute(sa.text("SELECT id, cpf FROM onboardings")).fetchall()
    for row in rows:
        connection.execute(
            sa.text("UPDATE onboardings SET cpf = :cpf WHERE id = :id"),
            {"cpf": decrypt_value(row.cpf), "id": row.id},
        )

    op.create_index(op.f('ix_onboardings_cpf_unique_not_deleted'), 'onboardings', ['cpf'], unique=True, postgresql_where='(deleted_at IS NULL)')
    op.drop_column('onboardings', 'cpf_hash')
