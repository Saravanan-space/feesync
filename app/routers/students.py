import csv
import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models import Student, Invoice
from app.schemas import StudentCreate, StudentUpdate, StudentOut


router = APIRouter(prefix="/api/students", tags=["Students"])


def decode_csv_file(file_bytes: bytes) -> str:
    if len(file_bytes) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds maximum allowed limit of 5 MB"
        )
    if not file_bytes or not file_bytes.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded CSV file is empty"
        )

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unable to decode CSV file with supported encodings (UTF-8, Lat  in-1)"
    )


@router.get("", response_model=List[StudentOut])
def list_students(
    q: Optional[str] = Query(None, description="Search query by name, ID, email, or phone"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(Student)
    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Student.student_id.ilike(search),
                Student.name.ilike(search),
                Student.email.ilike(search),
                Student.phone.ilike(search),
            )
        )
    students = query.order_by(Student.student_id.asc()).offset(skip).limit(limit).all()

    result = []
    for s in students:
        total_due = sum(inv.amount_due for inv in s.invoices)
        total_paid = sum(inv.paid_amount for inv in s.invoices)
        total_outstanding = max(0, total_due - total_paid)
        out = StudentOut(
            id=s.id,
            student_id=s.student_id,
            name=s.name,
            email=s.email,
            phone=s.phone,
            total_due=total_due,
            total_paid=total_paid,
            total_outstanding=total_outstanding,
            advance_credit=getattr(s, "advance_credit", 0),
        )
        result.append(out)
    return result


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(student_in: StudentCreate, db: Session = Depends(get_db)):
    clean_id = student_in.student_id.strip().upper()
    if not clean_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Student ID cannot be empty")
    if not student_in.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Student name cannot be empty")

    existing = db.query(Student).filter(Student.student_id == clean_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Student with ID '{clean_id}' already exists"
        )

    student = Student(
        student_id=clean_id,
        name=student_in.name.strip(),
        email=student_in.email.strip() if student_in.email else None,
        phone=student_in.phone.strip() if student_in.phone else None,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return StudentOut(
        id=student.id,
        student_id=student.student_id,
        name=student.name,
        email=student.email,
        phone=student.phone,
        total_due=0,
        total_paid=0,
        total_outstanding=0,
        advance_credit=getattr(student, "advance_credit", 0),
    )


@router.get("/{student_id_or_pk}", response_model=StudentOut)
def get_student(student_id_or_pk: str, db: Session = Depends(get_db)):
    student = None
    if student_id_or_pk.isdigit():
        student = db.query(Student).filter(Student.id == int(student_id_or_pk)).first()
    if not student:
        student = db.query(Student).filter(Student.student_id == student_id_or_pk.strip().upper()).first()

    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Student '{student_id_or_pk}' not found")

    total_due = sum(inv.amount_due for inv in student.invoices)
    total_paid = sum(inv.paid_amount for inv in student.invoices)
    return StudentOut(
        id=student.id,
        student_id=student.student_id,
        name=student.name,
        email=student.email,
        phone=student.phone,
        total_due=total_due,
        total_paid=total_paid,
        total_outstanding=max(0, total_due - total_paid),
        advance_credit=getattr(student, "advance_credit", 0),
    )


@router.put("/{student_id_or_pk}", response_model=StudentOut)
def update_student(student_id_or_pk: str, student_in: StudentUpdate, db: Session = Depends(get_db)):
    student = None
    if student_id_or_pk.isdigit():
        student = db.query(Student).filter(Student.id == int(student_id_or_pk)).first()
    if not student:
        student = db.query(Student).filter(Student.student_id == student_id_or_pk.strip().upper()).first()

    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Student '{student_id_or_pk}' not found")

    if student_in.name is not None:
        if not student_in.name.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Student name cannot be empty")
        student.name = student_in.name.strip()
    if student_in.email is not None:
        student.email = student_in.email.strip() or None
    if student_in.phone is not None:
        student.phone = student_in.phone.strip() or None

    db.commit()
    db.refresh(student)

    total_due = sum(inv.amount_due for inv in student.invoices)
    total_paid = sum(inv.paid_amount for inv in student.invoices)
    return StudentOut(
        id=student.id,
        student_id=student.student_id,
        name=student.name,
        email=student.email,
        phone=student.phone,
        total_due=total_due,
        total_paid=total_paid,
        total_outstanding=max(0, total_due - total_paid),
        advance_credit=getattr(student, "advance_credit", 0),
    )


@router.delete("/{student_id_or_pk}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student(student_id_or_pk: str, db: Session = Depends(get_db)):
    student = None
    if student_id_or_pk.isdigit():
        student = db.query(Student).filter(Student.id == int(student_id_or_pk)).first()
    if not student:
        student = db.query(Student).filter(Student.student_id == student_id_or_pk.strip().upper()).first()

    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Student '{student_id_or_pk}' not found")

    db.delete(student)
    db.commit()
    return None


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_students_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    csv_text = decode_csv_file(content)

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    if "student_id" not in fieldnames or "name" not in fieldnames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV header missing required columns: 'student_id' and 'name'"
        )

    imported = 0
    updated = 0
    for row in reader:
        # Normalize key access
        row_norm = {k.strip().lower(): v for k, v in row.items() if k}
        sid = (row_norm.get("student_id") or "").strip().upper()
        name = (row_norm.get("name") or "").strip()
        email = (row_norm.get("email") or "").strip() or None
        phone = (row_norm.get("phone") or "").strip() or None

        if not sid or not name:
            continue

        existing = db.query(Student).filter(Student.student_id == sid).first()
        if existing:
            existing.name = name
            if email:
                existing.email = email
            if phone:
                existing.phone = phone
            updated += 1
        else:
            new_s = Student(student_id=sid, name=name, email=email, phone=phone)
            db.add(new_s)
            imported += 1

    db.commit()
    return {"message": "Students imported successfully", "imported": imported, "updated": updated}
