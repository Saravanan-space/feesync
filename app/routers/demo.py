import os
import csv
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db, reset_db
from app.models import Student, Invoice, ImportBatch
from app.services.normalizer import parse_amount_to_paise, parse_date_string
from app.services.reconciler import derive_invoice_status, process_single_payment
from app.schemas import PaymentBatchResponse, ImportBatchOut


from fastapi.responses import FileResponse

router = APIRouter(tags=["Demo & Health"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DATA_DIR = os.path.join(BASE_DIR, "sample_data")


@router.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "app": "FeeReconcile", "version": "1.0.0"}


@router.get("/api/demo/download/students.csv")
def download_students_csv():
    """Download sample students CSV."""
    file_path = os.path.join(SAMPLE_DATA_DIR, "students.csv")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="students.csv sample file not found")
    return FileResponse(file_path, filename="students.csv", media_type="text/csv")


@router.get("/api/demo/download/invoices.csv")
def download_invoices_csv():
    """Download sample invoices CSV."""
    file_path = os.path.join(SAMPLE_DATA_DIR, "invoices.csv")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="invoices.csv sample file not found")
    return FileResponse(file_path, filename="invoices.csv", media_type="text/csv")


@router.get("/api/demo/download/payments.csv")
def download_payments_csv():
    """Download sample payments CSV."""
    file_path = os.path.join(SAMPLE_DATA_DIR, "payments_demo.csv")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="payments_demo.csv sample file not found")
    return FileResponse(file_path, filename="payments_demo.csv", media_type="text/csv")


@router.get("/api/demo/files/{filename}")
def download_demo_file(filename: str):
    """Download specific scenario CSV file from demo_files directory."""
    demo_dir = os.path.join(BASE_DIR, "demo_files")
    file_path = os.path.join(demo_dir, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Demo file {filename} not found")
    return FileResponse(file_path, filename=filename, media_type="text/csv")


@router.post("/api/demo/reset")
def reset_database():
    """Drops all tables and recreates an empty schema."""
    reset_db()
    return {"message": "Database reset successfully. All tables are empty."}


@router.post("/api/demo/load")
def load_demo_data(db: Session = Depends(get_db)):
    """
    Resets the database and automatically populates:
      1. Students (students.csv)
      2. Invoices (invoices.csv)
      3. Payments Reconciliation (payments_demo.csv)
    Produces the exact 9 test cases specified in the system design.
    """
    reset_db()

    students_path = os.path.join(SAMPLE_DATA_DIR, "students.csv")
    invoices_path = os.path.join(SAMPLE_DATA_DIR, "invoices.csv")
    payments_path = os.path.join(SAMPLE_DATA_DIR, "payments_demo.csv")

    if not os.path.exists(students_path) or not os.path.exists(invoices_path) or not os.path.exists(payments_path):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sample data files missing from directory: {SAMPLE_DATA_DIR}"
        )

    # 1. Load Students
    students_loaded = 0
    with open(students_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            s_dict = {k.strip().lower(): v for k, v in row.items() if k}
            sid = (s_dict.get("student_id") or "").strip().upper()
            name = (s_dict.get("name") or "").strip()
            email = (s_dict.get("email") or "").strip() or None
            phone = (s_dict.get("phone") or "").strip() or None
            if sid and name:
                db.add(Student(student_id=sid, name=name, email=email, phone=phone))
                students_loaded += 1
    db.commit()

    # 2. Load Invoices
    invoices_loaded = 0
    with open(invoices_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            i_dict = {k.strip().lower(): v for k, v in row.items() if k}
            inv_id = (i_dict.get("invoice_id") or "").strip().upper()
            sid = (i_dict.get("student_id") or "").strip().upper()
            desc = (i_dict.get("description") or "Tuition Fee").strip()
            raw_amt = i_dict.get("amount_due")
            raw_date = i_dict.get("due_date")

            paise, _ = parse_amount_to_paise(raw_amt)
            due_d = parse_date_string(raw_date)

            if inv_id and sid and paise and due_d:
                init_status = derive_invoice_status(paise, 0, due_d)
                db.add(Invoice(
                    invoice_id=inv_id,
                    student_id=sid,
                    description=desc,
                    amount_due=paise,
                    due_date=due_d,
                    status=init_status,
                ))
                invoices_loaded += 1
    db.commit()

    # 3. Load Payments and execute reconciliation cascade
    batch = ImportBatch(filename="payments_demo.csv")
    db.add(batch)
    db.flush()

    seen_txn_refs = {}
    total_rows = 0
    matched_cnt = 0
    duplicates_cnt = 0
    partial_cnt = 0
    unmatched_cnt = 0
    invalid_cnt = 0
    review_cnt = 0

    with open(payments_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            row_dict = {k.strip().lower(): v for k, v in row.items() if k}
            pmt = process_single_payment(
                db=db,
                raw_row=row_dict,
                batch_id=batch.id,
                seen_txn_refs=seen_txn_refs,
            )
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
                matched_cnt += 1

    batch.total_rows = total_rows
    batch.matched = matched_cnt
    batch.duplicates = duplicates_cnt
    batch.partial = partial_cnt
    batch.unmatched = unmatched_cnt
    batch.invalid = invalid_cnt
    batch.review = review_cnt
    db.commit()

    return {
        "message": "Demo data successfully loaded and reconciled",
        "students_loaded": students_loaded,
        "invoices_loaded": invoices_loaded,
        "payments_processed": total_rows,
        "results": {
            "matched": matched_cnt,
            "partial": partial_cnt,
            "duplicate": duplicates_cnt,
            "unmatched": unmatched_cnt,
            "review": review_cnt,
            "invalid": invalid_cnt,
        },
    }
