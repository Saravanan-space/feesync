import csv
import io
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Student, Invoice, Payment, Allocation, ExceptionRecord


def get_summary_report(db: Session) -> Dict[str, Any]:
    """
    Computes comprehensive financial and reconciliation metrics:
      - Total due, received, outstanding, collection percentage
      - Counts by invoice status and payment match status
      - Open exceptions grouped by reason code
    """
    # Total Due
    total_due = db.query(func.coalesce(func.sum(Invoice.amount_due), 0)).scalar() or 0

    # Total Received (from allocations)
    total_received = db.query(func.coalesce(func.sum(Allocation.amount_applied), 0)).scalar() or 0

    # Total Outstanding
    total_outstanding = max(0, total_due - total_received)

    # Collection Rate %
    collection_rate = round((total_received / total_due * 100.0), 2) if total_due > 0 else 0.0

    # Invoice Status Counts
    invoice_statuses = ["Pending", "Partial", "Paid", "Overpaid", "Overdue"]
    inv_counts = {st: 0 for st in invoice_statuses}
    for row in db.query(Invoice.status, func.count(Invoice.id)).group_by(Invoice.status).all():
        if row[0] in inv_counts:
            inv_counts[row[0]] = row[1]
        else:
            inv_counts[row[0]] = row[1]

    # Payment Status Counts
    pmt_statuses = ["Matched", "Partial", "Duplicate", "Unmatched", "Overpaid", "Invalid", "Review"]
    pmt_counts = {st: 0 for st in pmt_statuses}
    for row in db.query(Payment.match_status, func.count(Payment.id)).group_by(Payment.match_status).all():
        if row[0] in pmt_counts:
            pmt_counts[row[0]] = row[1]
        else:
            pmt_counts[row[0]] = row[1]

    # Explicitly alias "Review" to "Awaiting review" for reporting
    pmt_counts["Awaiting review"] = pmt_counts.get("Review", 0)
    awaiting_review_count = pmt_counts.get("Review", 0)
    awaiting_review_amount = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.match_status == "Review")
        .scalar()
        or 0
    )

    # Open Exceptions by Reason
    exc_reasons = ["DUPLICATE", "PARTIAL", "UNMATCHED", "OVERPAID", "AMBIGUOUS_MATCH", "INVALID_ROW", "REVIEW_REQUIRED", "SETTLED_INVOICE"]
    exc_counts = {r: 0 for r in exc_reasons}
    for row in (
        db.query(ExceptionRecord.reason_code, func.count(ExceptionRecord.id))
        .filter(ExceptionRecord.resolved == False)  # noqa: E712
        .group_by(ExceptionRecord.reason_code)
        .all()
    ):
        if row[0] in exc_counts:
            exc_counts[row[0]] = row[1]
        else:
            exc_counts[row[0]] = row[1]

    total_students = db.query(func.count(Student.id)).scalar() or 0
    total_invoices = db.query(func.count(Invoice.id)).scalar() or 0
    total_payments = db.query(func.count(Payment.id)).scalar() or 0
    open_exceptions_count = (
        db.query(func.count(ExceptionRecord.id)).filter(ExceptionRecord.resolved == False).scalar() or 0  # noqa: E712
    )

    return {
        "total_due": total_due,
        "total_received": total_received,
        "total_outstanding": total_outstanding,
        "collection_rate": collection_rate,
        "invoice_status_counts": inv_counts,
        "payment_status_counts": pmt_counts,
        "open_exceptions_by_reason": exc_counts,
        "total_students": total_students,
        "total_invoices": total_invoices,
        "total_payments": total_payments,
        "open_exceptions_count": open_exceptions_count,
        "awaiting_review_count": awaiting_review_count,
        "awaiting_review_amount": awaiting_review_amount,
    }


def generate_exceptions_csv(db: Session) -> str:
    """Exports exceptions queue to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Exception ID",
        "Payment ID",
        "Txn Ref",
        "Student Ref",
        "Payer Name",
        "Amount (INR)",
        "Reason Code",
        "Detail",
        "Suggested Action",
        "Resolved",
        "Resolution Note",
        "Created At",
    ])

    exceptions = (
        db.query(ExceptionRecord)
        .join(Payment)
        .order_by(ExceptionRecord.resolved.asc(), ExceptionRecord.created_at.desc())
        .all()
    )

    for exc in exceptions:
        pmt = exc.payment
        writer.writerow([
            exc.id,
            exc.payment_id,
            pmt.txn_ref or "",
            pmt.student_ref or "",
            pmt.payer_name or "",
            f"{pmt.amount / 100.0:.2f}",
            exc.reason_code,
            exc.detail,
            exc.suggested_action or "",
            "Yes" if exc.resolved else "No",
            exc.resolution_note or "",
            exc.created_at.strftime("%Y-%m-%d %H:%M:%S") if exc.created_at else "",
        ])

    return output.getvalue()


def generate_reconciliation_csv(db: Session) -> str:
    """Exports reconciliation ledger and allocations to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Payment ID",
        "Txn Ref",
        "Student Ref",
        "Invoice Ref",
        "Payer Name",
        "Amount (INR)",
        "Method",
        "Payment Date",
        "Match Status",
        "Confidence Score",
        "Match Reason",
        "Allocated Invoices",
        "Allocated Amount (INR)",
    ])

    payments = db.query(Payment).order_by(Payment.id.desc()).all()
    for pmt in payments:
        alloc_invs = ", ".join(f"{a.invoice.invoice_id}" for a in pmt.allocations if a.invoice)
        alloc_total = sum(a.amount_applied for a in pmt.allocations)
        writer.writerow([
            pmt.id,
            pmt.txn_ref or "",
            pmt.student_ref or "",
            pmt.invoice_ref or "",
            pmt.payer_name or "",
            f"{pmt.amount / 100.0:.2f}",
            pmt.method,
            pmt.payment_date.strftime("%Y-%m-%d") if pmt.payment_date else "",
            pmt.match_status,
            pmt.confidence_score,
            pmt.match_reason or "",
            alloc_invs,
            f"{alloc_total / 100.0:.2f}",
        ])

    return output.getvalue()
