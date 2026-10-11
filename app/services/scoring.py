from typing import Optional, Tuple, List


def calculate_name_similarity(name1: Optional[str], name2: Optional[str]) -> float:
    """
    Computes name similarity between two names using rapidfuzz token_sort_ratio
    and token-level comparison (handling typos in first/last names e.g. "Saravnan" vs "Saravanan Natarajan").
    Returns float score from 0.0 to 100.0.
    """
    if not name1 or not name2:
        return 0.0
    from rapidfuzz import fuzz
    n1 = name1.strip().lower()
    n2 = name2.strip().lower()
    base_sort = float(fuzz.token_sort_ratio(n1, n2))
    toks1 = n1.split()
    toks2 = n2.split()
    max_tok = 0.0
    for t1 in toks1:
        for t2 in toks2:
            max_tok = max(max_tok, float(fuzz.ratio(t1, t2)))
    return max(base_sort, max_tok)


def compute_confidence_score(
    invoice_ref_matched: bool = False,
    student_ref_matched: bool = False,
    is_fuzzy_only: bool = False,
    name_similarity: float = 0.0,
    student_agrees_with_invoice: bool = False,
    amount_equals_outstanding: bool = False,
    payer_name_matches: bool = False,
    invoice_student_conflict: bool = False,
    is_tied_candidate: bool = False,
    is_invoice_settled: bool = False,
    is_duplicate: bool = False,
    is_invalid: bool = False,
) -> Tuple[int, str]:
    """
    Computes confidence score (0-100) and plain-English match reason following Step 5 rules:
      Base:
        - invoice_ref exact = 85
        - student_ref exact (no invoice_ref) = 80
        - fuzzy name only = similarity scaled to max 70 (similarity * 0.70)
      Bonuses:
        - +10: student agrees with invoice's student
        - +10: amount equals an open invoice's outstanding
        - +5:  payer name matches student name (similarity >= 85)
      Penalties:
        - -30: invoice_ref and student_ref conflict
        - -20: tied candidates
        - -20: invoice already settled
      Capped at 100 (floor at 0).
      
      Thresholds (caller routing):
        >= 80: auto-reconcile
        50-79: Review (suggest, never apply)
        < 50:  Unmatched
    """
    if is_invalid:
        return 0, "Invalid payment row: data format or required fields missing"

    if is_duplicate:
        return 100, "Duplicate transaction reference detected"

    reasons: List[str] = []
    score = 0

    # 1. Base Score (identity only)
    if invoice_ref_matched:
        base = 85
        score += base
        reasons.append(f"Base: Exact invoice_ref match ({base})")
    elif student_ref_matched:
        base = 80
        score += base
        reasons.append(f"Base: Exact student_ref match ({base})")
    elif is_fuzzy_only:
        base = int(round((name_similarity / 100.0) * 70.0))
        score += base
        reasons.append(f"Base: Fuzzy name match {int(name_similarity)}% ({base})")
    else:
        return 0, "No matching student or invoice found"

    # 2. Bonuses
    if student_agrees_with_invoice:
        score += 10
        reasons.append("+10 (Student ID agrees with invoice student)")

    if amount_equals_outstanding:
        score += 10
        reasons.append("+10 (Amount equals open invoice outstanding)")

    if payer_name_matches and not is_fuzzy_only:
        score += 5
        reasons.append("+5 (Payer name matches student name)")

    # 3. Penalties
    if invoice_student_conflict:
        score -= 30
        reasons.append("-30 (Conflict between invoice ref and student ref)")

    if is_tied_candidate:
        score -= 20
        reasons.append("-20 (Tied candidate matches)")

    if is_invoice_settled:
        score -= 20
        reasons.append("-20 (Target invoice already settled)")

    final_score = min(100, max(0, score))
    match_reason = "; ".join(reasons) + f". Total score: {final_score}/100."
    return final_score, match_reason

