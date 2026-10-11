from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from rapidfuzz import fuzz
from app.models import Student, Invoice
from app.services.scoring import calculate_name_similarity, compute_confidence_score


@dataclass
class MatchResult:
    status: str  # "Matched", "Partial", "Overpaid", "Review", "Unmatched"
    student: Optional[Student] = None
    invoice: Optional[Invoice] = None
    open_invoices: Optional[List[Invoice]] = None
    confidence_score: int = 0
    match_reason: str = ""
    exception_code: Optional[str] = None  # AMBIGUOUS_MATCH, UNMATCHED, etc.
    exception_detail: Optional[str] = None
    suggested_action: Optional[str] = None


def match_payment_record(
    db: Session,
    student_ref: Optional[str],
    invoice_ref: Optional[str],
    payer_name: Optional[str],
    amount: int,  # in paise
) -> MatchResult:
    """
    Executes the matching cascade adhering strictly to Step 5 confidence scoring rules:
      1. invoice_ref match (checks for conflicting student_ref, settled invoice, agreement)
      2. student_ref match (identifies open invoices, checks settled status)
      3. Fuzzy match on payer_name against student names (evaluates top and tied candidates)
      4. Fallback to Unmatched
      
    Status thresholds based on identity confidence score:
      >= 80: Matched (auto-reconcile allocation candidate)
      50-79: Review (suggest, never auto-apply/allocate)
      < 50:  Unmatched
    """
    # -------------------------------------------------------------
    # 1. invoice_ref match
    # -------------------------------------------------------------
    if invoice_ref:
        invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_ref).first()
        if invoice:
            inv_student = db.query(Student).filter(Student.student_id == invoice.student_id).first()
            name_sim = calculate_name_similarity(payer_name, inv_student.name if inv_student else "")
            payer_name_matches = (name_sim >= 85.0)
            is_settled = (invoice.outstanding_amount == 0)
            amt_match = (invoice.outstanding_amount > 0 and amount == invoice.outstanding_amount)

            conflict = False
            student_agrees = False
            if student_ref:
                if student_ref != invoice.student_id:
                    conflict = True
                else:
                    student_agrees = True

            score, reason = compute_confidence_score(
                invoice_ref_matched=True,
                student_ref_matched=bool(student_ref and not conflict),
                student_agrees_with_invoice=student_agrees,
                amount_equals_outstanding=amt_match,
                payer_name_matches=payer_name_matches,
                invoice_student_conflict=conflict,
                is_invoice_settled=is_settled,
                name_similarity=name_sim,
            )

            if score >= 80:
                status = "Matched"
                exc_code = None
                exc_detail = None
                sug_action = None
            elif score >= 50:
                status = "Review"
                exc_code = "AMBIGUOUS_MATCH" if conflict else ("SETTLED_INVOICE" if is_settled else "REVIEW_REQUIRED")
                if conflict:
                    exc_detail = f"Conflict: Payment specified student '{student_ref}', but invoice '{invoice_ref}' belongs to '{invoice.student_id}'"
                    sug_action = f"Verify whether payment belongs to {student_ref} or {invoice.student_id}"
                elif is_settled:
                    exc_detail = f"Invoice '{invoice_ref}' is already settled (0 outstanding)"
                    sug_action = f"Review overpayment or credit for student {invoice.student_id}"
                else:
                    exc_detail = f"Invoice matched with confidence score {score}/100"
                    sug_action = f"Review and confirm allocation to invoice {invoice_ref}"
            else:
                status = "Unmatched"
                exc_code = "UNMATCHED"
                exc_detail = f"Low confidence match ({score}/100) for invoice '{invoice_ref}'"
                sug_action = "Review transaction details"

            return MatchResult(
                status=status,
                student=inv_student,
                invoice=invoice,
                open_invoices=[invoice] if not is_settled else [],
                confidence_score=score,
                match_reason=reason,
                exception_code=exc_code,
                exception_detail=exc_detail,
                suggested_action=sug_action,
            )

    # -------------------------------------------------------------
    # 2. student_ref match
    # -------------------------------------------------------------
    if student_ref:
        student = db.query(Student).filter(Student.student_id == student_ref).first()
        if student:
            all_invoices = db.query(Invoice).filter(Invoice.student_id == student.student_id).order_by(Invoice.due_date.asc()).all()
            open_invoices = [inv for inv in all_invoices if inv.outstanding_amount > 0]
            first_inv = open_invoices[0] if open_invoices else None

            name_sim = calculate_name_similarity(payer_name, student.name)
            payer_name_matches = (name_sim >= 85.0)
            amt_match = (first_inv is not None and amount == first_inv.outstanding_amount)
            is_settled = (len(all_invoices) > 0 and len(open_invoices) == 0)

            score, reason = compute_confidence_score(
                invoice_ref_matched=False,
                student_ref_matched=True,
                amount_equals_outstanding=amt_match,
                payer_name_matches=payer_name_matches,
                is_invoice_settled=is_settled,
                name_similarity=name_sim,
            )

            if score >= 80:
                status = "Matched"
                exc_code = None
                exc_detail = None
                sug_action = None
            elif score >= 50:
                status = "Review"
                exc_code = "SETTLED_INVOICE" if is_settled else "REVIEW_REQUIRED"
                exc_detail = f"Student '{student_ref}' matched but score is {score}/100" + (" (all invoices settled)" if is_settled else "")
                sug_action = f"Review payment for student {student_ref}"
            else:
                status = "Unmatched"
                exc_code = "UNMATCHED"
                exc_detail = f"Student '{student_ref}' found but confidence score too low ({score}/100)"
                sug_action = "Review payment details"

            return MatchResult(
                status=status,
                student=student,
                invoice=first_inv,
                open_invoices=open_invoices,
                confidence_score=score,
                match_reason=reason,
                exception_code=exc_code,
                exception_detail=exc_detail,
                suggested_action=sug_action,
            )

    # -------------------------------------------------------------
    # 3. Fuzzy match payer_name against student names
    # -------------------------------------------------------------
    if payer_name and payer_name.strip():
        all_students = db.query(Student).all()
        scored_candidates: List[Tuple[Student, float]] = []

        for s in all_students:
            sim = calculate_name_similarity(payer_name, s.name)
            if sim >= 50.0:
                scored_candidates.append((s, sim))

        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        if scored_candidates:
            top_student, top_score = scored_candidates[0]
            is_tied = (len(scored_candidates) > 1 and (top_score - scored_candidates[1][1]) < 2.0)

            all_invs = top_student.invoices
            open_invs = [inv for inv in all_invs if inv.outstanding_amount > 0]
            first_inv = open_invs[0] if open_invs else None

            amt_match = (first_inv is not None and amount == first_inv.outstanding_amount)
            payer_name_matches = (top_score >= 85.0)
            is_settled = (len(all_invs) > 0 and len(open_invs) == 0)

            score, reason = compute_confidence_score(
                is_fuzzy_only=True,
                name_similarity=top_score,
                amount_equals_outstanding=amt_match,
                payer_name_matches=payer_name_matches,
                is_tied_candidate=is_tied,
                is_invoice_settled=is_settled,
            )

            if score >= 80:
                status = "Matched"
                exc_code = None
                exc_detail = None
                sug_action = None
            elif score >= 50:
                status = "Review"
                exc_code = "AMBIGUOUS_MATCH"
                exc_detail = f"Fuzzy match: payer '{payer_name}' matched student '{top_student.name}' ({top_student.student_id}) with score {score}/100 (name sim: {top_score:.1f}%)"
                sug_action = f"Assign to student {top_student.student_id} ({top_student.name})"
            else:
                status = "Unmatched"
                exc_code = "UNMATCHED"
                exc_detail = f"Fuzzy match score too low ({score}/100) for payer '{payer_name}'"
                sug_action = "Manually assign to student or invoice"

            return MatchResult(
                status=status,
                student=top_student if score >= 50 else None,
                invoice=first_inv if score >= 50 else None,
                open_invoices=open_invs if score >= 50 else [],
                confidence_score=score,
                match_reason=reason,
                exception_code=exc_code,
                exception_detail=exc_detail,
                suggested_action=sug_action,
            )

    # -------------------------------------------------------------
    # 4. Nothing matches
    # -------------------------------------------------------------
    detail = "No matching invoice or student found"
    if student_ref:
        detail = f"Student ID '{student_ref}' not found in registry"
    elif invoice_ref:
        detail = f"Invoice ID '{invoice_ref}' not found in registry"

    return MatchResult(
        status="Unmatched",
        student=None,
        invoice=None,
        confidence_score=0,
        match_reason="No matching student or invoice found",
        exception_code="UNMATCHED",
        exception_detail=detail,
        suggested_action="Review payment details and manually assign to student or invoice",
    )
