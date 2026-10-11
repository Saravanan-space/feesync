import csv
import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models import Student, Invoice
from app.schemas import InvoiceCreate, InvoiceUpdate, InvoiceOut, InvoiceFeeItemOut
from app.services.normalizer import parse_amount_to_paise, parse_date_string
from app.services.reconciler import derive_invoice_status, recalculate_invoice_status, ensure_invoice_fee_items
from app.routers.students import decode_csv_file


router = APIRouter(prefix="/api/invoices", tags=["Invoices"])


def serialize_invoice(inv: Invoice) -> InvoiceOut:
    fee_items_out = [
        InvoiceFeeItemOut(
            id=item.id,
            invoice_id=item.invoice_id,
            fee_head=item.fee_head,
            amount=item.amount,
            priority=item.priority,
            amount_applied=item.amount_applied,
        )
        for item in (inv.fee_items or [])
    ]
    return InvoiceOut(
        id=inv.id,
        invoice_id=inv.invoice_id,
        student_id=inv.student_id,
        description=inv.description,
        amount_due=inv.amount_due,
        due_date=inv.due_date,
        status=inv.status,
        paid_amount=inv.paid_amount,
        outstanding_amount=inv.outstanding_amount,
        student_name=inv.student.name if inv.student else None,
        fee_items=fee_items_out,
    )


@router.get("", response_model=List[InvoiceOut])
def list_invoices(
    student_id: Optional[str] = Query(None, description="Filter by student ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (Pending, Partial, Paid, Overpaid, Overdue)"),
    q: Optional[str] = Query(None, description="Search by invoice ID, student ID, description, or student name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(Invoice).join(Invoice.student)

    if student_id and student_id.strip():
        query = query.filter(Invoice.student_id == student_id.strip().upper())

    if status_filter and status_filter.strip():
        query = query.filter(Invoice.status.ilike(status_filter.strip()))

    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Invoice.invoice_id.ilike(search),
                Invoice.student_id.ilike(search),
                Invoice.description.ilike(search),
                Student.name.ilike(search),
            )
        )

    invoices = query.order_by(Invoice.due_date.asc(), Invoice.invoice_id.asc()).offset(skip).limit(limit).all()

    result = []
    for inv in invoices:
        paid = inv.paid_amount
        # Re-verify status dynamically & ensure fee items
        inv_status = derive_invoice_status(inv.amount_due, paid, inv.due_date)
        ensure_invoice_fee_items(db, inv)
        if inv.status != inv_status:
            inv.status = inv_status
            db.flush()

        result.append(serialize_invoice(inv))
    db.commit()
    return result


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(invoice_in: InvoiceCreate, db: Session = Depends(get_db)):
    clean_id = invoice_in.invoice_id.strip().upper()
    clean_student_id = invoice_in.student_id.strip().upper()

    if not clean_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invoice ID cannot be empty")

    existing_inv = db.query(Invoice).filter(Invoice.invoice_id == clean_id).first()
    if existing_inv:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invoice '{clean_id}' already exists"
        )

    student = db.query(Student).filter(Student.student_id == clean_student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student '{clean_student_id}' does not exist"
        )

    if invoice_in.amount_due <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount due must be strictly positive")

    init_status = derive_invoice_status(invoice_in.amount_due, 0, invoice_in.due_date)
    invoice = Invoice(
        invoice_id=clean_id,
        student_id=clean_student_id,
        description=invoice_in.description.strip() or "Tuition Fee",
        amount_due=invoice_in.amount_due,
        due_date=invoice_in.due_date,
        status=init_status,
    )
    db.add(invoice)
    db.flush()
    ensure_invoice_fee_items(db, invoice)
    db.commit()
    db.refresh(invoice)

    return serialize_invoice(invoice)


@router.get("/{invoice_id_or_pk}", response_model=InvoiceOut)
def get_invoice(invoice_id_or_pk: str, db: Session = Depends(get_db)):
    inv = None
    if invoice_id_or_pk.isdigit():
        inv = db.query(Invoice).filter(Invoice.id == int(invoice_id_or_pk)).first()
    if not inv:
        inv = db.query(Invoice).filter(Invoice.invoice_id == invoice_id_or_pk.strip().upper()).first()

    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Invoice '{invoice_id_or_pk}' not found")

    recalculate_invoice_status(inv, db)
    ensure_invoice_fee_items(db, inv)
    db.commit()

    return serialize_invoice(inv)


@router.put("/{invoice_id_or_pk}", response_model=InvoiceOut)
def update_invoice(invoice_id_or_pk: str, invoice_in: InvoiceUpdate, db: Session = Depends(get_db)):
    inv = None
    if invoice_id_or_pk.isdigit():
        inv = db.query(Invoice).filter(Invoice.id == int(invoice_id_or_pk)).first()
    if not inv:
        inv = db.query(Invoice).filter(Invoice.invoice_id == invoice_id_or_pk.strip().upper()).first()

    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Invoice '{invoice_id_or_pk}' not found")

    if invoice_in.description is not None:
        inv.description = invoice_in.description.strip()
    if invoice_in.amount_due is not None:
        if invoice_in.amount_due <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount due must be positive")
        inv.amount_due = invoice_in.amount_due
    if invoice_in.due_date is not None:
        inv.due_date = invoice_in.due_date

    recalculate_invoice_status(inv, db)
    ensure_invoice_fee_items(db, inv)
    db.commit()
    db.refresh(inv)

    return serialize_invoice(inv)


@router.delete("/{invoice_id_or_pk}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(invoice_id_or_pk: str, db: Session = Depends(get_db)):
    inv = None
    if invoice_id_or_pk.isdigit():
        inv = db.query(Invoice).filter(Invoice.id == int(invoice_id_or_pk)).first()
    if not inv:
        inv = db.query(Invoice).filter(Invoice.invoice_id == invoice_id_or_pk.strip().upper()).first()

    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Invoice '{invoice_id_or_pk}' not found")

    db.delete(inv)
    db.commit()
    return None


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_invoices_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    csv_text = decode_csv_file(content)

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    required = ["invoice_id", "student_id", "amount_due", "due_date"]
    for req in required:
        if req not in fieldnames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"CSV header missing required column: '{req}'"
            )

    imported = 0
    updated = 0
    skipped = 0

    for row in reader:
        row_norm = {k.strip().lower(): v for k, v in row.items() if k}
        inv_id = (row_norm.get("invoice_id") or "").strip().upper()
        sid = (row_norm.get("student_id") or "").strip().upper()
        desc = (row_norm.get("description") or "Tuition Fee").strip()
        raw_amt = row_norm.get("amount_due")
        raw_date = row_norm.get("due_date")

        if not inv_id or not sid:
            skipped += 1
            continue

        paise, amt_err = parse_amount_to_paise(raw_amt)
        due_d = parse_date_string(raw_date)

        if amt_err or not due_d:
            skipped += 1
            continue

        student = db.query(Student).filter(Student.student_id == sid).first()
        if not student:
            # Create a placeholder student if not exists
            student = Student(student_id=sid, name=f"Student {sid}")
            db.add(student)
            db.flush()

        existing = db.query(Invoice).filter(Invoice.invoice_id == inv_id).first()
        if existing:
            existing.student_id = sid
            existing.description = desc
            existing.amount_due = paise
            existing.due_date = due_d
            recalculate_invoice_status(existing, db)
            updated += 1
        else:
            status_init = derive_invoice_status(paise, 0, due_d)
            new_inv = Invoice(
                invoice_id=inv_id,
                student_id=sid,
                description=desc,
                amount_due=paise,
                due_date=due_d,
                status=status_init,
            )
            db.add(new_inv)
            imported += 1

    db.commit()
    return {"message": "Invoices imported successfully", "imported": imported, "updated": updated, "skipped": skipped}
