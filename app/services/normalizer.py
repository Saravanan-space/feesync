from datetime import date, datetime
import re
from typing import Optional, Tuple, Dict, Any


VALID_METHODS = {"UPI", "NEFT", "CHEQUE", "DD", "CASH", "OTHER"}


def parse_date_string(date_val: Any) -> Optional[date]:
    """
    Parses date from string or date/datetime object.
    Supports YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, YYYY/MM/DD.
    """
    if not date_val:
        return None
    if isinstance(date_val, date) and not isinstance(date_val, datetime):
        return date_val
    if isinstance(date_val, datetime):
        return date_val.date()
    
    date_str = str(date_val).strip()
    if not date_str:
        return None

    # Try common formats
    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount_to_paise(amount_val: Any) -> Tuple[Optional[int], Optional[str]]:
    """
    Parses amount in Rupees to integer paise.
    Strips currency symbols (₹, Rs, rs, INR), commas, and whitespace.
    Returns (paise_int, error_message).
    """
    if amount_val is None:
        return None, "Amount is missing"

    raw_str = str(amount_val).strip()
    if not raw_str:
        return None, "Amount is empty"

    # Remove currency symbols, INR, Rs, rs, commas, and whitespace
    cleaned = re.sub(r"[₹\s,]|INR|Rs\.?|rs\.?", "", raw_str, flags=re.IGNORECASE)
    if not cleaned:
        return None, "Amount contains no numeric value"

    try:
        val = float(cleaned)
    except ValueError:
        return None, f"Amount '{raw_str}' is non-numeric"

    if val <= 0:
        return None, f"Amount must be strictly positive (got {val})"

    # Convert Rupees to paise
    paise = round(val * 100)
    return paise, None


def normalize_payment_row(row_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Normalizes a payment record (from CSV or manual entry) and validates it.
    Returns (normalized_dict, invalid_reason).
    If invalid_reason is not None, the record is flagged as INVALID.
    """
    txn_ref = str(row_data.get("txn_ref") or "").strip().upper() or None
    student_ref = str(row_data.get("student_ref") or "").strip().upper() or None
    invoice_ref = str(row_data.get("invoice_ref") or "").strip().upper() or None
    payer_name = str(row_data.get("payer_name") or "").strip() or None

    # Normalize method
    raw_method = str(row_data.get("method") or "").strip().upper()
    method = raw_method if raw_method in VALID_METHODS else "OTHER"

    # Validate amount
    amount_val = row_data.get("amount")
    paise, amount_err = parse_amount_to_paise(amount_val)
    if amount_err:
        return {
            "txn_ref": txn_ref,
            "student_ref": student_ref,
            "invoice_ref": invoice_ref,
            "payer_name": payer_name,
            "amount": 0,
            "method": method,
            "payment_date": parse_date_string(row_data.get("payment_date")) or date.today(),
        }, amount_err

    # Validate date
    payment_date = parse_date_string(row_data.get("payment_date"))
    if not payment_date:
        return {
            "txn_ref": txn_ref,
            "student_ref": student_ref,
            "invoice_ref": invoice_ref,
            "payer_name": payer_name,
            "amount": paise,
            "method": method,
            "payment_date": date.today(),
        }, "Payment date is missing or in an invalid format"

    # Validate student_ref / invoice_ref / payer_name presence
    if not student_ref and not invoice_ref and not payer_name:
        return {
            "txn_ref": txn_ref,
            "student_ref": student_ref,
            "invoice_ref": invoice_ref,
            "payer_name": payer_name,
            "amount": paise,
            "method": method,
            "payment_date": payment_date,
        }, "Record must contain at least one of: student_ref, invoice_ref, or payer_name"

    return {
        "txn_ref": txn_ref,
        "student_ref": student_ref,
        "invoice_ref": invoice_ref,
        "payer_name": payer_name,
        "amount": paise,
        "method": method,
        "payment_date": payment_date,
    }, None
