# models.py
from sqlalchemy import (
    Column, Integer, String, Float, Date, Boolean, ForeignKey, DateTime, Enum
)
from sqlalchemy.orm import relationship, declarative_base
import enum
import datetime

Base = declarative_base()

class PaymentCycle(enum.Enum):
    monthly = "monthly"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, unique=True, index=True)
    name = Column(String)
    timezone = Column(String, default="Europe/Amsterdam")

    loans = relationship("Loan", back_populates="user")

class Loan(Base):
    __tablename__ = "loans"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    bank = Column(String)
    loan_name = Column(String)
    principal = Column(Float)
    annual_interest_rate = Column(Float)
    term_months = Column(Integer)
    payment_cycle = Column(String, default="monthly")
    first_payment_date = Column(Date)  # stored as Gregorian date
    installments_paid = Column(Integer, default=0)
    reminder_days_before = Column(Integer, default=1)  # 1/2/3

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="loans")
    installments = relationship("Installment", back_populates="loan", cascade="all, delete-orphan")

class Installment(Base):
    __tablename__ = "installments"
    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, ForeignKey("loans.id"))
    sequence_number = Column(Integer)
    due_date = Column(Date)
    amount_total = Column(Float)
    amount_principal = Column(Float)
    amount_interest = Column(Float)
    is_paid = Column(Boolean, default=False)
    paid_at = Column(DateTime, nullable=True)
    paid_amount = Column(Float, nullable=True)

    loan = relationship("Loan", back_populates="installments")
