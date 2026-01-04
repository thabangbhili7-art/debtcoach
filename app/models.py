# app/models.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    BigInteger,
    ForeignKey,
    DateTime,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from .db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    phone_e164 = Column(String(32), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_payment_at = Column(DateTime, default=None)


class ConvoState(Base):
    __tablename__ = "convo_state"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    step = Column(String(64), nullable=False)
    scratch = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb")
    )


class Debt(Base):
    __tablename__ = "debts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    creditor_name = Column(String(128), nullable=False)
    balance_cents = Column(BigInteger, nullable=False)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount_cents = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

