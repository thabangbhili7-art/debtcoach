# app/models.py
from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, DateTime, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy import DateTime
from .db import Base
#something
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    phone_e164 = Column(String(32), unique=True, nullable=True)
    email = Column(String(255), unique=True, nullable=True)
    business_name = Column(String(128), nullable=True)
    password_hash = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_payment_at = Column(DateTime, default=None)

class ConvoState(Base):
    __tablename__ = "convo_state"

    user_id = Column(Integer, primary_key=True)  # 1 row per user
    step = Column(String(64), nullable=False)
    scratch = Column(JSONB, nullable=False, server_default="{}")

class Debt(Base):
    __tablename__ = "debts"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    creditor_name = Column(String(128), nullable=False)
    balance_cents = Column(BigInteger, nullable=False)  # store cents to avoid float issues
    original_amount_cents = Column(BigInteger, nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    next_reminder_at = Column(DateTime(timezone=True), nullable=True)

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    debt_id = Column(Integer, ForeignKey("debts.id"), nullable=True)
    amount_cents = Column(BigInteger, nullable=False)
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True)
    debt_id = Column(Integer, ForeignKey("debts.id"), nullable=False)
    send_at = Column(DateTime(timezone=True), nullable=False)
    sent = Column(Boolean, default=False, nullable=False)
