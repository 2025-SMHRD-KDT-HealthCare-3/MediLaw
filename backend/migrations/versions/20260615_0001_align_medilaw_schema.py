"""align medilaw schema

Revision ID: 20260615_0001
Revises:
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260615_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _columns(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if not _has_table("tb_user"):
        op.create_table(
            "tb_user",
            sa.Column("user_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("login_id", sa.String(length=50), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=True),
            sa.Column("phone_number", sa.String(length=20), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_tb_user_login_id", "tb_user", ["login_id"], unique=True)
        op.create_index("ix_tb_user_email", "tb_user", ["email"], unique=True)

    if not _has_table("tb_room"):
        op.create_table(
            "tb_room",
            sa.Column("room_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("tb_user.user_id"), nullable=False),
            sa.Column("room_title", sa.String(length=255), nullable=False),
            sa.Column("room_desc", sa.Text(), nullable=True),
            sa.Column("room_limit", sa.Integer(), nullable=True),
            sa.Column("room_status", sa.String(length=10), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _has_table("tb_chat"):
        op.create_table(
            "tb_chat",
            sa.Column("chat_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("room_id", sa.Integer(), sa.ForeignKey("tb_room.room_id"), nullable=False),
            sa.Column("chatter_id", sa.Integer(), sa.ForeignKey("tb_user.user_id"), nullable=True),
            sa.Column("speaker_type", sa.String(length=20), nullable=False),
            sa.Column("chat_text", sa.Text(), nullable=True),
            sa.Column("chat_emoticon", sa.String(length=255), nullable=True),
            sa.Column("chat_file", sa.String(length=255), nullable=True),
            sa.Column("chatted_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("speaker_type in ('USER', 'AI', 'ADMIN')", name="ck_chat_speaker_type"),
        )
    elif "speaker_type" not in _columns("tb_chat"):
        op.add_column(
            "tb_chat",
            sa.Column("speaker_type", sa.String(length=20), nullable=False, server_default="USER"),
        )
        op.create_check_constraint(
            "ck_chat_speaker_type",
            "tb_chat",
            "speaker_type in ('USER', 'AI', 'ADMIN')",
        )

    if not _has_table("tb_evidence"):
        op.create_table(
            "tb_evidence",
            sa.Column("evidence_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ans_id", sa.Integer(), sa.ForeignKey("tb_chat.chat_id"), nullable=False),
            sa.Column("law_name", sa.String(length=255), nullable=True),
            sa.Column("article_no", sa.String(length=100), nullable=True),
            sa.Column("core_basis", sa.Text(), nullable=True),
            sa.Column("source_url", sa.String(length=2048), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _has_table("tb_verification"):
        op.create_table(
            "tb_verification",
            sa.Column("verification_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ans_id", sa.Integer(), sa.ForeignKey("tb_chat.chat_id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("tb_user.user_id"), nullable=False),
            sa.Column("law_name", sa.String(length=255), nullable=True),
            sa.Column("article_no", sa.String(length=100), nullable=True),
            sa.Column("article_exists", sa.Boolean(), nullable=False),
            sa.Column("content_matches", sa.Boolean(), nullable=False),
            sa.Column("effective_date_valid", sa.Boolean(), nullable=False),
            sa.Column("verification_status", sa.String(length=20), nullable=False),
            sa.Column("confidence_score", sa.DECIMAL(5, 2), nullable=True),
            sa.Column("verification_reason", sa.Text(), nullable=True),
            sa.Column("verified_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "verification_status in ('CONFIRMED', 'WARNING', 'ERROR')",
                name="ck_verification_status",
            ),
            sa.CheckConstraint(
                "confidence_score >= 0 and confidence_score <= 100",
                name="ck_verification_confidence_score",
            ),
        )

    if not _has_table("tb_ai_ad_copy"):
        op.create_table(
            "tb_ai_ad_copy",
            sa.Column("ai_copy_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("tb_user.user_id"), nullable=False),
            sa.Column("input_language", sa.String(length=10), nullable=True),
            sa.Column("input_text", sa.Text(), nullable=False),
            sa.Column("english_text", sa.Text(), nullable=True),
            sa.Column("translated_text", sa.Text(), nullable=True),
            sa.Column("risky_expression", sa.Text(), nullable=True),
            sa.Column("legal_basis", sa.Text(), nullable=True),
            sa.Column("revision_recomm", sa.Text(), nullable=True),
            sa.Column("alternative_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    elif "revision_recommendation" in _columns("tb_ai_ad_copy") and "revision_recomm" not in _columns("tb_ai_ad_copy"):
        op.alter_column(
            "tb_ai_ad_copy",
            "revision_recommendation",
            new_column_name="revision_recomm",
            existing_type=sa.Text(),
            existing_nullable=True,
        )

    if not _has_table("tb_summary"):
        op.create_table(
            "tb_summary",
            sa.Column("summary_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("room_id", sa.Integer(), sa.ForeignKey("tb_room.room_id"), nullable=False),
            sa.Column("admin_id", sa.Integer(), sa.ForeignKey("tb_user.user_id"), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("checklist_item", sa.Text(), nullable=True),
            sa.Column("summary_file", sa.String(length=255), nullable=True),
            sa.Column("is_confirmed", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    elif "chat_summary" in _columns("tb_summary") and "summary" not in _columns("tb_summary"):
        op.alter_column(
            "tb_summary",
            "chat_summary",
            new_column_name="summary",
            existing_type=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    # This baseline migration is intentionally conservative because it may run
    # against an existing campus DB. Do not drop user data automatically.
    pass
