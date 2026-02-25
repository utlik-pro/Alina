"""Initial schema - clients, messages, bookings, dialog_sessions, packages

Revision ID: 001
Revises: None
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("location_latitude", sa.Float(), nullable=True),
        sa.Column("location_longitude", sa.Float(), nullable=True),
        sa.Column("location_details", sa.String(500), nullable=True),
        sa.Column("medical_notes", sa.Text(), nullable=True),
        sa.Column("preferred_therapist", sa.String(255), nullable=True),
        sa.Column("total_bookings", sa.Integer(), server_default="0"),
        sa.Column("is_vip", sa.Boolean(), server_default="false"),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index("ix_clients_telegram_id", "clients", ["telegram_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_client_id", "messages", ["client_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("service_name", sa.String(255), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("booking_date", sa.DateTime(), nullable=True),
        sa.Column("therapist_name", sa.String(255), nullable=True),
        sa.Column("base_price", sa.Float(), nullable=True),
        sa.Column("vat_rate", sa.Float(), server_default="0.05"),
        sa.Column("vat_amount", sa.Float(), nullable=True),
        sa.Column("total_price", sa.Float(), nullable=True),
        sa.Column("payment_method", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), server_default="draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column("yclients_appointment_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bookings_client_id", "bookings", ["client_id"])
    op.create_index("ix_bookings_status", "bookings", ["status"])
    op.create_index("ix_bookings_yclients_appointment_id", "bookings", ["yclients_appointment_id"])

    op.create_table(
        "dialog_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.String(50), nullable=False),
        sa.Column("state", sa.String(50), server_default="initial"),
        sa.Column("context_data", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("is_lost_client", sa.Boolean(), server_default="false"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_activity_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dialog_sessions_telegram_id", "dialog_sessions", ["telegram_id"])
    op.create_index("ix_dialog_sessions_is_active", "dialog_sessions", ["is_active"])
    op.create_index("ix_dialog_sessions_last_activity_at", "dialog_sessions", ["last_activity_at"])

    op.create_table(
        "packages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("package_type", sa.String(100), nullable=False),
        sa.Column("sessions_total", sa.Integer(), nullable=False),
        sa.Column("sessions_used", sa.Integer(), server_default="0"),
        sa.Column("sessions_remaining", sa.Integer(), nullable=False),
        sa.Column("base_price", sa.Float(), nullable=False),
        sa.Column("vat_amount", sa.Float(), nullable=False),
        sa.Column("total_price", sa.Float(), nullable=False),
        sa.Column("purchased_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_packages_client_id", "packages", ["client_id"])
    op.create_index("ix_packages_is_active", "packages", ["is_active"])


def downgrade() -> None:
    op.drop_table("packages")
    op.drop_table("dialog_sessions")
    op.drop_table("bookings")
    op.drop_table("messages")
    op.drop_table("clients")
