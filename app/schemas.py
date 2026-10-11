from datetime import date, datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class StudentBase(BaseModel):
    student_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class StudentCreate(StudentBase):
    pass


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class StudentOut(StudentBase):
    id: int
    total_due: int = 0
    total_paid: int = 0
    total_outstanding: int = 0
    advance_credit: int = 0

    model_config = ConfigDict(from_attributes=True)


class InvoiceFeeItemOut(BaseModel):
    id: int
    invoice_id: int
    fee_head: str
    amount: int
    priority: int
    amount_applied: int = 0

    model_config = ConfigDict(from_attributes=True)


class InvoiceBase(BaseModel):
    invoice_id: str
    student_id: str
    description: str = "Tuition Fee"
    amount_due: int  # in paise
    due_date: date


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceUpdate(BaseModel):
    description: Optional[str] = None
    amount_due: Optional[int] = None
    due_date: Optional[date] = None


class InvoiceOut(InvoiceBase):
    id: int
    status: str
    paid_amount: int = 0
    outstanding_amount: int = 0
    student_name: Optional[str] = None
    fee_items: List[InvoiceFeeItemOut] = []

    model_config = ConfigDict(from_attributes=True)


class RefundVoucherOut(BaseModel):
    id: int
    voucher_number: str
    payment_id: int
    student_id: Optional[str] = None
    amount: int
    action_type: str
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OverpaidActionRequest(BaseModel):
    action_type: Optional[str] = None
    action: Optional[str] = None
    note: Optional[str] = None

    @property
    def get_action_type(self) -> str:
        return self.action_type or self.action or "issue_refund"


class AllocationOut(BaseModel):
    id: int
    payment_id: int
    invoice_id: int
    invoice_ref: Optional[str] = None
    amount_applied: int

    model_config = ConfigDict(from_attributes=True)


class ExceptionBrief(BaseModel):
    id: int
    payment_id: int
    reason_code: str
    detail: str
    suggested_action: Optional[str] = None
    resolved: bool
    resolution_note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentCreate(BaseModel):
    txn_ref: Optional[str] = None
    student_ref: Optional[str] = None
    invoice_ref: Optional[str] = None
    payer_name: Optional[str] = None
    amount: Any  # can be int paise, float rupees, or string with currency symbols
    method: Optional[str] = "OTHER"
    payment_date: Any  # can be date object or string formatted date


class PaymentOut(BaseModel):
    id: int
    txn_ref: Optional[str] = None
    student_ref: Optional[str] = None
    invoice_ref: Optional[str] = None
    payer_name: Optional[str] = None
    amount: int
    method: str
    payment_date: date
    match_status: str
    matched_student_id: Optional[str] = None
    matched_student_name: Optional[str] = None
    matched_invoice_id: Optional[str] = None
    confidence_score: int
    match_reason: Optional[str] = None
    batch_id: Optional[int] = None
    created_at: datetime
    allocations: List[AllocationOut] = []
    exceptions: List[ExceptionBrief] = []

    model_config = ConfigDict(from_attributes=True)


class PaymentBrief(BaseModel):
    id: int
    txn_ref: Optional[str] = None
    student_ref: Optional[str] = None
    invoice_ref: Optional[str] = None
    payer_name: Optional[str] = None
    amount: int
    method: str
    payment_date: date
    match_status: str

    model_config = ConfigDict(from_attributes=True)


class ExceptionOut(BaseModel):
    id: int
    payment_id: int
    reason_code: str
    detail: str
    suggested_action: Optional[str] = None
    resolved: bool
    resolution_note: Optional[str] = None
    created_at: datetime
    payment: Optional[PaymentOut] = None

    model_config = ConfigDict(from_attributes=True)


class ExceptionResolve(BaseModel):
    action: str  # assign_to_student, accept_partial, mark_duplicate, dismiss
    note: Optional[str] = None
    student_id: Optional[str] = None
    invoice_id: Optional[str] = None


class ExceptionUpdate(BaseModel):
    resolution_note: Optional[str] = None
    suggested_action: Optional[str] = None


class ImportBatchOut(BaseModel):
    id: int
    filename: str
    total_rows: int
    matched: int
    duplicates: int
    partial: int
    unmatched: int
    invalid: int
    review: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentBatchResponse(BaseModel):
    batch: ImportBatchOut
    payments: List[PaymentOut]


class ReportSummary(BaseModel):
    total_due: int
    total_received: int
    total_outstanding: int
    collection_rate: float
    invoice_status_counts: Dict[str, int]
    payment_status_counts: Dict[str, int]
    open_exceptions_by_reason: Dict[str, int]
    total_students: int
    total_invoices: int
    total_payments: int
    open_exceptions_count: int
    awaiting_review_count: int = 0
    awaiting_review_amount: int = 0
