import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Student, Invoice, InvoiceFeeItem, RefundVoucher
from app.services.reconciler import (
    derive_invoice_status,
    process_single_payment,
    recalculate_invoice_status,
    reallocate_payment_to_student,
    ensure_invoice_fee_items,
    process_overpayment_action,
)


@pytest.fixture
def db_session():
    # Use SQLite in-memory database for fast, isolated testing
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_invoice_status_derivation():
    today = date(2026, 10, 10)
    future_date = date(2026, 11, 15)
    past_date = date(2026, 9, 1)

    # 1. Zero paid, future due date -> Pending
    assert derive_invoice_status(5000000, 0, future_date, today) == "Pending"

    # 2. Zero paid, past due date -> Overdue
    assert derive_invoice_status(5000000, 0, past_date, today) == "Overdue"

    # 3. Exactly paid -> Paid
    assert derive_invoice_status(5000000, 5000000, future_date, today) == "Paid"
    assert derive_invoice_status(5000000, 5000000, past_date, today) == "Paid"

    # 4. Overpaid -> Overpaid
    assert derive_invoice_status(5000000, 6000000, future_date, today) == "Overpaid"

    # 5. Partially paid, future date -> Partial
    assert derive_invoice_status(5000000, 2500000, future_date, today) == "Partial"

    # 6. Partially paid, past date -> Overdue
    assert derive_invoice_status(5000000, 2500000, past_date, today) == "Overdue"


def test_exact_match(db_session):
    student = Student(student_id="1KS25AI101", name="Aarav Sharma")
    db_session.add(student)
    db_session.flush()

    invoice = Invoice(
        invoice_id="INV-001",
        student_id="1KS25AI101",
        description="Semester 1 Tuition",
        amount_due=5000000,  # ₹50,000 in paise
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.commit()

    raw_row = {
        "txn_ref": "TXN1001",
        "student_ref": "1KS25AI101",
        "invoice_ref": "INV-001",
        "payer_name": "Aarav Sharma",
        "amount": "50000",
        "method": "UPI",
        "payment_date": "2026-10-01",
    }

    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()
    db_session.refresh(invoice)

    assert pmt.match_status == "Matched"
    assert pmt.confidence_score >= 90
    assert len(pmt.allocations) == 1
    assert pmt.allocations[0].amount_applied == 5000000
    assert invoice.status == "Paid"
    assert invoice.outstanding_amount == 0


def test_student_only_match(db_session):
    student = Student(student_id="1KS25AI102", name="Priya Patel")
    db_session.add(student)
    db_session.flush()

    invoice = Invoice(
        invoice_id="INV-002",
        student_id="1KS25AI102",
        description="Semester 1 Tuition",
        amount_due=7500000,  # ₹75,000
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.commit()

    raw_row = {
        "txn_ref": "TXN1002",
        "student_ref": "1KS25AI102",
        "invoice_ref": "",
        "payer_name": "Priya Patel",
        "amount": "75000",
        "method": "NEFT",
        "payment_date": "2026-10-02",
    }

    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()
    db_session.refresh(invoice)

    assert pmt.match_status == "Matched"
    assert len(pmt.allocations) == 1
    assert pmt.allocations[0].amount_applied == 7500000
    assert invoice.status == "Paid"


def test_exact_duplicate(db_session):
    student = Student(student_id="1KS25AI101", name="Aarav Sharma")
    db_session.add(student)
    invoice = Invoice(
        invoice_id="INV-001",
        student_id="1KS25AI101",
        description="Tuition",
        amount_due=5000000,
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.commit()

    raw_row = {
        "txn_ref": "TXN-DUP-01",
        "student_ref": "1KS25AI101",
        "invoice_ref": "INV-001",
        "payer_name": "Aarav Sharma",
        "amount": "50000",
        "method": "UPI",
        "payment_date": "2026-10-01",
    }

    # First run
    pmt1 = process_single_payment(db_session, raw_row)
    db_session.commit()
    assert pmt1.match_status == "Matched"

    # Second run with exact same txn_ref
    pmt2 = process_single_payment(db_session, raw_row)
    db_session.commit()

    assert pmt2.match_status == "Duplicate"
    assert len(pmt2.allocations) == 0
    assert len(pmt2.exceptions) == 1
    assert pmt2.exceptions[0].reason_code == "DUPLICATE"
    assert str(pmt1.id) in pmt2.exceptions[0].detail


def test_suspected_duplicate(db_session):
    student = Student(student_id="1KS25AI103", name="Rohan Verma")
    db_session.add(student)
    db_session.commit()

    raw_row1 = {
        "txn_ref": "",  # No txn_ref
        "student_ref": "1KS25AI103",
        "invoice_ref": "",
        "payer_name": "Rohan Verma",
        "amount": "25000",
        "method": "UPI",
        "payment_date": "2026-10-01",
    }
    pmt1 = process_single_payment(db_session, raw_row1)
    db_session.commit()

    # Second payment with same student, amount, method on the same day without txn_ref
    raw_row2 = {
        "txn_ref": "",
        "student_ref": "1KS25AI103",
        "invoice_ref": "",
        "payer_name": "Rohan Verma",
        "amount": "25000",
        "method": "UPI",
        "payment_date": "2026-10-01",
    }
    pmt2 = process_single_payment(db_session, raw_row2)
    db_session.commit()

    assert pmt2.match_status == "Review"
    assert len(pmt2.allocations) == 0
    assert len(pmt2.exceptions) == 1
    assert pmt2.exceptions[0].reason_code == "DUPLICATE"
    assert "Suspected duplicate" in pmt2.exceptions[0].detail


def test_partial_payment(db_session):
    student = Student(student_id="1KS25AI104", name="Ananya Iyer")
    db_session.add(student)
    invoice = Invoice(
        invoice_id="INV-004",
        student_id="1KS25AI104",
        description="Tuition",
        amount_due=5000000,  # ₹50,000
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.commit()

    raw_row = {
        "txn_ref": "TXN1004",
        "student_ref": "1KS25AI104",
        "invoice_ref": "INV-004",
        "payer_name": "Ananya Iyer",
        "amount": "25000",  # ₹25,000
        "method": "CHEQUE",
        "payment_date": "2026-10-03",
    }

    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()
    db_session.refresh(invoice)

    assert pmt.match_status == "Partial"
    assert len(pmt.allocations) == 1
    assert pmt.allocations[0].amount_applied == 2500000
    assert invoice.status == "Partial"
    assert invoice.outstanding_amount == 2500000
    assert len(pmt.exceptions) == 1
    assert pmt.exceptions[0].reason_code == "PARTIAL"


def test_overpaid(db_session):
    student = Student(student_id="1KS25AI107", name="Deepa Nair")
    db_session.add(student)
    invoice = Invoice(
        invoice_id="INV-007",
        student_id="1KS25AI107",
        description="Tuition",
        amount_due=5000000,  # ₹50,000
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.commit()

    raw_row = {
        "txn_ref": "TXN1007",
        "student_ref": "1KS25AI107",
        "invoice_ref": "INV-007",
        "payer_name": "Deepa Nair",
        "amount": "55000",  # ₹55,000
        "method": "DD",
        "payment_date": "2026-10-06",
    }

    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()
    db_session.refresh(invoice)

    assert pmt.match_status == "Overpaid"
    assert len(pmt.allocations) == 1
    assert pmt.allocations[0].amount_applied == 5000000  # Allocates outstanding
    assert invoice.status == "Paid"
    assert len(pmt.exceptions) == 1
    assert pmt.exceptions[0].reason_code == "OVERPAID"
    assert "₹5,000.00" in pmt.exceptions[0].detail


def test_unmatched(db_session):
    raw_row = {
        "txn_ref": "TXN-UNKNOWN",
        "student_ref": "1KS99XX999",
        "invoice_ref": "",
        "payer_name": "Unknown Stranger",
        "amount": "30000",
        "method": "UPI",
        "payment_date": "2026-10-04",
    }

    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()

    assert pmt.match_status == "Unmatched"
    assert len(pmt.allocations) == 0
    assert len(pmt.exceptions) == 1
    assert pmt.exceptions[0].reason_code == "UNMATCHED"


def test_fuzzy_name_review(db_session):
    student = Student(student_id="1KS25AI106", name="Saravanan Natarajan")
    db_session.add(student)
    invoice = Invoice(
        invoice_id="INV-006",
        student_id="1KS25AI106",
        description="Tuition",
        amount_due=5000000,
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.commit()

    # Typo in name: "Saravnan"
    raw_row = {
        "txn_ref": "TXN-FUZZY",
        "student_ref": "",
        "invoice_ref": "",
        "payer_name": "Saravnan",
        "amount": "50000",
        "method": "CASH",
        "payment_date": "2026-10-05",
    }

    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()

    # Never auto-applied!
    assert pmt.match_status == "Review"
    assert len(pmt.allocations) == 0
    assert len(pmt.exceptions) == 1
    assert pmt.exceptions[0].reason_code == "AMBIGUOUS_MATCH"
    assert "Saravanan Natarajan" in pmt.exceptions[0].detail


def test_invalid_row(db_session):
    # Missing amount
    raw_row1 = {
        "txn_ref": "TXN-INV-1",
        "student_ref": "1KS25AI101",
        "invoice_ref": "INV-001",
        "payer_name": "Aarav",
        "amount": "",
        "method": "UPI",
        "payment_date": "2026-10-01",
    }
    pmt1 = process_single_payment(db_session, raw_row1)
    db_session.commit()
    assert pmt1.match_status == "Invalid"
    assert pmt1.exceptions[0].reason_code == "INVALID_ROW"

    # Negative amount
    raw_row2 = {
        "txn_ref": "TXN-INV-2",
        "student_ref": "1KS25AI101",
        "amount": "-500",
        "payment_date": "2026-10-01",
    }
    pmt2 = process_single_payment(db_session, raw_row2)
    db_session.commit()
    assert pmt2.match_status == "Invalid"

    # All student/invoice/payer missing
    raw_row3 = {
        "txn_ref": "TXN-INV-3",
        "amount": "5000",
        "payment_date": "2026-10-01",
    }
    pmt3 = process_single_payment(db_session, raw_row3)
    db_session.commit()
    assert pmt3.match_status == "Invalid"


def test_multi_invoice_allocation(db_session):
    student = Student(student_id="1KS25AI110", name="Multi Invoice Student")
    db_session.add(student)

    # Invoice 1: Due earlier, ₹30,000
    inv1 = Invoice(
        invoice_id="INV-M1",
        student_id="1KS25AI110",
        description="Semester 1 Fee",
        amount_due=3000000,
        due_date=date(2026, 8, 1),
        status="Pending",
    )
    # Invoice 2: Due later, ₹40,000
    inv2 = Invoice(
        invoice_id="INV-M2",
        student_id="1KS25AI110",
        description="Semester 2 Fee",
        amount_due=4000000,
        due_date=date(2026, 12, 1),
        status="Pending",
    )
    db_session.add_all([inv1, inv2])
    db_session.commit()

    # Pay ₹50,000 for student without specifying invoice
    raw_row = {
        "txn_ref": "TXN-MULTI",
        "student_ref": "1KS25AI110",
        "invoice_ref": "",
        "payer_name": "Multi Student",
        "amount": "50000",
        "method": "NEFT",
        "payment_date": "2026-10-05",
    }

    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()
    db_session.refresh(inv1)
    db_session.refresh(inv2)

    # Oldest invoice (INV-M1) should get full ₹30,000 -> Paid
    # Next invoice (INV-M2) should get remaining ₹20,000 -> Partial
    assert len(pmt.allocations) == 2
    assert pmt.allocations[0].amount_applied == 3000000
    assert pmt.allocations[1].amount_applied == 2000000
    assert inv1.status == "Paid"
    assert inv2.status == "Partial"
    assert inv2.outstanding_amount == 2000000
    assert pmt.match_status == "Partial"


def test_idempotent_reimport(db_session):
    student = Student(student_id="1KS25AI101", name="Aarav Sharma")
    db_session.add(student)
    invoice = Invoice(
        invoice_id="INV-001",
        student_id="1KS25AI101",
        amount_due=5000000,
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.commit()

    batch_data = [
        {
            "txn_ref": "TXN-IDEM-01",
            "student_ref": "1KS25AI101",
            "invoice_ref": "INV-001",
            "payer_name": "Aarav Sharma",
            "amount": "50000",
            "method": "UPI",
            "payment_date": "2026-10-01",
        }
    ]

    # Batch 1
    seen1 = {}
    p1 = process_single_payment(db_session, batch_data[0], seen_txn_refs=seen1)
    db_session.commit()
    db_session.refresh(invoice)
    assert p1.match_status == "Matched"
    assert invoice.status == "Paid"
    alloc_sum_before = sum(a.amount_applied for a in invoice.allocations)
    assert alloc_sum_before == 5000000

    # Batch 2 (re-importing exact same payment)
    seen2 = {}
    p2 = process_single_payment(db_session, batch_data[0], seen_txn_refs=seen2)
    db_session.commit()
    db_session.refresh(invoice)
    assert p2.match_status == "Duplicate"

    # Allocations and invoice totals must remain unchanged
    alloc_sum_after = sum(a.amount_applied for a in invoice.allocations)
    assert alloc_sum_after == alloc_sum_before
    assert invoice.status == "Paid"


def test_step5_confidence_scoring_rules(db_session):
    # Setup students and invoices
    s1 = Student(student_id="STU-001", name="Rahul Verma")
    s2 = Student(student_id="STU-002", name="Rahul Sharma")
    db_session.add_all([s1, s2])

    inv1 = Invoice(invoice_id="INV-101", student_id="STU-001", amount_due=1000000, due_date=date(2026, 11, 1), status="Pending")
    inv2 = Invoice(invoice_id="INV-102", student_id="STU-001", amount_due=1000000, due_date=date(2026, 11, 2), status="Pending")
    inv_settled = Invoice(invoice_id="INV-SETTLED", student_id="STU-001", amount_due=500000, due_date=date(2026, 8, 1), status="Paid")
    db_session.add_all([inv1, inv2, inv_settled])
    db_session.commit()

    # Settle inv_settled with a payment
    process_single_payment(db_session, {
        "txn_ref": "T-PREV", "student_ref": "STU-001", "invoice_ref": "INV-SETTLED", "payer_name": "Rahul Verma", "amount": "5000", "payment_date": "2026-08-01"
    })

    # 1. Exact invoice_ref match (Base 85) + agree (+10) + amount (+10) + name (+5) = 110 -> 100
    p1 = process_single_payment(db_session, {
        "txn_ref": "T1", "student_ref": "STU-001", "invoice_ref": "INV-101", "payer_name": "Rahul Verma", "amount": "10000", "payment_date": "2026-10-01"
    })
    assert p1.confidence_score == 100
    assert p1.match_status == "Matched"
    assert len(p1.allocations) == 1

    # 2. Conflict penalty (-30): payment specifies STU-002, but invoice INV-102 belongs to STU-001
    # Base 85 - 30 (conflict) + 10 (amount match) + 5 (name match) = 70 (Review)
    p2 = process_single_payment(db_session, {
        "txn_ref": "T2", "student_ref": "STU-002", "invoice_ref": "INV-102", "payer_name": "Rahul Verma", "amount": "10000", "payment_date": "2026-10-01"
    })
    assert p2.confidence_score == 70
    assert p2.match_status == "Review"
    assert len(p2.allocations) == 0  # Review payments are NEVER allocated

    # 3. Settled invoice penalty (-20): Base 85 + 10 (agree) - 20 (settled) = 75 (Review)
    p3 = process_single_payment(db_session, {
        "txn_ref": "T3", "student_ref": "STU-001", "invoice_ref": "INV-SETTLED", "payer_name": "Unknown Payer", "amount": "5000", "payment_date": "2026-10-01"
    })
    assert p3.confidence_score == 75
    assert p3.match_status == "Review"
    assert len(p3.allocations) == 0

    # 4. Low score (< 50) -> Unmatched
    p4 = process_single_payment(db_session, {
        "txn_ref": "T4", "student_ref": "STU-999", "invoice_ref": "", "payer_name": "Unknown", "amount": "10000", "payment_date": "2026-10-01"
    })
    assert p4.confidence_score < 50
    assert p4.match_status == "Unmatched"
    assert len(p4.allocations) == 0


def test_itemized_fee_head_priority_allocation(db_session):
    student = Student(student_id="1KS25AI201", name="Fee Head Priority Test Student")
    db_session.add(student)
    db_session.flush()

    # Create invoice ₹60,000 Total: Tuition (40k, P1), Exam (5k, P2), Hostel (10k, P3), Transport (5k, P4)
    invoice = Invoice(
        invoice_id="INV-FEEHEAD-01",
        student_id="1KS25AI201",
        description="Semester 1 Full Fee",
        amount_due=6000000,
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.flush()

    ensure_invoice_fee_items(db_session, invoice)
    db_session.commit()

    # Verify 4 fee items created with default ratios
    items = sorted(invoice.fee_items, key=lambda x: x.priority)
    assert len(items) == 4
    assert items[0].fee_head == "Tuition Fee" and items[0].priority == 1
    assert items[1].fee_head == "Examination Fee" and items[1].priority == 2
    assert items[2].fee_head == "Hostel & Mess Fee" and items[2].priority == 3
    assert items[3].fee_head == "Transport & Library" and items[3].priority == 4

    # Pay partial amount: ₹45,000 (4,500,000 paise)
    raw_row = {
        "txn_ref": "TXN-FH-45K",
        "student_ref": "1KS25AI201",
        "invoice_ref": "INV-FEEHEAD-01",
        "payer_name": "Priority Payer",
        "amount": "45000",
        "method": "UPI",
        "payment_date": "2026-10-08",
    }
    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()

    db_session.refresh(invoice)
    items = sorted(invoice.fee_items, key=lambda x: x.priority)

    # Priority 1 (Tuition Fee, 70% = ₹42,000): fully satisfied with 4,200,000 paise
    assert items[0].amount_applied == items[0].amount

    # Priority 2 (Examination Fee, 10% = ₹6,000): gets remaining 300,000 paise (₹3,000 partial)
    assert items[1].amount_applied == 300000

    # Priority 3 (Hostel & Mess) & Priority 4 (Transport & Library) remain 0
    assert items[2].amount_applied == 0
    assert items[3].amount_applied == 0

    # Total allocated across fee heads equals ₹45,000 (4,500,000 paise)
    total_allocated_heads = sum(item.amount_applied for item in items)
    assert total_allocated_heads == 4500000


def test_overpayment_refund_voucher_action(db_session):
    student = Student(student_id="1KS25AI202", name="Refund Student")
    db_session.add(student)
    invoice = Invoice(
        invoice_id="INV-RFD-01",
        student_id="1KS25AI202",
        description="Tuition",
        amount_due=5000000,  # ₹50,000
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.commit()

    # Pay ₹55,000 -> ₹5,000 overpaid
    raw_row = {
        "txn_ref": "TXN-RFD-55K",
        "student_ref": "1KS25AI202",
        "invoice_ref": "INV-RFD-01",
        "payer_name": "Refund Payer",
        "amount": "55000",
        "method": "UPI",
        "payment_date": "2026-10-08",
    }
    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()

    assert pmt.match_status == "Overpaid"

    # Execute 1-click issue refund voucher
    voucher = process_overpayment_action(db_session, pmt.id, "issue_refund")
    db_session.commit()

    assert voucher.action_type == "REFUND_VOUCHER"
    assert voucher.voucher_number.startswith("RFD-")
    assert voucher.amount == 500000  # ₹5,000 in paise

    # Check voucher created in DB
    db_voucher = db_session.query(RefundVoucher).filter_by(voucher_number=voucher.voucher_number).first()
    assert db_voucher is not None
    assert db_voucher.amount == 500000
    assert db_voucher.student_id == "1KS25AI202"

    # Check exception resolved
    exc = pmt.exceptions[0]
    assert exc.resolved is True
    assert "Issued Refund Voucher" in exc.resolution_note


def test_overpayment_roll_advance_credit_action(db_session):
    student = Student(student_id="1KS25AI203", name="Credit Student", advance_credit=0)
    db_session.add(student)
    invoice = Invoice(
        invoice_id="INV-CRD-01",
        student_id="1KS25AI203",
        description="Tuition",
        amount_due=5000000,  # ₹50,000
        due_date=date(2026, 11, 15),
        status="Pending",
    )
    db_session.add(invoice)
    db_session.commit()

    # Pay ₹65,000 -> ₹15,000 overpaid
    raw_row = {
        "txn_ref": "TXN-CRD-65K",
        "student_ref": "1KS25AI203",
        "invoice_ref": "INV-CRD-01",
        "payer_name": "Credit Payer",
        "amount": "65000",
        "method": "NEFT",
        "payment_date": "2026-10-08",
    }
    pmt = process_single_payment(db_session, raw_row)
    db_session.commit()

    assert pmt.match_status == "Overpaid"

    # Execute 1-click roll forward advance credit
    voucher = process_overpayment_action(db_session, pmt.id, "roll_advance_credit")
    db_session.commit()

    assert voucher.action_type == "ADVANCE_CREDIT"
    assert voucher.voucher_number.startswith("CRD-")
    assert voucher.amount == 1500000  # ₹15,000 in paise

    # Check student advance credit updated
    db_session.refresh(student)
    assert student.advance_credit == 1500000

    # Check exception resolved
    exc = pmt.exceptions[0]
    assert exc.resolved is True
    assert "Rolled Forward" in exc.resolution_note


