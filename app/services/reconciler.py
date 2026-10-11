from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import random
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Student, Invoice, Payment, Allocation, ExceptionRecord, ImportBatch, InvoiceFeeItem, RefundVoucher
from app.services.normalizer import normalize_payment_row
from app.services.matcher import match_payment_record, MatchResult
from app.services.scoring import compute_confidence_score


def ensure_invoice_fee_items(db: Session, invoice: Invoice) -> List[InvoiceFeeItem]:
    """
    Ensures that an invoice has itemized fee heads.
    If none exist, creates default itemized heads:
      1. Tuition Fee (Priority 1, 70% of amount_due)
      2. Examination Fee (Priority 2, 10% of amount_due)
      3. Hostel & Mess Fee (Priority 3, 15% of amount_due)
      4. Transport & Library (Priority 4, 5% of amount_due)
    """
    existing = getattr(invoice, "fee_items", []) or []
    if existing and len(existing) > 0:
        return sorted(existing, key=lambda x: x.priority)

    total = invoice.amount_due
    tuition = int(total * 0.70)
    exam = int(total * 0.10)
    hostel = int(total * 0.15)
    transport = max(0, total - (tuition + exam + hostel))

    items = [
        InvoiceFeeItem(invoice_id=invoice.id, fee_head="Tuition Fee", amount=tuition, priority=1, amount_applied=0),
        InvoiceFeeItem(invoice_id=invoice.id, fee_head="Examination Fee", amount=exam, priority=2, amount_applied=0),
        InvoiceFeeItem(invoice_id=invoice.id, fee_head="Hostel & Mess Fee", amount=hostel, priority=3, amount_applied=0),
        InvoiceFeeItem(invoice_id=invoice.id, fee_head="Transport & Library", amount=transport, priority=4, amount_applied=0),
    ]
    if db is not None:
        for item in items:
            db.add(item)
        db.flush()
    invoice.fee_items = items
    return sorted(invoice.fee_items, key=lambda x: x.priority)


def allocate_fee_heads(db: Optional[Session], invoice: Invoice, total_paid: int) -> None:
    """
    Allocates total_paid across itemized fee heads in order of priority (1 -> 2 -> 3 -> 4).
    """
    fee_items = ensure_invoice_fee_items(db, invoice)
    rem = total_paid
    for item in fee_items:
        apply_amount = min(rem, item.amount)
        item.amount_applied = apply_amount
        rem = max(0, rem - apply_amount)
    if db is not None:
        db.flush()


def derive_invoice_status(amount_due: int, paid: int, due_date: date, today: Optional[date] = None) -> str:
    """
    Derives invoice status from amount_due, total paid, and due_date:
      paid == 0 and due_date >= today -> Pending
      paid == 0 and due_date < today  -> Overdue
      0 < paid < amount_due           -> Partial (or Overdue if past due date)
      paid == amount_due              -> Paid
      paid > amount_due               -> Overpaid
    """
    if today is None:
        today = date.today()

    if paid == 0:
        return "Overdue" if due_date < today else "Pending"
    elif paid == amount_due:
        return "Paid"
    elif paid > amount_due:
        return "Overpaid"
    else:  # 0 < paid < amount_due
        return "Overdue" if due_date < today else "Partial"


def recalculate_invoice_status(
    arg1: Any,
    arg2: Optional[Any] = None,
    today: Optional[date] = None,
) -> None:
    from sqlalchemy.orm import object_session

    if isinstance(arg1, Invoice):
        inv = arg1
        sess = arg2 if isinstance(arg2, Session) else None
    elif isinstance(arg2, Invoice):
        inv = arg2
        sess = arg1 if isinstance(arg1, Session) else None
    elif hasattr(arg1, "amount_due") and hasattr(arg1, "due_date"):
        inv = arg1
        sess = arg2 if isinstance(arg2, Session) else None
    elif hasattr(arg2, "amount_due") and hasattr(arg2, "due_date"):
        inv = arg2
        sess = arg1 if isinstance(arg1, Session) else None
    else:
        raise ValueError("recalculate_invoice_status requires an Invoice instance")

    if sess is None:
        sess = object_session(inv)

    if sess is not None and getattr(inv, "id", None) is not None:
        paid = (
            sess.query(func.coalesce(func.sum(Allocation.amount_applied), 0))
            .filter(Allocation.invoice_id == inv.id)
            .scalar()
            or 0
        )
    else:
        paid = sum(a.amount_applied for a in getattr(inv, "allocations", []))

    inv.status = derive_invoice_status(inv.amount_due, paid, inv.due_date, today)
    allocate_fee_heads(sess, inv, paid)

    if sess is not None:
        sess.flush()
        try:
            sess.refresh(inv)
        except Exception:
            pass


def format_rupees(paise: int) -> str:
    """Formats paise into Indian Rupee representation, e.g. ₹1,25,000.00"""
    rupees = paise / 100.0
    return f"₹{rupees:,.2f}"


def check_duplicate(
    db: Session,
    txn_ref: Optional[str],
    student_ref: Optional[str],
    amount: int,
    method: str,
    payment_date: date,
    seen_txn_refs: Dict[str, int],
    exclude_payment_id: Optional[int] = None,
) -> Tuple[bool, bool, Optional[int], Optional[str]]:
    """
    Checks for exact duplicates or suspected duplicates.
    Returns (is_exact_dup, is_suspected_dup, original_payment_id, note).
    """
    # 1. Exact duplicate on txn_ref
    if txn_ref:
        # Check in current batch memory
        if txn_ref in seen_txn_refs:
            orig_id = seen_txn_refs[txn_ref]
            if not exclude_payment_id or orig_id != exclude_payment_id:
                return True, False, orig_id, f"Duplicate txn_ref '{txn_ref}' in same batch (first occurrence #{orig_id})"

        # Check in DB
        q = db.query(Payment).filter(Payment.txn_ref == txn_ref)
        if exclude_payment_id:
            q = q.filter(Payment.id != exclude_payment_id)
        existing_pmt = q.first()
        if existing_pmt and existing_pmt.match_status != "Invalid":
            return True, False, existing_pmt.id, f"Duplicate txn_ref '{txn_ref}' already recorded (payment #{existing_pmt.id})"

    # 2. Suspected duplicate (no txn_ref): same student_ref + same amount + same method within 24 hours
    if not txn_ref and student_ref:
        # Check within +/- 1 day in DB
        q = (
            db.query(Payment)
            .filter(
                Payment.student_ref == student_ref,
                Payment.amount == amount,
                Payment.method == method,
                Payment.payment_date >= (payment_date - timedelta(days=1)),
                Payment.payment_date <= (payment_date + timedelta(days=1)),
            )
        )
        if exclude_payment_id:
            q = q.filter(Payment.id != exclude_payment_id)
        candidate = q.first()
        if candidate and candidate.match_status != "Invalid":
            return False, True, candidate.id, "Suspected duplicate: identical student, amount, and method within 24 hours"

    return False, False, None, None


def process_single_payment(
    db: Session,
    raw_row: Dict[str, Any],
    batch_id: Optional[int] = None,
    seen_txn_refs: Optional[Dict[str, int]] = None,
    existing_payment_id: Optional[int] = None,
) -> Payment:
    """
    Executes the 5-step payment processing pipeline:
      Step 1: Normalize / Validate
      Step 2: Duplicate Detection
      Step 3: Matching Cascade
      Step 4: Amount Comparison and Allocation
      Step 5: Confidence Scoring
    """
    if seen_txn_refs is None:
        seen_txn_refs = {}

    existing_payment = None
    if existing_payment_id is not None:
        existing_payment = db.query(Payment).filter(Payment.id == existing_payment_id).first()

    # Step 1 - Normalize and validate
    norm_data, invalid_reason = normalize_payment_row(raw_row)

    if invalid_reason is not None:
        # Invalid payment row
        if existing_payment:
            existing_payment.txn_ref = norm_data["txn_ref"]
            existing_payment.student_ref = norm_data["student_ref"]
            existing_payment.invoice_ref = norm_data["invoice_ref"]
            existing_payment.payer_name = norm_data["payer_name"]
            existing_payment.amount = norm_data["amount"]
            existing_payment.method = norm_data["method"]
            existing_payment.payment_date = norm_data["payment_date"]
            existing_payment.match_status = "Invalid"
            existing_payment.confidence_score = 0
            existing_payment.match_reason = f"Validation failed: {invalid_reason}"
            
            exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == existing_payment.id).first()
            if exc:
                exc.reason_code = "INVALID_ROW"
                exc.detail = invalid_reason
                exc.suggested_action = "Correct data format or supply required fields and re-import"
                exc.resolved = False
                exc.resolution_note = None
            else:
                exc = ExceptionRecord(
                    payment_id=existing_payment.id,
                    reason_code="INVALID_ROW",
                    detail=invalid_reason,
                    suggested_action="Correct data format or supply required fields and re-import",
                    resolved=False,
                )
                db.add(exc)
            db.flush()
            return existing_payment

        payment = Payment(
            txn_ref=norm_data["txn_ref"],
            student_ref=norm_data["student_ref"],
            invoice_ref=norm_data["invoice_ref"],
            payer_name=norm_data["payer_name"],
            amount=norm_data["amount"],
            method=norm_data["method"],
            payment_date=norm_data["payment_date"],
            match_status="Invalid",
            confidence_score=0,
            match_reason=f"Validation failed: {invalid_reason}",
            batch_id=batch_id,
        )
        db.add(payment)
        db.flush()

        exc = ExceptionRecord(
            payment_id=payment.id,
            reason_code="INVALID_ROW",
            detail=invalid_reason,
            suggested_action="Correct data format or supply required fields and re-import",
            resolved=False,
        )
        db.add(exc)
        db.flush()
        return payment

    txn_ref = norm_data["txn_ref"]
    student_ref = norm_data["student_ref"]
    invoice_ref = norm_data["invoice_ref"]
    payer_name = norm_data["payer_name"]
    amount = norm_data["amount"]
    method = norm_data["method"]
    payment_date = norm_data["payment_date"]

    # Step 2 - Duplicate detection (before matching)
    is_exact_dup, is_suspected_dup, orig_id, dup_note = check_duplicate(
        db,
        txn_ref,
        student_ref,
        amount,
        method,
        payment_date,
        seen_txn_refs,
        exclude_payment_id=existing_payment.id if existing_payment else None,
    )

    if is_exact_dup:
        if existing_payment:
            existing_payment.txn_ref = txn_ref
            existing_payment.student_ref = student_ref
            existing_payment.invoice_ref = invoice_ref
            existing_payment.payer_name = payer_name
            existing_payment.amount = amount
            existing_payment.method = method
            existing_payment.payment_date = payment_date
            existing_payment.match_status = "Duplicate"
            existing_payment.confidence_score = 100
            existing_payment.match_reason = dup_note

            exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == existing_payment.id).first()
            if exc:
                exc.reason_code = "DUPLICATE"
                exc.detail = dup_note or f"Duplicate txn_ref #{orig_id}"
                exc.suggested_action = "Mark as duplicate or dismiss"
                exc.resolved = False
            else:
                exc = ExceptionRecord(
                    payment_id=existing_payment.id,
                    reason_code="DUPLICATE",
                    detail=dup_note or f"Duplicate txn_ref #{orig_id}",
                    suggested_action="Mark as duplicate or dismiss",
                    resolved=False,
                )
                db.add(exc)
            db.flush()
            return existing_payment

        payment = Payment(
            txn_ref=txn_ref,
            student_ref=student_ref,
            invoice_ref=invoice_ref,
            payer_name=payer_name,
            amount=amount,
            method=method,
            payment_date=payment_date,
            match_status="Duplicate",
            confidence_score=100,
            match_reason=dup_note,
            batch_id=batch_id,
        )
        db.add(payment)
        db.flush()

        exc = ExceptionRecord(
            payment_id=payment.id,
            reason_code="DUPLICATE",
            detail=dup_note or f"Duplicate txn_ref #{orig_id}",
            suggested_action="Mark as duplicate or dismiss",
            resolved=False,
        )
        db.add(exc)
        db.flush()
        return payment

    if is_suspected_dup:
        if existing_payment:
            existing_payment.txn_ref = txn_ref
            existing_payment.student_ref = student_ref
            existing_payment.invoice_ref = invoice_ref
            existing_payment.payer_name = payer_name
            existing_payment.amount = amount
            existing_payment.method = method
            existing_payment.payment_date = payment_date
            existing_payment.match_status = "Review"
            existing_payment.confidence_score = 70
            existing_payment.match_reason = dup_note

            exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == existing_payment.id).first()
            if exc:
                exc.reason_code = "DUPLICATE"
                exc.detail = dup_note or "Suspected duplicate payment"
                exc.suggested_action = "Review and confirm if payment was legitimate repeat"
                exc.resolved = False
            else:
                exc = ExceptionRecord(
                    payment_id=existing_payment.id,
                    reason_code="DUPLICATE",
                    detail=dup_note or "Suspected duplicate payment",
                    suggested_action="Review and confirm if payment was legitimate repeat",
                    resolved=False,
                )
                db.add(exc)
            db.flush()
            return existing_payment

        payment = Payment(
            txn_ref=txn_ref,
            student_ref=student_ref,
            invoice_ref=invoice_ref,
            payer_name=payer_name,
            amount=amount,
            method=method,
            payment_date=payment_date,
            match_status="Review",
            confidence_score=70,
            match_reason=dup_note,
            batch_id=batch_id,
        )
        db.add(payment)
        db.flush()

        exc = ExceptionRecord(
            payment_id=payment.id,
            reason_code="DUPLICATE",
            detail=dup_note or "Suspected duplicate payment",
            suggested_action="Review and confirm if payment was legitimate repeat",
            resolved=False,
        )
        db.add(exc)
        db.flush()
        return payment

    # Step 3 - Matching cascade
    match_result: MatchResult = match_payment_record(
        db=db,
        student_ref=student_ref,
        invoice_ref=invoice_ref,
        payer_name=payer_name,
        amount=amount,
    )

    # Step 4 & 5 - Amount comparison, Allocation, and Scoring
    if existing_payment:
        # Clear prior allocations if any
        old_allocs = list(existing_payment.allocations)
        for old_a in old_allocs:
            inv = old_a.invoice
            db.delete(old_a)
            db.flush()
            if inv:
                recalculate_invoice_status(db, inv)

        existing_payment.txn_ref = txn_ref
        existing_payment.student_ref = student_ref
        existing_payment.invoice_ref = invoice_ref
        existing_payment.payer_name = payer_name
        existing_payment.amount = amount
        existing_payment.method = method
        existing_payment.payment_date = payment_date
        existing_payment.match_status = match_result.status
        existing_payment.matched_student_id = match_result.student.student_id if match_result.student else None
        existing_payment.matched_invoice_id = match_result.invoice.invoice_id if match_result.invoice else None
        existing_payment.confidence_score = match_result.confidence_score
        existing_payment.match_reason = match_result.match_reason
        payment = existing_payment
    else:
        payment = Payment(
            txn_ref=txn_ref,
            student_ref=student_ref,
            invoice_ref=invoice_ref,
            payer_name=payer_name,
            amount=amount,
            method=method,
            payment_date=payment_date,
            match_status=match_result.status,
            matched_student_id=match_result.student.student_id if match_result.student else None,
            matched_invoice_id=match_result.invoice.invoice_id if match_result.invoice else None,
            confidence_score=match_result.confidence_score,
            match_reason=match_result.match_reason,
            batch_id=batch_id,
        )
        db.add(payment)
        db.flush()

    # Track seen txn_ref
    if txn_ref:
        seen_txn_refs[txn_ref] = payment.id

    # Handle Review or Unmatched matches (NEVER auto-apply)
    if match_result.status in ("Review", "Unmatched"):
        exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == payment.id).first() if existing_payment else None
        if exc:
            exc.reason_code = match_result.exception_code or "UNMATCHED"
            exc.detail = match_result.exception_detail or match_result.match_reason
            exc.suggested_action = match_result.suggested_action or "Review transaction and manually reconcile"
            exc.resolved = False
            exc.resolution_note = None
        else:
            exc = ExceptionRecord(
                payment_id=payment.id,
                reason_code=match_result.exception_code or "UNMATCHED",
                detail=match_result.exception_detail or match_result.match_reason,
                suggested_action=match_result.suggested_action or "Review transaction and manually reconcile",
                resolved=False,
            )
            db.add(exc)
        db.flush()
        return payment

    # Handle Matched candidates -> Run Allocation logic
    if invoice_ref and match_result.invoice:
        # Dedicated invoice allocation
        inv = match_result.invoice
        outstanding = inv.outstanding_amount

        if amount == outstanding:
            payment.match_status = "Matched"
            alloc = Allocation(payment_id=payment.id, invoice_id=inv.id, amount_applied=amount)
            db.add(alloc)
            db.flush()
            recalculate_invoice_status(db, inv)
            if existing_payment:
                db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == payment.id).update({
                    "resolved": True,
                    "resolution_note": "Payment re-entered and reconciled successfully",
                })

        elif amount < outstanding:
            payment.match_status = "Partial"
            alloc = Allocation(payment_id=payment.id, invoice_id=inv.id, amount_applied=amount)
            db.add(alloc)
            db.flush()
            recalculate_invoice_status(db, inv)
            rem = outstanding - amount
            exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == payment.id).first() if existing_payment else None
            if exc:
                exc.reason_code = "PARTIAL"
                exc.detail = f"Partial payment received: {format_rupees(amount)}. Remaining balance on {inv.invoice_id}: {format_rupees(rem)}"
                exc.suggested_action = "Accept partial payment or follow up for remaining balance"
                exc.resolved = False
                exc.resolution_note = None
            else:
                exc = ExceptionRecord(
                    payment_id=payment.id,
                    reason_code="PARTIAL",
                    detail=f"Partial payment received: {format_rupees(amount)}. Remaining balance on {inv.invoice_id}: {format_rupees(rem)}",
                    suggested_action="Accept partial payment or follow up for remaining balance",
                    resolved=False,
                )
                db.add(exc)
            db.flush()

        else:  # amount > outstanding
            payment.match_status = "Overpaid"
            applied = outstanding
            if applied > 0:
                alloc = Allocation(payment_id=payment.id, invoice_id=inv.id, amount_applied=applied)
                db.add(alloc)
                db.flush()
                recalculate_invoice_status(db, inv)
            excess = amount - applied
            exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == payment.id).first() if existing_payment else None
            if exc:
                exc.reason_code = "OVERPAID"
                exc.detail = f"Overpaid by {format_rupees(excess)}: Invoice {inv.invoice_id} Amount = {format_rupees(inv.amount_due)} (Applied: {format_rupees(applied)}), Payment Received = {format_rupees(amount)}. Exact Overpaid Amount = {format_rupees(excess)}."
                exc.suggested_action = "Refund excess amount or allocate to subsequent invoice"
                exc.resolved = False
                exc.resolution_note = None
            else:
                exc = ExceptionRecord(
                    payment_id=payment.id,
                    reason_code="OVERPAID",
                    detail=f"Overpaid by {format_rupees(excess)}: Invoice {inv.invoice_id} Amount = {format_rupees(inv.amount_due)} (Applied: {format_rupees(applied)}), Payment Received = {format_rupees(amount)}. Exact Overpaid Amount = {format_rupees(excess)}.",
                    suggested_action="Refund excess amount or allocate to subsequent invoice",
                    resolved=False,
                )
                db.add(exc)
            db.flush()

    elif match_result.student:
        # Student-level match (applies to oldest open invoice, carrying remainder across open invoices)
        open_invoices = match_result.open_invoices or []
        if not open_invoices:
            # Student has no open invoices! Entire amount is Overpaid
            payment.match_status = "Overpaid"
            exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == payment.id).first() if existing_payment else None
            if exc:
                exc.reason_code = "OVERPAID"
                exc.detail = f"Student {match_result.student.student_id} has no open invoices. Entire amount {format_rupees(amount)} is excess."
                exc.suggested_action = "Refund payment or retain as advance deposit"
                exc.resolved = False
                exc.resolution_note = None
            else:
                exc = ExceptionRecord(
                    payment_id=payment.id,
                    reason_code="OVERPAID",
                    detail=f"Student {match_result.student.student_id} has no open invoices. Entire amount {format_rupees(amount)} is excess.",
                    suggested_action="Refund payment or retain as advance deposit",
                    resolved=False,
                )
                db.add(exc)
            db.flush()
        else:
            remaining_amount = amount
            last_allocated_invoice = None
            for inv in open_invoices:
                out = inv.outstanding_amount
                if out <= 0:
                    continue
                to_apply = min(remaining_amount, out)
                alloc = Allocation(payment_id=payment.id, invoice_id=inv.id, amount_applied=to_apply)
                db.add(alloc)
                db.flush()
                recalculate_invoice_status(db, inv)
                remaining_amount -= to_apply
                last_allocated_invoice = inv
                if remaining_amount == 0:
                    break

            if payment.matched_invoice_id is None and last_allocated_invoice:
                payment.matched_invoice_id = last_allocated_invoice.invoice_id

            if remaining_amount > 0:
                # All open invoices paid, still excess left
                payment.match_status = "Overpaid"
                total_applied = amount - remaining_amount
                exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == payment.id).first() if existing_payment else None
                if exc:
                    exc.reason_code = "OVERPAID"
                    exc.detail = f"Overpaid by {format_rupees(remaining_amount)}: Total Applied across open invoices = {format_rupees(total_applied)}, Payment Received = {format_rupees(amount)}. Exact Overpaid Amount = {format_rupees(remaining_amount)}."
                    exc.suggested_action = "Refund excess or hold as credit for future semester"
                    exc.resolved = False
                    exc.resolution_note = None
                else:
                    exc = ExceptionRecord(
                        payment_id=payment.id,
                        reason_code="OVERPAID",
                        detail=f"Overpaid by {format_rupees(remaining_amount)}: Total Applied across open invoices = {format_rupees(total_applied)}, Payment Received = {format_rupees(amount)}. Exact Overpaid Amount = {format_rupees(remaining_amount)}.",
                        suggested_action="Refund excess or hold as credit for future semester",
                        resolved=False,
                    )
                    db.add(exc)
                db.flush()
            elif last_allocated_invoice and last_allocated_invoice.outstanding_amount > 0:
                # Last invoice has remaining balance
                payment.match_status = "Partial"
                exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == payment.id).first() if existing_payment else None
                if exc:
                    exc.reason_code = "PARTIAL"
                    exc.detail = f"Partial payment applied. Invoice {last_allocated_invoice.invoice_id} has {format_rupees(last_allocated_invoice.outstanding_amount)} outstanding balance."
                    exc.suggested_action = "Accept partial payment or request balance"
                    exc.resolved = False
                    exc.resolution_note = None
                else:
                    exc = ExceptionRecord(
                        payment_id=payment.id,
                        reason_code="PARTIAL",
                        detail=f"Partial payment applied. Invoice {last_allocated_invoice.invoice_id} has {format_rupees(last_allocated_invoice.outstanding_amount)} outstanding balance.",
                        suggested_action="Accept partial payment or request balance",
                        resolved=False,
                    )
                    db.add(exc)
                db.flush()
            else:
                payment.match_status = "Matched"
                if existing_payment:
                    db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == payment.id).update({
                        "resolved": True,
                        "resolution_note": "Payment re-entered and reconciled successfully",
                    })

    db.flush()
    db.refresh(payment)
    return payment


def reallocate_payment_to_student(
    db: Session,
    payment_id: int,
    student_id: str,
    invoice_id: Optional[str] = None,
    resolution_note: Optional[str] = None,
) -> Payment:
    """
    Re-allocates an existing payment to a specified student (and optional invoice).
    Clears old allocations, links student, and reruns allocation logic.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise ValueError(f"Payment #{payment_id} not found")

    student = db.query(Student).filter(Student.student_id == student_id).first()
    if not student:
        raise ValueError(f"Student '{student_id}' not found")

    # Clear existing allocations and recalculate impacted invoices
    old_allocations = list(payment.allocations)
    for a in old_allocations:
        inv = a.invoice
        db.delete(a)
        db.flush()
        if inv:
            recalculate_invoice_status(db, inv)

    # Update payment references
    payment.student_ref = student.student_id
    payment.matched_student_id = student.student_id
    if invoice_id:
        payment.invoice_ref = invoice_id
        payment.matched_invoice_id = invoice_id

    # If specific invoice requested
    # Mark existing exceptions for this payment as resolved
    existing_excs = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == payment.id).all()
    for e in existing_excs:
        e.resolved = True
        e.resolution_note = resolution_note or f"Manually assigned to {student.student_id}"

    target_invoice = None
    if invoice_id:
        target_invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()

    amount = payment.amount
    if target_invoice:
        outstanding = target_invoice.outstanding_amount
        payment.matched_invoice_id = target_invoice.invoice_id
        if amount == outstanding:
            payment.match_status = "Matched"
            alloc = Allocation(payment_id=payment.id, invoice_id=target_invoice.id, amount_applied=amount)
            db.add(alloc)
            db.flush()
            recalculate_invoice_status(db, target_invoice)
        elif amount < outstanding:
            payment.match_status = "Partial"
            alloc = Allocation(payment_id=payment.id, invoice_id=target_invoice.id, amount_applied=amount)
            db.add(alloc)
            db.flush()
            recalculate_invoice_status(db, target_invoice)
            exc = ExceptionRecord(
                payment_id=payment.id,
                reason_code="PARTIAL",
                detail=f"Reassigned partial payment. Outstanding: {format_rupees(target_invoice.outstanding_amount)}",
                suggested_action="Accept partial or follow up",
                resolved=True,
                resolution_note=resolution_note or f"Manually assigned to {student.student_id}",
            )
            db.add(exc)
        else:
            payment.match_status = "Overpaid"
            applied = outstanding
            if applied > 0:
                alloc = Allocation(payment_id=payment.id, invoice_id=target_invoice.id, amount_applied=applied)
                db.add(alloc)
                db.flush()
                recalculate_invoice_status(db, target_invoice)
            excess = amount - applied
            exc = ExceptionRecord(
                payment_id=payment.id,
                reason_code="OVERPAID",
                detail=f"Reassigned overpayment. Excess: {format_rupees(excess)}",
                suggested_action="Refund excess",
                resolved=True,
                resolution_note=resolution_note or f"Manually assigned to {student.student_id}",
            )
            db.add(exc)
    else:
        # Apply across student's open invoices
        open_invs = db.query(Invoice).filter(Invoice.student_id == student.student_id).order_by(Invoice.due_date.asc()).all()
        open_invoices = [inv for inv in open_invs if inv.outstanding_amount > 0]
        if not open_invoices:
            payment.match_status = "Overpaid"
            exc = ExceptionRecord(
                payment_id=payment.id,
                reason_code="OVERPAID",
                detail=f"Student {student.student_id} has no open invoices. Entire amount is excess.",
                suggested_action="Refund or hold deposit",
                resolved=True,
                resolution_note=resolution_note or f"Manually assigned to {student.student_id}",
            )
            db.add(exc)
        else:
            rem = amount
            last_inv = None
            for inv in open_invoices:
                out = inv.outstanding_amount
                to_apply = min(rem, out)
                alloc = Allocation(payment_id=payment.id, invoice_id=inv.id, amount_applied=to_apply)
                db.add(alloc)
                db.flush()
                recalculate_invoice_status(db, inv)
                rem -= to_apply
                last_inv = inv
                if rem == 0:
                    break

            payment.matched_invoice_id = last_inv.invoice_id if last_inv else None
            if rem > 0:
                payment.match_status = "Overpaid"
                exc = ExceptionRecord(
                    payment_id=payment.id,
                    reason_code="OVERPAID",
                    detail=f"Excess of {format_rupees(rem)} after satisfying all open invoices.",
                    suggested_action="Refund excess",
                    resolved=True,
                    resolution_note=resolution_note or f"Manually assigned to {student.student_id}",
                )
                db.add(exc)
            elif last_inv and last_inv.outstanding_amount > 0:
                payment.match_status = "Partial"
                exc = ExceptionRecord(
                    payment_id=payment.id,
                    reason_code="PARTIAL",
                    detail=f"Partial payment applied to {last_inv.invoice_id}. Remaining: {format_rupees(last_inv.outstanding_amount)}",
                    suggested_action="Accept partial or follow up",
                    resolved=True,
                    resolution_note=resolution_note or f"Manually assigned to {student.student_id}",
                )
                db.add(exc)
            else:
                payment.match_status = "Matched"

    payment.confidence_score = 95
    payment.match_reason = f"Manually assigned to student {student.student_id} ({student.name}). {resolution_note or ''}"
    db.flush()
    db.refresh(payment)
    return payment


def process_overpayment_action(
    db: Session,
    payment_id: int,
    action_type: str,
    note: Optional[str] = None
) -> RefundVoucher:
    """
    Processes 1-click action for an overpaid payment:
      - action_type in ('issue_refund', 'refund_voucher'): Generates RFD-YYYYMMDD-XXXX voucher.
      - action_type in ('roll_advance_credit', 'advance_credit'): Adds excess to student's advance_credit and generates CRD-YYYYMMDD-XXXX voucher.
    Resolves any open OVERPAID exception records for this payment.
    """
    pmt = db.query(Payment).filter(Payment.id == payment_id).first()
    if not pmt:
        raise ValueError(f"Payment record #{payment_id} not found")

    applied = db.query(func.coalesce(func.sum(Allocation.amount_applied), 0)).filter(Allocation.payment_id == payment_id).scalar() or 0
    excess = max(0, pmt.amount - applied)
    if excess == 0:
        excess = pmt.amount

    today_str = datetime.now().strftime("%Y%m%d")
    rand_seq = f"{random.randint(1000, 9999)}"
    student_id = pmt.matched_student_id or pmt.student_ref

    action_clean = (action_type or "").lower()

    if "refund" in action_clean:
        v_num = f"RFD-{today_str}-{rand_seq}"
        act_enum = "REFUND_VOUCHER"
        audit_note = f"Issued Refund Voucher {v_num} for exact excess {format_rupees(excess)}."
        if note:
            audit_note += f" Note: {note}"
    else:  # advance credit
        v_num = f"CRD-{today_str}-{rand_seq}"
        act_enum = "ADVANCE_CREDIT"
        audit_note = f"Rolled Forward excess {format_rupees(excess)} as Advance Credit (Voucher {v_num})."
        if note:
            audit_note += f" Note: {note}"

        if student_id:
            st = db.query(Student).filter(Student.student_id == student_id).first()
            if st:
                st.advance_credit = (st.advance_credit or 0) + excess

    voucher = RefundVoucher(
        voucher_number=v_num,
        payment_id=pmt.id,
        student_id=student_id,
        amount=excess,
        action_type=act_enum,
        note=note or audit_note,
    )
    db.add(voucher)

    # Resolve open overpaid exception
    excs = db.query(ExceptionRecord).filter(
        ExceptionRecord.payment_id == pmt.id,
        ExceptionRecord.reason_code == "OVERPAID",
        ExceptionRecord.resolved == False
    ).all()

    for exc in excs:
        exc.resolved = True
        exc.resolution_note = audit_note

    db.flush()
    db.refresh(voucher)
    return voucher
