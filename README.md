# FeeReconcile

FeeReconcile is an automated, production-grade financial reconciliation web application built for colleges. It ingests simulated student fee payment records (from bank statements, UPI feeds, NEFT logs, cheques, and cash receipts) and reconciles them against student fee obligations in accordance with strict institutional accounting rules.

---

## 1. Quick Start

### One-Command Run
```bash
pip install -r requirements.txt && uvicorn app.main:app --reload
```
Open your browser and navigate to:
```
http://127.0.0.1:8000
```
API Documentation (Swagger / OpenAPI):
```
http://127.0.0.1:8000/docs
```

### Running Tests
Execute the comprehensive Pytest suite:
```bash
pytest tests/test_reconciler.py -v
```

---

## 2. Architecture & Technology Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.x, Pydantic v2, Uvicorn
- **Database**: SQLite (file `feereconcile.db`, automatically initialized on startup)
- **Currency Storage**: Stored strictly as **INTEGER paise** (never floating point) to prevent financial rounding inaccuracies. Displayed in Indian Rupees format (e.g., ₹1,25,000.00).
- **Frontend**: Single-Page App in vanilla HTML5, CSS3, and JavaScript (no frameworks, no build steps, zero third-party UI dependencies).
- **Matching Libraries**: `rapidfuzz` for high-performance token-level fuzzy student name matching.

### Project Structure
```
feeSync/
├── app/
│   ├── main.py                     # FastAPI application entrypoint & static mounts
│   ├── database.py                 # SQLite engine, session, & schema management
│   ├── models.py                   # SQLAlchemy ORM models (Students, Invoices, Payments, Allocations, Exceptions, Batches)
│   ├── schemas.py                  # Pydantic v2 validation & serialization models
│   ├── routers/
│   │   ├── students.py             # Students CRUD & CSV bulk import
│   │   ├── invoices.py             # Fee Invoices CRUD & CSV bulk import
│   │   ├── payments.py             # Payments ingestion, single manual entry, & exceptions resolution
│   │   ├── reports.py              # Financial summary reports & CSV export downloads
│   │   └── demo.py                 # Health check & demo dataset reset/load endpoints
│   ├── services/
│   │   ├── normalizer.py           # Input sanitization, date parsing, paise conversion
│   │   ├── matcher.py              # 4-stage matching cascade (invoice_ref, student_ref, fuzzy name)
│   │   ├── reconciler.py           # Payment allocation, multi-invoice cascade, & invoice status updates
│   │   ├── scoring.py              # 0-100 confidence scoring & human-readable rationale
│   │   └── report.py               # Aggregation calculations & CSV ledger generators
│   └── static/
│       ├── index.html              # Single-page dashboard interface
│       ├── css/styles.css          # Fintech design system, dark mode, & responsive styles
│       └── js/app.js               # Reactive vanilla JavaScript application logic
├── sample_data/
│   ├── students.csv                # 8 realistic Indian college student records
│   ├── invoices.csv                # Mixed tuition invoices with future & past due dates
│   └── payments_demo.csv           # 8 payment scenarios covering all 9 test cases
├── tests/
│   └── test_reconciler.py          # Pytest suite with 100% test scenario coverage
├── requirements.txt
└── README.md
```

---

## 3. CSV Column Formats

### 1. `students.csv`
| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `student_id` | String | Yes | Unique college roll/registration number (uppercase) | `1KS25AI101` |
| `name` | String | Yes | Full student name | `Aarav Sharma` |
| `email` | String | No | Student institutional email | `aarav.sharma@example.edu` |
| `phone` | String | No | Contact number | `9876543210` |

### 2. `invoices.csv`
| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `invoice_id` | String | Yes | Unique invoice number (uppercase) | `INV-001` |
| `student_id` | String | Yes | Target student registration ID | `1KS25AI101` |
| `description` | String | Yes | Fee obligation description | `Semester 1 Tuition` |
| `amount_due` | Number/Rupees | Yes | Amount in INR (converted to paise on import) | `50000` |
| `due_date` | Date | Yes | Due date (`YYYY-MM-DD` or `DD-MM-YYYY`) | `2026-11-15` |

### 3. `payments_demo.csv`
| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `txn_ref` | String | No | Unique transaction reference from bank/UPI | `TXN2026100101` |
| `student_ref`| String | No | Student roll number quoted by payer | `1KS25AI101` |
| `invoice_ref`| String | No | Invoice number quoted in payment remarks | `INV-001` |
| `payer_name` | String | No | Name of remitter / student | `Aarav Sharma` |
| `amount` | Number/Rupees | Yes | Amount in INR (₹, commas, Rs stripped) | `50000` |
| `method` | String | Yes | `UPI`, `NEFT`, `CHEQUE`, `DD`, `CASH`, or `OTHER` | `UPI` |
| `payment_date`| Date | Yes | Transaction date (`YYYY-MM-DD` or `DD-MM-YYYY`) | `2026-10-01` |

---

## 4. Payment Reconciliation Pipeline

For every payment row (from bulk CSV or single manual entry), the engine executes the following steps in sequence:

### Step 1: Normalize & Validate (`normalizer.py`)
- Trims whitespace, uppercases identifiers (`txn_ref`, `student_ref`, `invoice_ref`).
- Normalizes payment method (defaults to `OTHER` if unrecognized).
- Converts monetary strings (e.g., `₹50,000`, `50000.00`, `Rs 50,000`) into integer paise.
- Validates date formats (`YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY`).
- Flags row as **`Invalid`** (generating an `INVALID_ROW` exception) if amount is missing/non-positive, date is unparseable, or all three identifiers (`student_ref`, `invoice_ref`, `payer_name`) are empty.

### Step 2: Duplicate Detection
- **Exact Duplicate**: If `txn_ref` already exists in the database or earlier within the same batch, the record is flagged as **`Duplicate`**, no money is applied to any invoice, and a `DUPLICATE` exception is registered referencing the original payment.
- **Suspected Duplicate**: If `txn_ref` is blank but another payment has the identical `student_ref`, amount, and method within 24 hours, it is routed to **`Review`** with a `DUPLICATE` exception note.

### Step 3: Matching Cascade (`matcher.py`)
1. **Invoice Match**: `invoice_ref` matches an invoice. If `student_ref` is also supplied and conflicts with the invoice owner, routes to **`Review`** with `AMBIGUOUS_MATCH`.
2. **Student Match**: `student_ref` matches a student. The amount is applied to the student's **oldest open invoice** (earliest `due_date` with outstanding balance > 0). If the amount exceeds that invoice, the remainder is carried forward to subsequent open invoices.
3. **Fuzzy Name Match**: `payer_name` is compared against students using RapidFuzz. If best similarity score >= 85% and unique, routes to **`Review`** with `AMBIGUOUS_MATCH` (never auto-applied).
4. **Fallback**: If nothing matches, flags as **`Unmatched`** with an `UNMATCHED` exception.

### Step 4: Amount Comparison & Allocation (`reconciler.py`)
- `amount == outstanding`: Status **`Matched`**, invoice becomes **`Paid`**.
- `amount < outstanding`: Status **`Partial`**, allocated, generates `PARTIAL` exception with remaining balance.
- `amount > outstanding`: Status **`Overpaid`**, outstanding balance allocated, generates `OVERPAID` exception with excess amount.

### Step 5: Confidence Scoring (`scoring.py`)
Calculates a score between 0 and 100:
- Invoice Ref Match: `+50`
- Student ID Verified: `+25`
- Amount matches balance: `+15`
- Name similarity: up to `+10`
Thresholds:
- `>= 90`: Auto-reconciled
- `60 - 89`: Review queue
- `< 60`: Unmatched

### Idempotency
Re-uploading the exact same payment CSV will flag previously recorded transactions as duplicates without altering invoice balances or total collections.

---

## 5. Invoice Status Definitions

Invoice status is strictly computed dynamically from actual allocations:
$$\text{paid} = \sum \text{allocations.amount\_applied}$$
- **`Pending`**: $\text{paid} = 0$ and $\text{due\_date} \ge \text{today}$
- **`Overdue`**: $\text{paid} = 0$ and $\text{due\_date} < \text{today}$
- **`Partial`**: $0 < \text{paid} < \text{amount\_due}$ (or `Overdue` if past due date)
- **`Paid`**: $\text{paid} = \text{amount\_due}$
- **`Overpaid`**: $\text{paid} > \text{amount\_due}$

---

## 6. Short Demo Script

1. **Start the Application**:
   ```bash
   uvicorn app.main:app --reload
   ```
2. **Load Demo Dataset**:
   Click the **"Load Demo Data"** button in the top navigation bar or sidebar.
3. **Observe the Results**:
   - **Dashboard**: KPI cards update instantly to ₹4,75,000.00 Due, ₹2,00,000.00 Received, ₹2,75,000.00 Outstanding, and 42.11% Collection Rate.
   - **Row 1 (`TXN2026100101`)**: Matched to `INV-001` (Aarav Sharma), invoice marked **Paid**.
   - **Row 2 (`TXN2026100202`)**: Matched via student roll number `1KS25AI102` to oldest open invoice `INV-002`, invoice marked **Paid**.
   - **Row 3 (`TXN2026100101`)**: Exact duplicate flagged as **Duplicate** without modifying balances.
   - **Row 4 (`TXN2026100404`)**: ₹25,000 paid against ₹50,000 obligation, invoice marked **Partial** with ₹25,000 remaining.
   - **Row 5 (`TXN2026100505`)**: Unknown student roll number `1KS99XX999`, marked **Unmatched**.
   - **Row 6 (`TXN2026100606`)**: Payer name typo `"Saravnan"` matches student `"Saravanan Natarajan"` with 94% similarity, sent to **Review Queue**.
   - **Row 7 (`TXN2026100707`)**: ₹55,000 payment against ₹50,000 invoice `INV-007`, invoice marked **Paid** and ₹5,000 flagged as **Overpaid**.
   - **Row 8 (`TXN2026100808`)**: Missing payment amount, rejected safely as **Invalid**.
   - **Student 1KS25AI108 (`INV-008`)**: Due date in the past with no payments, marked **Overdue**.
4. **Resolve an Exception**:
   - Navigate to the **Exceptions** tab.
   - Locate the `AMBIGUOUS_MATCH` exception for `"Saravnan"`.
   - Click **"Assign"**, select student `1KS25AI106 (Saravanan Natarajan)`, enter a resolution note, and confirm.
   - Watch the transaction immediately allocate and reconcile the student's tuition invoice!
#   f e e s y n c  
 