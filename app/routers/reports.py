from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import ReportSummary
from app.services.report import (
    get_summary_report,
    generate_exceptions_csv,
    generate_reconciliation_csv,
)

router = APIRouter(tags=["Reports"])


@router.get("/api/reports/summary", response_model=ReportSummary)
def get_report_summary(db: Session = Depends(get_db)):
    """Computes real-time financial metrics, statuses, and exceptions summary."""
    return get_summary_report(db)


@router.get("/api/reports/export/exceptions.csv")
@router.get("/export/exceptions.csv")
def export_exceptions_csv(db: Session = Depends(get_db)):
    """Exports all exception records as a CSV file."""
    csv_data = generate_exceptions_csv(db)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="exceptions.csv"'},
    )


@router.get("/api/reports/export/reconciliation.csv")
@router.get("/export/reconciliation.csv")
def export_reconciliation_csv(db: Session = Depends(get_db)):
    """Exports reconciliation ledger as a CSV file."""
    csv_data = generate_reconciliation_csv(db)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="reconciliation.csv"'},
    )
