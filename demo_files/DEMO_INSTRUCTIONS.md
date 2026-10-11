# FeeReconcile — Step-by-Step Live Demonstration Guide

Follow this sequence to demonstrate all fee reconciliation and exception resolution cases continuously:

---

### Step 0: Clear Data & Start Fresh
Click the **"Clear data"** button in the top-right header (next to the theme toggle) and confirm.
The dashboard, tables, and exception counters will now be completely clean and empty (0 records).

---

### Step 1: Upload Students Registry
- **File**: `01_STEP1_upload_to_students.csv`
- **Location in App**: Navigate to **Fee Obligations** &rarr; **Students Registry** tab &rarr; Click **"Import CSV"**.
- **Result**: 8 students enrolled (`1KS25AI101` to `1KS25AI108`) with contact details and zero balance.

---

### Step 2: Upload Fee Invoices
- **File**: `02_STEP2_upload_to_invoices.csv`
- **Location in App**: Navigate to **Fee Obligations** &rarr; **Fee Invoices** tab &rarr; Click **"Import CSV"**.
- **Result**: 8 fee invoices issued (`INV-001` to `INV-008`) totaling **₹4,75,000.00**. Dashboard shows 0% collection rate.

---

### Step 3: Demonstrate Exact Match (100% Automated Reconciliation)
- **File**: `03_STEP3_payment_exact_match.csv`
- **Location in App**: Navigate to **Payments** &rarr; Click **"Select CSV file"** (or drag & drop).
- **Scenario**: Payments for Aarav Sharma (₹50,000) and Priya Patel (₹75,000) with matching invoice refs.
- **Result**: Reconciled with **100% confidence**. Invoices `INV-001` and `INV-002` marked as **Paid**. Dashboard collection increases to 26.32%. Zero exceptions created.

---

### Step 4: Demonstrate Partial Payment
- **File**: `04_STEP4_payment_partial.csv`
- **Location in App**: Navigate to **Payments** &rarr; Click **"Select CSV file"**.
- **Scenario**: Ananya Iyer owes ₹50,000 on `INV-004`, but pays ₹25,000 via Cheque.
- **Result**: Invoice `INV-004` transitions to **Partial** with ₹25,000 outstanding. A `PARTIAL` exception is logged in the Exceptions queue with primary action **"Accept partial"**.

---

### Step 5: Demonstrate Ambiguous Match (AI Fuzzy Name Matching)
- **File**: `05_STEP5_payment_ambiguous_fuzzy_name.csv`
- **Location in App**: Navigate to **Payments** &rarr; Click **"Select CSV file"**.
- **Scenario**: Cash payment arrives with payer misspelled as `"Saravnan"` and no student ID or invoice reference.
- **Result**: Match engine detects 76% similarity to student `Saravanan Natarajan (1KS25AI106)`. Logs an `AMBIGUOUS_MATCH` exception with primary button **"Confirm Saravanan Natarajan"**.

---

### Step 6: Demonstrate Duplicate Transaction Detection
- **File**: `06_STEP6_payment_duplicate_txn.csv`
- **Location in App**: Navigate to **Payments** &rarr; Click **"Select CSV file"**.
- **Scenario**: Transaction `TXN2026100101` (already processed in Step 3) is re-submitted.
- **Result**: Engine detects duplicate `txn_ref` and flags it as a `DUPLICATE` exception with primary action **"Confirm duplicate"** to prevent double-crediting.

---

### Step 7: Demonstrate Overpaid / Excess Payment Handling
- **File**: `07_STEP7_payment_overpaid_excess.csv`
- **Location in App**: Navigate to **Payments** &rarr; Click **"Select CSV file"**.
- **Scenario**: Deepa Nair owes ₹50,000 on `INV-007`, but pays ₹55,000 via Demand Draft.
- **Result**: Invoice `INV-007` is fully settled, and **₹5,000.00 excess** is detected. Logs an `OVERPAID` exception with primary action **"Keep as credit"** (or issue refund voucher).

---

### Step 8: Demonstrate Unmatched / Unknown Student Reference
- **File**: `08_STEP8_payment_unmatched_student.csv`
- **Location in App**: Navigate to **Payments** &rarr; Click **"Select CSV file"**.
- **Scenario**: Payment arrives citing student ID `1KS99XX999` which does not exist in student records.
- **Result**: Flagged with **38% low confidence** as an `UNMATCHED` exception with primary action **"Assign to student"**.

---

### Step 9: Demonstrate Invalid Row Validation
- **File**: `09_STEP9_payment_invalid_row.csv`
- **Location in App**: Navigate to **Payments** &rarr; Click **"Select CSV file"**.
- **Scenario**: Payment record has an empty or zero amount (`₹0.00`).
- **Result**: System blocks invalid entry and generates an `INVALID_ROW` exception: *"Amount is missing or invalid"*, guiding operator to fix and re-enter.

---

### Step 10: Shortcut Master Batch (All Scenarios in 1 File)
- **File**: `10_ALL_IN_ONE_master_demo_batch.csv`
- **Scenario**: If you want to demonstrate all 7 reconciliation states in one single upload after Steps 1 & 2, upload this file.
- **Result**: Immediately populates all match categories on the Dashboard, Reconciliation ledger, and Exceptions queue!
