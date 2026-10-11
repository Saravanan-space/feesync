import csv
import io
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models import Payment, ExceptionRecord, ImportBatch, Allocation, Student, Invoice
from app.schemas import (
    PaymentCreate, PaymentOut, AllocationOut, ExceptionBrief,
    ExceptionOut, ExceptionResolve, ImportBatchOut, PaymentBatchResponse,
    OverpaidActionRequest, RefundVoucherOut
)
from app.services.reconciler import (
    process_single_payment, reallocate_payment_to_student, process_overpayment_action
)
from app.routers.students import decode_csv_file


router = APIRouter(tags=["Payments & Exceptions"])


def serialize_payment(pmt: Payment, db: Optional[Session] = None) -> PaymentOut:
    """Helper to convert Payment model into PaymentOut with allocations and exceptions."""
    allocations_out = [
        AllocationOut(
            id=a.id,
            payment_id=a.payment_id,
            invoice_id=a.invoice_id,
            invoice_ref=a.invoice.invoice_id if a.invoice else None,
            amount_applied=a.amount_applied,
        )
        for a in pmt.allocations
    ]
    exceptions_out = [
        ExceptionBrief(
            id=e.id,
            payment_id=e.payment_id,
            reason_code=e.reason_code,
            detail=e.detail,
            suggested_action=e.suggested_action,
            resolved=e.resolved,
            resolution_note=e.resolution_note,
            created_at=e.created_at,
        )
        for e in pmt.exceptions
    ]
    student_name = None
    if pmt.matched_student_id and db:
        st_obj = db.query(Student).filter(Student.student_id == pmt.matched_student_id).first()
        if st_obj:
            student_name = st_obj.name

    return PaymentOut(
        id=pmt.id,
        txn_ref=pmt.txn_ref,
        student_ref=pmt.student_ref,
        invoice_ref=pmt.invoice_ref,
        payer_name=pmt.payer_name,
        amount=pmt.amount,
        method=pmt.method,
        payment_date=pmt.payment_date,
        match_status=pmt.match_status,
        matched_student_id=pmt.matched_student_id,
        matched_student_name=student_name,
        matched_invoice_id=pmt.matched_invoice_id,
        confidence_score=pmt.confidence_score,
        match_reason=pmt.match_reason,
        batch_id=pmt.batch_id,
        created_at=pmt.created_at,
        allocations=allocations_out,
        exceptions=exceptions_out,
    )


@router.post("/api/payments/import", response_model=PaymentBatchResponse)
async def import_payments_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Imports and reconciles payments from a CSV file.
    Runs the 5-step reconciliation pipeline on every row inside a single DB transaction.
    """
    content = await file.read()
    csv_text = decode_csv_file(content)

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    if not fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file has no header row")

    try:
        batch = ImportBatch(filename=file.filename or "payments.csv")
        db.add(batch)
        db.flush()

        seen_txn_refs: Dict[str, int] = {}
        processed_payments: List[Payment] = []
        total_rows = 0
        matched_cnt = 0
        duplicates_cnt = 0
        partial_cnt = 0
        unmatched_cnt = 0
        invalid_cnt = 0
        review_cnt = 0

        for raw_row in reader:
            total_rows += 1
            # Normalize keys to lower
            row_dict = {k.strip().lower(): v for k, v in raw_row.items() if k}

            pmt = process_single_payment(
                db=db,
                raw_row=row_dict,
                batch_id=batch.id,
                seen_txn_refs=seen_txn_refs,
            )
            processed_payments.append(pmt)

            st = pmt.match_status
            if st == "Matched":
                matched_cnt += 1
            elif st == "Duplicate":
                duplicates_cnt += 1
            elif st == "Partial":
                partial_cnt += 1
            elif st == "Unmatched":
                unmatched_cnt += 1
            elif st == "Invalid":
                invalid_cnt += 1
            elif st == "Review":
                review_cnt += 1
            elif st == "Overpaid":
                # Overpaid is matched with excess
                matched_cnt += 1

        batch.total_rows = total_rows
        batch.matched = matched_cnt
        batch.duplicates = duplicates_cnt
        batch.partial = partial_cnt
        batch.unmatched = unmatched_cnt
        batch.invalid = invalid_cnt
        batch.review = review_cnt

        db.commit()
        db.refresh(batch)

        return PaymentBatchResponse(
            batch=ImportBatchOut.model_validate(batch),
            payments=[serialize_payment(p) for p in processed_payments],
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment import failed during reconciliation: {str(e)}"
        )


@router.post("/api/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_manual_payment(payment_in: PaymentCreate, db: Session = Depends(get_db)):
    """Creates and processes a single manual payment entry."""
    try:
        row_dict = payment_in.model_dump()
        pmt = process_single_payment(db=db, raw_row=row_dict)
        db.commit()
        db.refresh(pmt)
        return serialize_payment(pmt)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/api/payments", response_model=List[PaymentOut])
def list_payments(
    status_filter: Optional[str] = Query(None, alias="status"),
    method_filter: Optional[str] = Query(None, alias="method"),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Payment)

    if status_filter and status_filter.strip():
        query = query.filter(Payment.match_status.ilike(status_filter.strip()))

    if method_filter and method_filter.strip():
        query = query.filter(Payment.method.ilike(method_filter.strip()))

    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Payment.txn_ref.ilike(search),
                Payment.student_ref.ilike(search),
                Payment.invoice_ref.ilike(search),
                Payment.payer_name.ilike(search),
                Payment.matched_student_id.ilike(search),
                Payment.matched_invoice_id.ilike(search),
            )
        )

    offset = (page - 1) * page_size
    payments = query.order_by(Payment.id.desc()).offset(offset).limit(page_size).all()
    return [serialize_payment(p) for p in payments]


@router.get("/api/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: int, db: Session = Depends(get_db)):
    """Retrieves a single payment record by ID."""
    pmt = db.query(Payment).filter(Payment.id == payment_id).first()
    if not pmt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment #{payment_id} not found"
        )
    return serialize_payment(pmt, db=db)


@router.get("/api/exceptions", response_model=List[ExceptionOut])
def list_exceptions(
    reason: Optional[str] = Query(None),
    resolved: Optional[bool] = Query(None),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(ExceptionRecord).join(ExceptionRecord.payment)

    if isinstance(reason, str) and reason.strip():
        query = query.filter(ExceptionRecord.reason_code == reason.strip().upper())

    if isinstance(resolved, bool):
        query = query.filter(ExceptionRecord.resolved == resolved)

    if isinstance(q, str) and q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                ExceptionRecord.detail.ilike(search),
                Payment.txn_ref.ilike(search),
                Payment.student_ref.ilike(search),
                Payment.payer_name.ilike(search),
            )
        )

    exceptions = query.order_by(ExceptionRecord.resolved.asc(), ExceptionRecord.created_at.desc()).all()

    result = []
    for exc in exceptions:
        result.append(
            ExceptionOut(
                id=exc.id,
                payment_id=exc.payment_id,
                reason_code=exc.reason_code,
                detail=exc.detail,
                suggested_action=exc.suggested_action,
                resolved=exc.resolved,
                resolution_note=exc.resolution_note,
                created_at=exc.created_at,
                payment=serialize_payment(exc.payment, db=db) if exc.payment else None,
            )
        )
    return result


@router.get("/api/exceptions/{exception_id}", response_model=ExceptionOut)
def get_exception(exception_id: int, db: Session = Depends(get_db)):
    # 1. Lookup by ExceptionRecord.id
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.id == exception_id).first()

    # 2. Fallback: Lookup by ExceptionRecord.payment_id
    if not exc:
        exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == exception_id).first()

    # 3. Fallback: If payment exists but no exception record exists yet, create one on the fly
    if not exc:
        pmt = db.query(Payment).filter(Payment.id == exception_id).first()
        if pmt:
            exc = ExceptionRecord(
                payment_id=pmt.id,
                reason_code=pmt.match_status.upper() if pmt.match_status else "MANUAL_REVIEW",
                detail=pmt.match_reason or "Manual review or student assignment requested",
                suggested_action="Assign to student or invoice",
                resolved=False,
            )
            db.add(exc)
            db.commit()
            db.refresh(exc)

    if not exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Exception record or payment #{exception_id} not found")

    return ExceptionOut(
        id=exc.id,
        payment_id=exc.payment_id,
        reason_code=exc.reason_code,
        detail=exc.detail,
        suggested_action=exc.suggested_action,
        resolved=exc.resolved,
        resolution_note=exc.resolution_note,
        created_at=exc.created_at,
        payment=serialize_payment(exc.payment, db=db) if exc.payment else None,
    )


@router.post("/api/exceptions/{exception_id}/resolve", response_model=ExceptionOut)
def resolve_exception(
    exception_id: int,
    resolution: ExceptionResolve,
    db: Session = Depends(get_db),
):
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.id == exception_id).first()
    if not exc:
        exc = db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == exception_id).first()

    if not exc:
        pmt = db.query(Payment).filter(Payment.id == exception_id).first()
        if pmt:
            exc = ExceptionRecord(
                payment_id=pmt.id,
                reason_code=pmt.match_status.upper() if pmt.match_status else "MANUAL_REVIEW",
                detail=pmt.match_reason or "Manual review or student assignment requested",
                suggested_action="Assign to student or invoice",
                resolved=False,
            )
            db.add(exc)
            db.flush()

    if not exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exception record or payment #{exception_id} not found"
        )

    action = resolution.action.strip().lower()
    note = resolution.note or ""

    if action in ("issue_refund", "refund_voucher"):
        try:
            v = process_overpayment_action(db=db, payment_id=exc.payment_id, action_type="issue_refund", note=note)
            db.commit()
            db.refresh(exc)
        except ValueError as ve:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    elif action in ("roll_advance_credit", "advance_credit"):
        try:
            v = process_overpayment_action(db=db, payment_id=exc.payment_id, action_type="roll_advance_credit", note=note)
            db.commit()
            db.refresh(exc)
        except ValueError as ve:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    elif action == "assign_to_student":
        if not resolution.student_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="student_id is required for assign_to_student action"
            )
        try:
            reallocate_payment_to_student(
                db=db,
                payment_id=exc.payment_id,
                student_id=resolution.student_id.strip().upper(),
                invoice_id=resolution.invoice_id.strip().upper() if resolution.invoice_id else None,
                resolution_note=note,
            )
            res_note = f"Assigned to {resolution.student_id}. {note}".strip()
            db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == exc.payment_id).update({
                "resolved": True,
                "resolution_note": res_note
            })
            db.commit()
            db.refresh(exc)
        except ValueError as ve:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    elif action == "accept_partial":
        res_note = note or "Partial payment accepted as-is"
        db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == exc.payment_id).update({
            "resolved": True,
            "resolution_note": res_note
        })
        db.commit()
        db.refresh(exc)

    elif action == "mark_duplicate":
        res_note = note or "Confirmed and marked as duplicate transaction"
        db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == exc.payment_id).update({
            "resolved": True,
            "resolution_note": res_note
        })
        exc.payment.match_status = "Duplicate"
        db.commit()
        db.refresh(exc)

    elif action == "dismiss":
        res_note = note or "Dismissed by operator"
        db.query(ExceptionRecord).filter(ExceptionRecord.payment_id == exc.payment_id).update({
            "resolved": True,
            "resolution_note": res_note
        })
        db.commit()
        db.refresh(exc)

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action '{resolution.action}'. Allowed: issue_refund, roll_advance_credit, assign_to_student, accept_partial, mark_duplicate, dismiss"
        )

    return ExceptionOut(
        id=exc.id,
        payment_id=exc.payment_id,
        reason_code=exc.reason_code,
        detail=exc.detail,
        suggested_action=exc.suggested_action,
        resolved=exc.resolved,
        resolution_note=exc.resolution_note,
        created_at=exc.created_at,
        payment=serialize_payment(exc.payment, db=db) if exc.payment else None,
    )


@router.post("/api/payments/{payment_id}/overpaid-action", response_model=RefundVoucherOut)
def trigger_overpaid_action(
    payment_id: int,
    req: OverpaidActionRequest,
    db: Session = Depends(get_db)
):
    """
    Executes a 1-click overpayment resolution:
      - action_type: 'issue_refund' -> Issues a refund voucher (RFD-YYYYMMDD-XXXX).
      - action_type: 'roll_advance_credit' -> Roll forward excess to student's advance credit balance (CRD-YYYYMMDD-XXXX).
    """
    try:
        act = req.get_action_type
        voucher = process_overpayment_action(db=db, payment_id=payment_id, action_type=act, note=req.note)
        db.commit()
        db.refresh(voucher)
        return RefundVoucherOut.model_validate(voucher)
    except ValueError as ve:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
