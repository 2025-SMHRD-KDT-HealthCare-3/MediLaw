"""fix existing foreign keys and nullable columns

Revision ID: 20260615_0002
Revises: 20260615_0001
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260615_0002"
down_revision: Union[str, Sequence[str], None] = "20260615_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _fk_names(table_name: str) -> set[str]:
    return {fk["name"] for fk in inspect(op.get_bind()).get_foreign_keys(table_name) if fk["name"]}


def _fk_exists(table_name: str, column: str, referred_table: str, referred_column: str) -> bool:
    for fk in inspect(op.get_bind()).get_foreign_keys(table_name):
        if (
            fk["constrained_columns"] == [column]
            and fk["referred_table"] == referred_table
            and fk["referred_columns"] == [referred_column]
        ):
            return True
    return False


def _index_names(table_name: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "FK_tb_evidence_ans_id_tb_summary_summary_id" in _fk_names("tb_evidence"):
        op.drop_constraint("FK_tb_evidence_ans_id_tb_summary_summary_id", "tb_evidence", type_="foreignkey")
    if not _fk_exists("tb_evidence", "ans_id", "tb_chat", "chat_id"):
        op.create_foreign_key(
            "fk_tb_evidence_ans_id_tb_chat",
            "tb_evidence",
            "tb_chat",
            ["ans_id"],
            ["chat_id"],
        )

    if "FK_tb_verification_ans_id_tb_summary_summary_id" in _fk_names("tb_verification"):
        op.drop_constraint(
            "FK_tb_verification_ans_id_tb_summary_summary_id",
            "tb_verification",
            type_="foreignkey",
        )
    if not _fk_exists("tb_verification", "ans_id", "tb_chat", "chat_id"):
        op.create_foreign_key(
            "fk_tb_verification_ans_id_tb_chat",
            "tb_verification",
            "tb_chat",
            ["ans_id"],
            ["chat_id"],
        )

    if not _fk_exists("tb_chat", "chatter_id", "tb_user", "user_id"):
        op.create_foreign_key(
            "fk_tb_chat_chatter_id_tb_user",
            "tb_chat",
            "tb_user",
            ["chatter_id"],
            ["user_id"],
        )

    if not _fk_exists("tb_summary", "room_id", "tb_room", "room_id"):
        op.create_foreign_key(
            "fk_tb_summary_room_id_tb_room",
            "tb_summary",
            "tb_room",
            ["room_id"],
            ["room_id"],
        )

    if "ix_tb_user_login_id" not in _index_names("tb_user"):
        op.create_index("ix_tb_user_login_id", "tb_user", ["login_id"], unique=True)
    if "ix_tb_user_email" not in _index_names("tb_user"):
        op.create_index("ix_tb_user_email", "tb_user", ["email"], unique=True)

    op.alter_column("tb_user", "name", existing_type=sa.String(length=100), nullable=True)
    op.alter_column("tb_user", "phone_number", existing_type=sa.String(length=20), nullable=True)
    op.alter_column("tb_user", "email", existing_type=sa.String(length=255), nullable=True)

    op.alter_column("tb_room", "room_desc", existing_type=sa.Text(), nullable=True)
    op.alter_column("tb_room", "room_limit", existing_type=sa.Integer(), nullable=True)

    op.alter_column("tb_chat", "chatter_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("tb_chat", "chat_text", existing_type=sa.Text(), nullable=True)
    op.alter_column("tb_chat", "chat_emoticon", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("tb_chat", "chat_file", existing_type=sa.String(length=255), nullable=True)

    op.alter_column("tb_evidence", "law_name", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("tb_evidence", "article_no", existing_type=sa.String(length=100), nullable=True)
    op.alter_column("tb_evidence", "core_basis", existing_type=sa.Text(), nullable=True)

    op.alter_column("tb_verification", "law_name", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("tb_verification", "article_no", existing_type=sa.String(length=100), nullable=True)
    op.alter_column("tb_verification", "confidence_score", existing_type=sa.DECIMAL(5, 2), nullable=True)

    op.alter_column("tb_ai_ad_copy", "input_language", existing_type=sa.String(length=10), nullable=True)
    op.alter_column("tb_ai_ad_copy", "translated_text", existing_type=sa.Text(), nullable=True)
    op.alter_column("tb_ai_ad_copy", "risky_expression", existing_type=sa.Text(), nullable=True)
    op.alter_column("tb_ai_ad_copy", "legal_basis", existing_type=sa.Text(), nullable=True)
    op.alter_column("tb_ai_ad_copy", "alternative_text", existing_type=sa.Text(), nullable=True)

    op.alter_column("tb_summary", "checklist_item", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # Do not reverse these adjustments automatically on the shared campus DB.
    pass
