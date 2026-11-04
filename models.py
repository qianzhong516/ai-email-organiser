from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# Holds the shared SQLAlchemy metadata used to create the application's tables.
class Base(DeclarativeBase):
    pass


# Stores an email's mailbox identity, metadata, and decoded body for processing.
# UIDVALIDITY and UID identify a message within an account's mailbox; a new
# UIDVALIDITY represents a different mailbox generation even if UIDs are reused.
class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("account", "mailbox", "uidvalidity", "uid", name="uq_emails_mailbox_identity"),
        CheckConstraint("uidvalidity > 0 AND uid > 0", name="ck_emails_positive_imap_ids"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account: Mapped[str] = mapped_column(Text)
    mailbox: Mapped[str] = mapped_column(Text)
    uidvalidity: Mapped[int] = mapped_column(BigInteger)
    uid: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    sender: Mapped[str] = mapped_column(Text)
    date: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Tracks a classification task for an email. Status changes and result inserts
# should be committed together when the worker is integrated in a later step.
class EmailTask(Base):
    __tablename__ = "email_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_email_tasks_status",
        ),
        UniqueConstraint("id", "email_id", name="uq_email_tasks_id_email"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Stores one validated prediction per task, plus its email and model provenance.
# The composite foreign key prevents a result from referencing a task belonging
# to a different email. A new classification task may produce another result.
class Result(Base):
    __tablename__ = "results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "email_id"], ["email_tasks.id", "email_tasks.email_id"],
            name="fk_results_task_email",
        ),
        CheckConstraint("sender_type IN ('tech', 'recruitment', 'others')", name="ck_results_sender_type"),
        CheckConstraint("length(trim(explanation)) > 0", name="ck_results_explanation"),
        CheckConstraint("execution_time_seconds >= 0", name="ck_results_execution_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"), index=True)
    task_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    sender_type: Mapped[str] = mapped_column(String(20))
    explanation: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_hash: Mapped[str] = mapped_column(String(64))
    execution_time_seconds: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
