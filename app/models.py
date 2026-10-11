from datetime import datetime, timezone, date
from typing import List, Optional
from sqlalchemy import (
    Integer, String, Date, DateTime, Boolean, ForeignKey, Text
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.database import Base


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    advance_credit: Mapped[int] = mapped_column(Integer, default=0)  # in paise (roll forward excess credit)

    invoices: Mapped[List["Invoice"]] = relationship("Invoice", back_populates="student", cascade="all, delete-orphan")


class InvoiceFeeItem(Base):
    __tablename__ = "invoice_fee_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    invoice_id: Mapped[int] = mapped_column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    fee_head: Mapped[str] = mapped_column(String(50), nullable=False)  # Tuition | Exam | Hostel | Transport
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # in paise
    priority: Mapped[int] = mapped_column(Integer, default=1)  # 1 Highest (Tuition), 2 (Exam), 3 (Hostel), 4 (Transport)
    amount_applied: Mapped[int] = mapped_column(Integer, default=0)  # in paise

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="fee_items")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    invoice_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    student_id: Mapped[str] = mapped_column(String(50), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="Tuition Fee")
    amount_due: Mapped[int] = mapped_column(Integer, nullable=False)  # in paise
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Pending")  # Pending | Partial | Paid | Overpaid | Overdue

    student: Mapped["Student"] = relationship("Student", back_populates="invoices")
    allocations: Mapped[List["Allocation"]] = relationship("Allocation", back_populates="invoice", cascade="all, delete-orphan")
    fee_items: Mapped[List["InvoiceFeeItem"]] = relationship("InvoiceFeeItem", back_populates="invoice", cascade="all, delete-orphan")

    @property
    def paid_amount(self) -> int:
        return sum(a.amount_applied for a in self.allocations) if self.allocations else 0

    @property
    def outstanding_amount(self) -> int:
        return max(0, self.amount_due - self.paid_amount)


class RefundVoucher(Base):
    __tablename__ = "refund_vouchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    voucher_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    payment_id: Mapped[int] = mapped_column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # in paise
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)  # REFUND_VOUCHER | ADVANCE_CREDIT
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    txn_ref: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    student_ref: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    invoice_ref: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payer_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # in paise
    method: Mapped[str] = mapped_column(String(20), default="OTHER")  # UPI | NEFT | CHEQUE | DD | CASH | OTHER
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    match_status: Mapped[str] = mapped_column(String(20), nullable=False)  # Matched | Partial | Duplicate | Unmatched | Overpaid | Invalid | Review
    matched_student_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    matched_invoice_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0)
    match_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    batch_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)

    allocations: Mapped[List["Allocation"]] = relationship("Allocation", back_populates="payment", cascade="all, delete-orphan")
    exceptions: Mapped[List["ExceptionRecord"]] = relationship("ExceptionRecord", back_populates="payment", cascade="all, delete-orphan")
    batch: Mapped[Optional["ImportBatch"]] = relationship("ImportBatch", back_populates="payments")


class Allocation(Base):
    __tablename__ = "allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payment_id: Mapped[int] = mapped_column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    invoice_id: Mapped[int] = mapped_column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    amount_applied: Mapped[int] = mapped_column(Integer, nullable=False)  # in paise

    payment: Mapped["Payment"] = relationship("Payment", back_populates="allocations")
    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="allocations")


class ExceptionRecord(Base):
    __tablename__ = "exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payment_id: Mapped[int] = mapped_column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(30), nullable=False)  # DUPLICATE | PARTIAL | UNMATCHED | OVERPAID | AMBIGUOUS_MATCH | INVALID_ROW
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)

    payment: Mapped["Payment"] = relationship("Payment", back_populates="exceptions")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    partial: Mapped[int] = mapped_column(Integer, default=0)
    unmatched: Mapped[int] = mapped_column(Integer, default=0)
    invalid: Mapped[int] = mapped_column(Integer, default=0)
    review: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)

    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="batch")
