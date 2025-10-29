import os
import logging
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from zoneinfo import ZoneInfo
from typing import Optional
import hmac
import hashlib
import threading
import time
import re
# optional cross-process file lock to protect Excel in multi-process deployments
try:
    import portalocker
except Exception:
    portalocker = None

import pandas as pd
from flask import Flask, request, jsonify, abort, send_file

# =========================
# Config & constants
# =========================
TZ = ZoneInfo("Africa/Johannesburg")
INTEREST_RATE = Decimal("0.30")     # 30% per 30-day period
LOAN_TERM_DAYS = 30
CURRENCY_Q = Decimal("0.01")
BACKUP_DIR = os.getenv("STOKVEL_BACKUPS_DIR", "backups")

SHEETS = {
    "members": "Members",
    "contrib": "Contributions",
    "loans": "Loans",
    "payments": "Payments",
    "bank": "Bank",
}

COLS = {
    "members": ["Member Name", "Phone", "Active"],
    "contrib": ["Date", "Member Name", "Amount", "Bank Charge", "Net", "Note", "Message ID"],
    "loans": [
        "Loan ID", "Name of the stokvel member", "Name of the borrower", "Amount borrowed",
        "Date borrowed", "Interest Rate", "Interest Periods", "Interest", "Due Amount",
        "Due Date", "Interest extended", "Paid", "Pay Date", "Status", "Overdue Since", "Message ID", "Aging Bucket"
    ],
    "payments": ["Loan ID", "Member Name", "Borrower", "When", "Amount", "Type", "Message ID", "Proof URL"],
    "bank": ["Date", "Description", "Credit", "Debit", "Bank Charge", "Balance", "Message ID"],
}

STATE = {
    "IDLE": "idle",
    "MENU": "awaiting_option",
    "BORROWER_NAME": "awaiting_borrower_name",
    "BORROW_AMOUNT": "awaiting_borrow_amount",
    "CONFIRM_BORROW": "confirm_borrow",
    "CONTRIB_AMOUNT": "awaiting_contribution_amount",
    "CONTRIB_CHARGE": "awaiting_contribution_charge",
    "PAY_SELECT_BORROWER": "awaiting_borrower_selection",
    "PAY_AMOUNT": "awaiting_payment_amount",
    "PAY_PROOF": "awaiting_proof_upload",
}

# =========================
# Helpers
# =========================

def Znow():
    return datetime.now(TZ)


def d(x) -> Decimal:
    return Decimal(str(x))


def money(x) -> Decimal:
    return d(x).quantize(CURRENCY_Q, rounding=ROUND_HALF_UP)


def fmt_money(x: Decimal) -> str:
    return f"{x:.2f}"


def store_local(dt: datetime) -> str:
    """Format a timezone-aware datetime for storage as local (TZ) naive ISO-like string.

    Stores times as "YYYY-MM-DD HH:MM:SS" (no timezone marker). On read we will treat
    such naive timestamps as occurring in the configured TZ (Africa/Johannesburg).
    """
    if dt is None:
        return None
    # ensure it's in the configured timezone
    try:
        dt_tz = dt.astimezone(TZ)
    except Exception:
        # if dt is naive, assume it's local and attach TZ then convert
        dt_tz = dt.replace(tzinfo=TZ)
    # drop tzinfo for storage
    return dt_tz.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def parse_stored_datetime(val) -> Optional[datetime]:
    """Parse a stored datetime string (possibly naive) and return a TZ-aware datetime.

    All returned datetimes will have tzinfo set to the configured TZ (Africa/Johannesburg).
    If input is naive (no timezone), it is interpreted as being in the configured TZ.
    If input has a different timezone, it is converted to the configured TZ.
    Returns None only if input is None.

    This is the complement to store_local() - it takes timestamps stored as naive local
    time and reattaches the proper timezone information.
    """
    if val is None:
        return None
        
    # Convert to pandas Timestamp first for easier timezone handling
    ts = pd.to_datetime(val)
    
    # Handle naive input - interpret as local time
    if ts.tz is None:
        try:
            # Proper localization for naive timestamps
            ts = ts.tz_localize(TZ)
        except Exception:
            # Fallback if localization fails (e.g. ambiguous/nonexistent times)
            ts = ts.tz_localize(None).replace(tzinfo=TZ)
            
    # Convert to our timezone if needed
    ts = ts.tz_convert(TZ)
    
    # Convert Timestamp to standard datetime
    return ts.to_pydatetime()


def parse_amount(text: str) -> Decimal:
    """Parse inputs like 'R 1 500.75' or '1500.75' into Decimal money.

    Produces ValueError on invalid input with a helpful message.
    """
    if text is None:
        raise ValueError("empty amount")
    s = str(text).strip()
    if s == '':
        raise ValueError("empty amount")
    # support accounting parentheses '(150)' to mean negative values
    is_parentheses_negative = bool(re.match(r"^\(.*\)$", s.strip()))
    if is_parentheses_negative:
        s = s.strip()[1:-1].strip()

    # remove common currency symbols and thousands separators (commas) and whitespace
    s = re.sub(r"[R$€\,\s]", "", s)

    # allow an explicit leading + or - sign
    sign = 1
    if s.startswith('+'):
        s = s[1:]
    elif s.startswith('-'):
        sign = -1
        s = s[1:]

    # keep digits and at most one dot
    s = re.sub(r"[^0-9.]", "", s)
    if s == '' or s == '.' or s == '-':
        raise ValueError(f"Invalid money value: {text}")

    try:
        val = Decimal(s) * Decimal(sign)
        if is_parentheses_negative:
            val = -val
        return money(val)
    except InvalidOperation:
        raise ValueError(f"Invalid money value: {text}")


def sanitize_soft(text: str) -> str:
    return re.sub(r"[^\w\s\.\-@']", "", str(text), flags=re.UNICODE).strip()


def normalize_sender_for_rate(sender: str) -> str:
    """Normalize an incoming sender identifier to a stable key for rate-limiting.

    Preference order:
      - If sender contains a long sequence of digits (phone number), return digits-only.
      - Otherwise return the original sender string lowercased.

    This prevents rate buckets from shifting when a user's display name changes.
    """
    if not sender:
        return ''
    s = str(sender)
    # look for longest digit substring (phone numbers), else fallback
    digit_groups = re.findall(r"\d+", s)
    if digit_groups:
        # pick the longest group of digits as the likely phone number
        longest = max(digit_groups, key=len)
        if len(longest) >= 6:
            return longest
    return s.strip().lower()


def periods_elapsed(start: datetime, asof: datetime, period_days=LOAN_TERM_DAYS) -> int:
    days = (asof - start).days
    # interpret negative or zero as first started period
    if days <= 0:
        return 1
    # count full periods: days exactly equal to period_days should count as the next period
    return (days // period_days) + 1


def compute_due(principal: Decimal, rate: Decimal, borrowed_at: datetime, paid_total: Decimal, asof: datetime):
    p = periods_elapsed(borrowed_at, asof)
    interest_total = money(principal * rate * Decimal(p))
    due = money(principal + interest_total - paid_total)
    return p, interest_total, max(due, Decimal("0.00"))


def aging_bucket(due_date: datetime, asof: datetime) -> str:
    delta = (asof.date() - due_date.date()).days
    if delta <= 0:
        return "Current"
    if delta <= 30:
        return "1-30"
    if delta <= 60:
        return "31-60"
    if delta <= 90:
        return "61-90"
    return "90+"

# =========================
# Excel repository
# =========================

class ExcelRepository:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        os.makedirs(BACKUP_DIR, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.path):
            frames = {
                'members': pd.DataFrame(columns=COLS['members']),
                'contrib': pd.DataFrame(columns=COLS['contrib']),
                'loans': pd.DataFrame(columns=COLS['loans']),
                'payments': pd.DataFrame(columns=COLS['payments']),
                'bank': pd.DataFrame(columns=COLS['bank']),
            }
            self._write(frames)

    def _acquire_file_lock(self):
        """Return a context manager that acquires a cross-process lock when portalocker
        is available, otherwise fall back to the in-process threading lock."""
        if portalocker:
            # portalocker.Lock provides a context manager
            return portalocker.Lock(self.path + ".lock", timeout=10)
        else:
            class _DummyLock:
                def __init__(self, outer):
                    self._outer = outer
                def __enter__(self):
                    return self._outer.lock.acquire()
                def __exit__(self, exc_type, exc, tb):
                    return self._outer.lock.release()
            return _DummyLock(self)

    def _read(self):
        # use file lock to avoid races when multiple processes read/write the Excel file
        lock_ctx = self._acquire_file_lock()
        with lock_ctx:
            xl = pd.ExcelFile(self.path)
            def get_df(key):
                sheet = SHEETS[key]
                if sheet in xl.sheet_names:
                    df = xl.parse(sheet)
                else:
                    df = pd.DataFrame()
                # ensure columns exist
                for c in COLS[key]:
                    if c not in df.columns:
                        df[c] = pd.Series([None] * len(df))
                return df[COLS[key]]
            frames = {
                'members': get_df('members'),
                'contrib': get_df('contrib'),
                'loans': get_df('loans'),
                'payments': get_df('payments'),
                'bank': get_df('bank'),
            }
            try:
                self._validate_bank_balances(frames)
            except Exception:
                logging.exception("Failed during bank balance validation on read")
            return frames

    def _read_no_lock(self):
        """Read workbook frames without acquiring the cross-process lock.

        This should only be used when the caller already holds the file lock
        (via _acquire_file_lock) to avoid a TOCTOU race.
        """
        xl = pd.ExcelFile(self.path)

        def get_df(key):
            sheet = SHEETS[key]
            if sheet in xl.sheet_names:
                df = xl.parse(sheet)
            else:
                df = pd.DataFrame()
            # ensure columns exist
            for c in COLS[key]:
                if c not in df.columns:
                    df[c] = pd.Series([None] * len(df))
            return df[COLS[key]]

        frames = {
            'members': get_df('members'),
            'contrib': get_df('contrib'),
            'loans': get_df('loans'),
            'payments': get_df('payments'),
            'bank': get_df('bank'),
        }
        try:
            self._validate_bank_balances(frames)
        except Exception:
            logging.exception("Failed during bank balance validation on read (no-lock)")
        return frames

    def _backup(self):
        ts = Znow().strftime("%Y%m%d-%H%M%S")
        base = os.path.basename(self.path)
        name, ext = os.path.splitext(base)
        dest = os.path.join(BACKUP_DIR, f"{name}-{ts}{ext}")
        try:
            shutil.copy2(self.path, dest)
        except Exception:
            logging.exception("Failed to backup Excel file")

    def _write(self, frames: dict):
        # prefer a cross-process lock when available; fall back to the in-process lock
        lock_ctx = self._acquire_file_lock()
        with lock_ctx:
            with self.lock:
                # backup current file before writing
                if os.path.exists(self.path):
                    self._backup()
                # Recompute derived fields (e.g., Bank Balance) before persisting to keep the file authoritative
                try:
                    self._recompute_bank_balances(frames)
                except Exception:
                    logging.exception("Failed to recompute bank balances before write")
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
                tmp.close()
                try:
                    with pd.ExcelWriter(tmp.name, engine='openpyxl', mode='w') as w:
                        frames['members'].to_excel(w, SHEETS['members'], index=False)
                        frames['contrib'].to_excel(w, SHEETS['contrib'], index=False)
                        frames['loans'].to_excel(w, SHEETS['loans'], index=False)
                        frames['payments'].to_excel(w, SHEETS['payments'], index=False)
                        frames['bank'].to_excel(w, SHEETS['bank'], index=False)
                    shutil.move(tmp.name, self.path)
                finally:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)

    def _write_unlocked(self, frames: dict):
        """Write workbook frames assuming the caller already holds both the
        cross-process lock and the in-process lock.

        This avoids deadlocks from calling _write while already holding locks.
        """
        # Recompute derived fields (e.g., Bank Balance) before persisting to keep the file authoritative
        try:
            self._recompute_bank_balances(frames)
        except Exception:
            logging.exception("Failed to recompute bank balances before unlocked write")

        # backup current file before writing
        if os.path.exists(self.path):
            try:
                self._backup()
            except Exception:
                logging.exception("Failed to backup Excel file before unlocked write")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        tmp.close()
        try:
            with pd.ExcelWriter(tmp.name, engine='openpyxl', mode='w') as w:
                frames['members'].to_excel(w, SHEETS['members'], index=False)
                frames['contrib'].to_excel(w, SHEETS['contrib'], index=False)
                frames['loans'].to_excel(w, SHEETS['loans'], index=False)
                frames['payments'].to_excel(w, SHEETS['payments'], index=False)
                frames['bank'].to_excel(w, SHEETS['bank'], index=False)
            shutil.move(tmp.name, self.path)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def _recompute_bank_balances(self, frames: dict):
        """Derive the Balance column as a running total of Credit - Debit - Bank Charge.

        This method mutates frames['bank'] in-place and formats the Balance column with two decimals.
        It is tolerant of missing or malformed numeric values.
        """
        bank = frames.get('bank')
        if bank is None or bank.empty:
            return

        # helper to parse numeric-like values into Decimal safely
        def _to_decimal(val):
            try:
                if pd.isna(val):
                    return Decimal('0.00')
                # Remove any non-numeric characters except dot and minus
                s = re.sub(r"[^0-9.\-]", "", str(val))
                if s == '' or s == '.' or s == '-':
                    return Decimal('0.00')
                return money(Decimal(s))
            except Exception:
                return Decimal('0.00')

        running = Decimal('0.00')
        # If the bank frame has a custom index, iterate by index to avoid positional assumptions
        for idx in bank.index:
            credit = _to_decimal(bank.at[idx, 'Credit']) if 'Credit' in bank.columns else Decimal('0.00')
            debit = _to_decimal(bank.at[idx, 'Debit']) if 'Debit' in bank.columns else Decimal('0.00')
            charge = _to_decimal(bank.at[idx, 'Bank Charge']) if 'Bank Charge' in bank.columns else Decimal('0.00')
            running = money(running + credit - debit - charge)
            # store formatted string to match existing file expectations
            bank.at[idx, 'Balance'] = fmt_money(running)
        frames['bank'] = bank

    def _validate_bank_balances(self, frames: dict):
        """Validate that stored Balance values in the Bank sheet match the derived running total.

        This method logs a warning for each row where the persisted Balance differs from the
        computed Balance (Credit - Debit - Bank Charge running total). It does NOT modify data.
        """
        bank = frames.get('bank')
        if bank is None or bank.empty:
            return

        def _to_decimal(val):
            try:
                if pd.isna(val):
                    return Decimal('0.00')
                s = re.sub(r"[^0-9.\-]", "", str(val))
                if s == '' or s == '.' or s == '-':
                    return Decimal('0.00')
                return money(Decimal(s))
            except Exception:
                return Decimal('0.00')

        running = Decimal('0.00')
        for idx in bank.index:
            credit = _to_decimal(bank.at[idx, 'Credit']) if 'Credit' in bank.columns else Decimal('0.00')
            debit = _to_decimal(bank.at[idx, 'Debit']) if 'Debit' in bank.columns else Decimal('0.00')
            charge = _to_decimal(bank.at[idx, 'Bank Charge']) if 'Bank Charge' in bank.columns else Decimal('0.00')
            running = money(running + credit - debit - charge)
            # parse stored balance
            stored = Decimal('0.00')
            try:
                if 'Balance' in bank.columns:
                    stored = _to_decimal(bank.at[idx, 'Balance'])
            except Exception:
                stored = Decimal('0.00')
            if stored != running:
                desc = bank.at[idx, 'Description'] if 'Description' in bank.columns else ''
                logging.warning(
                    f"Bank balance mismatch at index {idx}: stored={fmt_money(stored)} derived={fmt_money(running)} desc=\"{desc}\""
                )

    # ---------- Public API ----------
    def latest_balance(self) -> Decimal:
        """Compute current bank balance from ledger entries.
        
        Does not trust stored Balance values - recomputes from Credit - Debit - Bank Charge.
        Logs a warning if the computed balance differs from the last stored Balance.
        """
        frames = self._read()
        bank = frames['bank']
        if bank.empty:
            return Decimal("0.00")
            
        # Helper to safely parse numeric values
        def _to_decimal(val) -> Decimal:
            if pd.isna(val):
                return Decimal('0.00')
            try:
                # Handle various formats including currency symbols and parentheses
                return parse_amount(str(val))
            except (ValueError, InvalidOperation):
                logging.warning(f"Invalid numeric value in bank ledger: {val}")
                return Decimal('0.00')
        
        # Compute running balance from all entries
        balance = Decimal('0.00')
        for idx in bank.index:
            credit = _to_decimal(bank.at[idx, 'Credit'])
            debit = _to_decimal(bank.at[idx, 'Debit'])
            charge = _to_decimal(bank.at[idx, 'Bank Charge'])
            balance = money(balance + credit - debit - charge)
            
        # Compare with stored balance and warn if different
        try:
            stored = money(bank.iloc[-1]['Balance'] or 0)
            if stored != balance:
                desc = bank.iloc[-1].get('Description', '')
                logging.warning(
                    f"Latest bank balance mismatch: stored={fmt_money(stored)} "
                    f"computed={fmt_money(balance)} desc=\"{desc}\""
                )
        except Exception as e:
            logging.warning(f"Could not verify stored balance: {e}")
            
        return balance

    def member_by_sender(self, sender: str):
        frames = self._read()
        mem = frames['members']
        if not sender:
            return None

        def _normalize_phone(s):
            return re.sub(r"\D", "", str(s or ""))

        s_name_norm = str(sender).strip().lower()
        # by name (trim and compare lowercase)
        row = mem[mem['Member Name'].fillna('').astype(str).str.strip().str.lower() == s_name_norm]
        if not row.empty:
            return row.iloc[0]
        # by phone: normalize stored phones and input to digits-only
        s_phone = _normalize_phone(sender)
        phones = mem['Phone'].fillna('').astype(str).apply(_normalize_phone)
        row = mem[phones == s_phone]
        if not row.empty:
            return row.iloc[0]
        return None

    def add_contribution(self, member_name: str, amount: Decimal, bank_charge: Decimal, note: str = "", message_id: str | None = None):
        frames = self._read()
        contrib = frames['contrib']
        bank = frames['bank']
        date = Znow().date().isoformat()

        if message_id and not contrib[contrib['Message ID'] == str(message_id)].empty:
            return frames  # duplicate ignored

        net = money(amount - bank_charge)
        contrib.loc[len(contrib)] = [date, member_name, fmt_money(amount), fmt_money(bank_charge), fmt_money(net), note, str(message_id) if message_id else None]

        last_balance = money(bank.iloc[-1]['Balance'] if not bank.empty else 0)
        new_balance = money(last_balance + amount - bank_charge)
        # avoid duplicate bank entry
        if not (message_id and not bank[bank['Message ID'] == str(message_id)].empty):
            bank.loc[len(bank)] = [date, f"Contribution: {member_name}", fmt_money(amount), "0.00", fmt_money(bank_charge), fmt_money(new_balance), str(message_id) if message_id else None]

        frames['contrib'] = contrib
        frames['bank'] = bank
        self._write(frames)
        return frames

    def add_loan(self, member_name: str, borrower: str, amount: Decimal, message_id: str | None = None):
        # Perform read-check-mutate-write under a single file lock to avoid TOCTOU races.
        lock_ctx = self._acquire_file_lock()
        with lock_ctx:
            with self.lock:
                now = Znow()

                # read frames without acquiring the lock again
                frames = self._read_no_lock()
                loans, bank = frames['loans'], frames['bank']

                # idempotency: if message_id already exists on a loan row, return existing Loan ID
                if message_id and 'Message ID' in loans.columns:
                    existing = loans[loans['Message ID'] == str(message_id)]
                    if not existing.empty:
                        return existing.iloc[-1]['Loan ID']

                loan_id = str(uuid.uuid4())
                interest_periods = 1
                interest = money(amount * INTEREST_RATE * Decimal(interest_periods))
                due = money(amount + interest)
                due_date = (now + timedelta(days=LOAN_TERM_DAYS)).date().isoformat()

                # Recompute/derive bank balances from the ledger in the locked context
                try:
                    self._recompute_bank_balances(frames)
                except Exception:
                    logging.exception("Failed to recompute bank balances during add_loan")

                last_balance = money(bank.iloc[-1]['Balance'] if not bank.empty else 0)
                if amount > last_balance:
                    raise ValueError("Insufficient available balance to issue loan.")

                loan_row = {
                    "Loan ID": loan_id,
                    "Name of the stokvel member": member_name,
                    "Name of the borrower": borrower,
                    "Amount borrowed": fmt_money(amount),
                    "Date borrowed": store_local(now),
                    "Interest Rate": str(INTEREST_RATE),
                    "Interest Periods": interest_periods,
                    "Interest": fmt_money(interest),
                    "Due Amount": fmt_money(due),
                    "Due Date": due_date,
                    "Interest extended": "0.00",
                    "Paid": "0.00",
                    "Pay Date": None,
                    "Status": "Active",
                    "Overdue Since": None,
                    "Message ID": str(message_id) if message_id else None,
                    "Aging Bucket": "Current",
                }
                loans.loc[len(loans)] = [loan_row[c] for c in COLS['loans']]

                new_balance = money(last_balance - amount)
                if not (message_id and not bank[bank['Message ID'] == str(message_id)].empty):
                    bank.loc[len(bank)] = [now.date().isoformat(), f"Loan to {borrower}", "0.00", fmt_money(amount), "0.00", fmt_money(new_balance), str(message_id) if message_id else None]

                frames['loans'], frames['bank'] = loans, bank
                # write without trying to re-acquire locks (we already hold them)
                self._write_unlocked(frames)
                return loan_id

    def get_loan_by_id(self, loan_id: str) -> pd.Series | None:
        """Get a loan by its ID. Much safer than matching by multiple fields."""
        frames = self._read()
        loans = frames['loans']
        mask = (loans['Loan ID'].fillna('') == loan_id)
        if not mask.any():
            return None
        return loans[mask].iloc[-1]

    def get_active_loan(self, member_name: str, borrower: str) -> pd.Series | None:
        """Legacy method - prefer get_loan_by_id when Loan ID is available."""
        frames = self._read()
        loans = frames['loans']
        mask = (
            (loans['Name of the stokvel member'].fillna('').str.lower() == member_name.lower()) &
            (loans['Name of the borrower'].fillna('').str.lower() == borrower.lower()) &
            (loans['Status'] == 'Active')
        )
        if not mask.any():
            return None
        return loans[mask].iloc[-1]

    def apply_payment_by_id(self, loan_id: str, amount: Decimal, message_id: str | None = None) -> tuple[int, Decimal]:
        """Apply a payment to a loan using its ID. Returns (periods, interest_total)."""
        loan = self.get_loan_by_id(loan_id)
        if loan is None:
            raise LookupError(f"No loan found with ID {loan_id}")
        if loan['Status'] != 'Active':
            raise ValueError(f"Loan {loan_id} is not active")
            
        # compute interest
        borrowed_at = parse_stored_datetime(loan['Date borrowed'])
        if borrowed_at is None:
            raise ValueError("Invalid loan borrow date")
            
        principal = money(loan['Amount borrowed'])
        paid_so_far = money(loan['Paid'] or 0)
        periods, interest_total, _ = compute_due(principal, INTEREST_RATE, borrowed_at, paid_so_far, Znow())
        
        # apply the payment
        self.apply_payment(loan, amount, periods, interest_total, message_id)
        return periods, interest_total

    def ensure_loan_id(self, loan_index: int) -> str:
        """Ensure a loan has a valid Loan ID, creating one if needed."""
        frames = self._read()
        loans = frames['loans']
        if pd.isna(loans.loc[loan_index, 'Loan ID']) or not str(loans.loc[loan_index, 'Loan ID']).strip():
            new_id = str(uuid.uuid4())
            loans.loc[loan_index, 'Loan ID'] = new_id
            frames['loans'] = loans
            self._write(frames)
            return new_id
        return str(loans.loc[loan_index, 'Loan ID'])

    def apply_payment(self, loan_row: pd.Series, amount: Decimal, periods: int, interest_total: Decimal, message_id: str | None = None):
        frames = self._read()
        loans, payments, bank = frames['loans'], frames['payments'], frames['bank']
        now = Znow()
        
        # Prefer locating the loan by its Loan ID when available (much safer).
        idx = None
        provided_id = None
        try:
            # loan_row may be a Series from a previous read; guard access
            provided_id = loan_row.get('Loan ID') if 'Loan ID' in loan_row.index else None
        except Exception:
            provided_id = None

        if provided_id and not pd.isna(provided_id) and str(provided_id).strip():
            matches = loans[loans['Loan ID'] == str(provided_id)]
            if not matches.empty:
                idx = matches.index[0]

        # Fallback: match by identifying columns (legacy / missing Loan ID)
        if idx is None:
            loan_mask = (
                (loans['Name of the stokvel member'] == loan_row['Name of the stokvel member']) &
                (loans['Name of the borrower'] == loan_row['Name of the borrower']) &
                (loans['Amount borrowed'] == loan_row['Amount borrowed']) &
                (loans['Date borrowed'] == loan_row['Date borrowed'])
            )
            if not loan_mask.any():
                raise ValueError("Could not find matching loan")
            idx = loans[loan_mask].index[0]

        # idempotency on payments and bank
        if message_id and (not payments[payments['Message ID'] == str(message_id)].empty):
            return frames

        # ensure Loan ID
        loan_id = loans.loc[idx, 'Loan ID']
        if pd.isna(loan_id) or not str(loan_id).strip():
            loan_id = str(uuid.uuid4())
            loans.loc[idx, 'Loan ID'] = loan_id

        # Recompute and update loan summary
        principal = money(loan_row['Amount borrowed'])
        paid_so_far = money(loan_row['Paid'] or 0)
        due_before = money(loan_row['Due Amount'])
        due_now = money(principal + interest_total - paid_so_far)

        new_paid = money(paid_so_far + amount)
        new_due = money(principal + interest_total - new_paid)

        # Update loan fields using loc instead of at
        loans.loc[idx, 'Interest Periods'] = periods
        loans.loc[idx, 'Interest'] = fmt_money(interest_total)
        # Compute and store any interest beyond the base first period (idempotent)
        try:
            base_interest = money(principal * INTEREST_RATE)
            interest_extended = max(money(interest_total) - base_interest, Decimal('0.00'))
        except Exception:
            base_interest = Decimal('0.00')
            interest_extended = Decimal('0.00')
        loans.loc[idx, 'Interest extended'] = fmt_money(interest_extended)
        loans.loc[idx, 'Due Amount'] = fmt_money(max(new_due, Decimal('0.00')))
        loans.loc[idx, 'Paid'] = fmt_money(new_paid)
        loans.loc[idx, 'Pay Date'] = store_local(now)
        loans.loc[idx, 'Status'] = 'Settled' if new_due <= Decimal('0.00') else 'Active'
        # overdue fields
        try:
            due_date = parse_stored_datetime(loan_row['Due Date'])
            if due_date is not None:
                # keep comparisons in the configured TZ
                now_tz = Znow()
                if new_due > Decimal('0.00') and now_tz > due_date:
                    loans.loc[idx, ['Overdue Since', 'Aging Bucket']] = [
                        due_date.date().isoformat(),
                        aging_bucket(due_date, now_tz)
                    ]
            else:
                loans.loc[idx, ['Overdue Since', 'Aging Bucket']] = [None, 'Current']
        except Exception:
            loans.loc[idx, ['Overdue Since', 'Aging Bucket']] = [None, 'Current']

        # Payments ledger
        payments.loc[len(payments)] = [
            loan_id,
            loan_row['Name of the stokvel member'],
            loan_row['Name of the borrower'],
            store_local(now),
            fmt_money(amount),
            'Unspecified',  # could be Interest/Principal/Mixed if you add allocation rule
            str(message_id) if message_id else None,
            None,
        ]

        # Bank ledger (avoid duplicate by message_id)
        if not (message_id and not bank[bank['Message ID'] == str(message_id)].empty):
            last_balance = money(bank.iloc[-1]['Balance'] if not bank.empty else 0)
            new_balance = money(last_balance + amount)
            bank.loc[len(bank)] = [now.date().isoformat(), f"Payment from {loan_row['Name of the borrower']}", fmt_money(amount), "0.00", "0.00", fmt_money(new_balance), str(message_id) if message_id else None]

        frames['loans'], frames['payments'], frames['bank'] = loans, payments, bank
        self._write(frames)
        return frames

# =========================
# Stokvel service (business)
# =========================

class StokvelService:
    def __init__(self, repo: ExcelRepository, rate: Decimal = INTEREST_RATE):
        self.repo = repo
        self.rate = rate

    def verify_member(self, sender: str):
        row = self.repo.member_by_sender(sender)
        if row is None:
            raise PermissionError("You are not registered as a member.")
        if str(row.get("Active", "True")).lower() == "false":
            raise PermissionError("Your membership is inactive.")
        return row["Member Name"]

    def available_balance(self) -> Decimal:
        return self.repo.latest_balance()

    def contribute(self, member: str, amount_text: str, charge_text: str, note: str, message_id: str | None = None):
        amount = parse_amount(amount_text)
        charge = parse_amount(charge_text)
        # Strict invariants: amount must be positive, charge non-negative and not exceed amount
        if amount <= 0:
            raise ValueError("Contribution amount must be positive.")
        if charge < 0:
            raise ValueError("Bank charge cannot be negative.")
        if amount < charge:
            raise ValueError("Bank charge cannot exceed contribution amount.")
        self.repo.add_contribution(member, amount, charge, note, message_id)
        return amount, charge

    def borrow_preview(self, member: str, borrower: str, amount_text: str):
        """Return a preview (amount, interest, due, due_date) without persisting a loan."""
        amount = parse_amount(amount_text)
        if amount <= 0:
            raise ValueError("Amount must be positive.")
        interest = money(amount * self.rate)
        due = money(amount + interest)
        due_date = (Znow() + timedelta(days=LOAN_TERM_DAYS)).date().isoformat()
        return amount, interest, due, due_date

    def create_loan(self, member: str, borrower: str, amount: Decimal, message_id: str | None = None):
        """Persist a loan (called after user confirmation). Returns loan_id."""
        return self.repo.add_loan(member, borrower, amount, message_id)

    def pay_by_id(self, loan_id: str, amount_text: str, message_id: str | None = None) -> tuple[Decimal, int]:
        """Apply a payment using the loan ID. Returns (amount_paid, periods)."""
        amount = parse_amount(amount_text)
        if amount <= 0:
            raise ValueError("Amount must be positive.")
            
        periods, interest_total = self.repo.apply_payment_by_id(loan_id, amount, message_id)
        return amount, periods
        
    def pay(self, member: str, borrower: str, amount_text: str, message_id: str | None = None):
        """Legacy payment method - prefer pay_by_id when Loan ID is available."""
        loan = self.repo.get_active_loan(member, borrower)
        if loan is None:
            raise LookupError("No active loan found for this borrower under your name.")
            
        # Always use the ID-based path when we have an ID
        loan_id = str(loan['Loan ID']).strip()
        if loan_id:
            return self.pay_by_id(loan_id, amount_text, message_id)
            
        # Legacy path for loans without IDs (should be rare/none)
        amount = parse_amount(amount_text)
        if amount <= 0:
            raise ValueError("Amount must be positive.")
            
        borrowed_at = parse_stored_datetime(loan['Date borrowed'])
        if borrowed_at is None:
            raise ValueError("Invalid loan borrow date")
            
        principal = money(loan['Amount borrowed'])
        paid_so_far = money(loan['Paid'] or 0)
        periods, interest_total, _ = compute_due(principal, self.rate, borrowed_at, paid_so_far, Znow())
        self.repo.apply_payment(loan, amount, periods, interest_total, message_id)
        return amount, periods

    def list_active_borrowers(self, member_name: str) -> list:
        """Return a sorted list of borrower names with active loans under the given member.

        Kept small and efficient; lives on the service layer so callers (e.g., ChatFSM)
        don't need to depend on repository internals.
        """
        frames = self.repo._read()
        loans = frames['loans']
        mask = (
            (loans['Name of the stokvel member'].fillna('').str.lower() == member_name.lower()) &
            (loans['Status'] == 'Active')
        )
        borrowers = sorted(loans[mask]['Name of the borrower'].dropna().unique().tolist(), key=lambda x: x.lower())
        return borrowers

    def current_due(self, member: str, borrower: str) -> tuple[Decimal, Decimal, Decimal, datetime]:
        """Get current loan information for a borrower.
        
        Returns:
            tuple of (principal, total_paid, current_due_amount, borrowed_at)
            or raises ValueError if no active loan found
        """
        loan = self.repo.get_active_loan(member, borrower)
        if loan is None:
            raise ValueError(f"No active loan found for {borrower}")

        # parse stored/prioritized values safely
        try:
            principal = money(loan['Amount borrowed'])
        except Exception:
            raise ValueError(f"Invalid principal for loan of {borrower}")

        try:
            paid = money(loan.get('Paid') or 0)
        except Exception:
            paid = Decimal('0.00')

        borrowed_at = parse_stored_datetime(loan.get('Date borrowed'))
        if borrowed_at is None:
            raise ValueError(f"Invalid loan record - missing borrow date for {borrower}")

        _, _, due = compute_due(principal, self.rate, borrowed_at, paid, Znow())
        return principal, paid, due, borrowed_at

    def recompute_all_loans(self, asof: Optional[datetime] = None) -> dict:
        """Recompute interest, due amounts and aging for all loans.

        This updates the Loans sheet in-place and persists the workbook.
        Returns a summary dict with counts of updated rows.
        """
        if asof is None:
            asof = Znow()

        frames = self.repo._read()
        loans = frames['loans']
        updated = 0
        total = 0
        overwritten = 0

        # iterate rows and update derived fields for Active loans
        for idx in loans.index:
            try:
                status = loans.at[idx, 'Status'] if 'Status' in loans.columns else 'Active'
                if status != 'Active':
                    continue

                total += 1
                # parse stored values
                principal = money(loans.at[idx, 'Amount borrowed'])
                paid = money(loans.at[idx, 'Paid'] or 0)
                borrowed_at = parse_stored_datetime(loans.at[idx, 'Date borrowed'])
                due_date = parse_stored_datetime(loans.at[idx, 'Due Date'])

                if borrowed_at is None:
                    logging.warning(f"Skipping loan idx {idx} missing borrow date")
                    continue

                periods, interest_total, due = compute_due(principal, self.rate, borrowed_at, paid, asof)

                # base interest (first period) for idempotent Interest extended calculation
                base_interest = money(principal * INTEREST_RATE)
                interest_extended = max(money(interest_total) - base_interest, Decimal('0.00'))

                # store formatted values
                prev_interest = loans.at[idx, 'Interest'] if 'Interest' in loans.columns else None
                loans.at[idx, 'Interest Periods'] = periods
                loans.at[idx, 'Interest'] = fmt_money(interest_total)
                loans.at[idx, 'Interest extended'] = fmt_money(interest_extended)
                loans.at[idx, 'Due Amount'] = fmt_money(max(due, Decimal('0.00')))

                # overdue / aging fields
                try:
                    if due_date is not None:
                        bucket = aging_bucket(due_date, asof)
                        loans.at[idx, 'Aging Bucket'] = bucket
                        if bucket != 'Current':
                            loans.at[idx, 'Overdue Since'] = due_date.date().isoformat()
                        else:
                            loans.at[idx, 'Overdue Since'] = None
                    else:
                        loans.at[idx, 'Aging Bucket'] = 'Current'
                        loans.at[idx, 'Overdue Since'] = None
                except Exception:
                    loans.at[idx, 'Aging Bucket'] = 'Current'
                    loans.at[idx, 'Overdue Since'] = None

                # count updates
                if prev_interest != loans.at[idx, 'Interest']:
                    updated += 1
            except Exception:
                logging.exception(f"Failed to recompute loan at index {idx}")

        frames['loans'] = loans
        try:
            self.repo._write(frames)
            overwritten = total
        except Exception:
            logging.exception("Failed to write recomputed loans to workbook")

        return {"total_active": total, "updated_interest_rows": updated, "persisted_rows": overwritten}


# =========================
# FSM Chat
# =========================

class ChatFSM:
    def __init__(self, service: StokvelService):
        self.sessions = {}
        self.service = service

    def handle(self, sender: str, message: str, message_id: str | None = None) -> str:
        if not sender:
            abort(400, description="Missing sender")
        msg = sanitize_soft(message)
        msg_lower = msg.lower()

        # ensure session
        s = self.sessions.get(sender, {"state": STATE["IDLE"]})
        state = s["state"]

        try:
            if msg_lower in ("hi", "hello", "menu"):
                member_name = self.service.verify_member(sender)
                bal = self.service.available_balance()
                self.sessions[sender] = {"state": STATE["MENU"], "member": member_name}
                return (
                    f"👋 Hi {member_name}!\n"
                    f"Bank balance available to lend: R{fmt_money(bal)}\n"
                    "Choose:\n1. Borrow\n2. Pay\n3. Contribute\n4. Cancel Chat"
                )

            if state == STATE["MENU"]:
                if msg_lower == '4':
                    self.sessions[sender] = {"state": STATE["IDLE"]}
                    return "✅ Chat ended. Send 'Hi' to start again."
                elif msg_lower == '3':
                    self.sessions[sender].update({"state": STATE["CONTRIB_AMOUNT"]})
                    return "💰 Enter the contribution amount:"
                elif msg_lower == '2':
                    # list borrowers
                    # ask service for borrowers so FSM doesn't pierce repository internals
                    member_name = s.get('member')
                    borrowers = self.service.list_active_borrowers(member_name)
                    if not borrowers:
                        return "❌ No active borrowers found under your name."
                    listing = "\n".join([f"{i+1}. {b}" for i, b in enumerate(borrowers)])
                    self.sessions[sender].update({"state": STATE["PAY_SELECT_BORROWER"], "borrowers": borrowers})
                    return f"📋 Borrowers under your name:\n{listing}\nReply with a number."
                elif msg_lower == '1':
                    self.sessions[sender].update({"state": STATE["BORROWER_NAME"]})
                    return "👤 Enter the name of the borrower:"
                else:
                    return "❌ Invalid option. Reply with 1, 2, 3, or 4."

            if state == STATE["BORROWER_NAME"]:
                borrower = sanitize_soft(msg)
                self.sessions[sender].update({"borrower": borrower, "state": STATE["BORROW_AMOUNT"]})
                return "💸 Enter the amount to borrow:"

            if state == STATE["BORROW_AMOUNT"]:
                try:
                    # preview and confirm (do not persist yet)
                    member = s.get('member')
                    borrower = s.get('borrower')
                    amount, interest, due, due_date = self.service.borrow_preview(member, borrower, msg)
                    # store preview data in session but don't write to storage yet
                    self.sessions[sender].update({
                        "amount": amount, "interest": interest, "due": due, "due_date": due_date,
                        "state": STATE["CONFIRM_BORROW"]
                    })
                    return (
                        "Please confirm:\n"
                        f"Member: {member}\nBorrower: {borrower}\nAmount: R{fmt_money(amount)}\n"
                        f"Interest (first 30 days): R{fmt_money(interest)}\nDue Amount (initial): R{fmt_money(due)}\n"
                        f"Due Date: {due_date}\nReply 'yes' to confirm or 'no' to cancel."
                    )
                except ValueError as ve:
                    return f"❌ {ve}"
                except PermissionError as pe:
                    return f"❌ {pe}"

            if state == STATE["CONFIRM_BORROW"]:
                if msg_lower == 'yes':
                    # persist loan now
                    member = s.get('member')
                    borrower = s.get('borrower')
                    amount = s.get('amount')
                    try:
                        loan_id = self.service.create_loan(member, borrower, amount, message_id)
                        self.sessions[sender] = {"state": STATE["IDLE"]}
                        return f"✅ Loan recorded. Loan ID: {loan_id}"
                    except Exception as e:
                        logging.exception("Failed to persist loan on confirmation")
                        self.sessions[sender] = {"state": STATE["IDLE"]}
                        return f"❌ Failed to record loan: {e}"
                else:
                    self.sessions[sender] = {"state": STATE["IDLE"]}
                    return "❌ Borrowing cancelled."

            if state == STATE["CONTRIB_AMOUNT"]:
                self.sessions[sender].update({"contrib_amount": msg, "state": STATE["CONTRIB_CHARGE"]})
                return "🏦 Enter the bank charge for this contribution (0 if none):"

            if state == STATE["CONTRIB_CHARGE"]:
                try:
                    member = s.get('member')
                    amount, charge = self.service.contribute(member, s.get('contrib_amount'), msg, note="", message_id=message_id)
                    self.sessions[sender] = {"state": STATE["IDLE"]}
                    return f"✅ Contribution of R{fmt_money(amount)} (bank charge R{fmt_money(charge)}) recorded for {member}."
                except Exception:
                    return "❌ Enter valid amounts (e.g., 150, 0 or R 150.00)."

            if state == STATE["PAY_SELECT_BORROWER"]:
                borrowers = s.get('borrowers', [])
                try:
                    n = int(msg)
                except ValueError:
                    return "❌ Invalid selection. Reply with a number."
                if n < 1 or n > len(borrowers):
                    return "❌ Invalid selection. Reply with a valid number."
                borrower = borrowers[n-1]
                self.sessions[sender].update({"borrower": borrower, "state": STATE["PAY_AMOUNT"]})
                # Show current due
                try:
                    principal, paid, due_now, _ = self.service.current_due(s.get('member'), borrower)
                    return f"💰 {borrower} currently owes R{fmt_money(due_now)}. How much are they paying?"
                except ValueError as e:
                    return f"❌ {str(e)}"

            if state == STATE["PAY_AMOUNT"]:
                try:
                    member = s.get('member')
                    borrower = s.get('borrower')
                    amount, periods = self.service.pay(member, borrower, msg, message_id)
                    self.sessions[sender] = {"state": STATE["PAY_PROOF"], "member": member}
                    return f"✅ Payment of R{fmt_money(amount)} recorded for {periods} periods. Please send proof of payment (screenshot/pdf)."
                except LookupError as le:
                    return f"❌ {le}"
                except Exception:
                    return "❌ Please enter a valid payment amount."

            if state == STATE["PAY_PROOF"]:
                self.sessions[sender] = {"state": STATE["IDLE"]}
                return "📩 Proof received (not stored in this version). Thank you!"

            return "❌ Please start by typing 'Hi'."
        except PermissionError as pe:
            return f"❌ {pe}"
        except Exception:
            logging.exception("Chat handling error")
            return "❌ An internal error occurred. Please try again later."

# =========================
# Flask app
# =========================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration
EXCEL_PATH = os.getenv("STOKVEL_EXCEL_PATH", "stokvel_book.xlsx")
WEBHOOK_SECRET = os.getenv("STOKVEL_WEBHOOK_SECRET")  # for HMAC verification
RECONCILE_TOKEN = os.getenv("RECONCILE_TOKEN")  # for admin endpoints

repo = ExcelRepository(EXCEL_PATH)
service = StokvelService(repo)
fsm = ChatFSM(service)

# Simple in-memory per-sender token-bucket rate limiter for /process endpoint
# Configurable via env vars: RATE_LIMIT_CAPACITY (tokens), RATE_LIMIT_REFILL_PER_SEC
RATE_LIMIT_CAPACITY = int(os.getenv('RATE_LIMIT_CAPACITY', '6'))
RATE_LIMIT_REFILL_PER_SEC = float(os.getenv('RATE_LIMIT_REFILL_PER_SEC', '0.2'))
_rate_lock = threading.Lock()
_rate_buckets: dict = {}

# Optional background thread: daily recompute of loans to refresh interest/aging
def _daily_loan_recompute_loop(svc: StokvelService):
    # disabled if env var set
    if os.getenv('DISABLE_DAILY_LOAN_RECOMPUTE', '0') == '1':
        logging.info('Daily loan recompute disabled via DISABLE_DAILY_LOAN_RECOMPUTE=1')
        return
    logging.info('Starting daily loan recompute thread')
    while True:
        try:
            now = Znow()
            # schedule next run at 03:00 local time next day
            next_run = (now + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
            sleep_seconds = max(0, (next_run - now).total_seconds())
            logging.info(f"Daily loan recompute sleeping for {sleep_seconds} seconds until {next_run}")
            time.sleep(sleep_seconds)
            try:
                stats = svc.recompute_all_loans()
                logging.info(f"Daily loan recompute completed: {stats}")
            except Exception:
                logging.exception('Daily loan recompute failed')
        except Exception:
            logging.exception('Unexpected error in daily loan recompute loop; retrying in 60s')
            time.sleep(60)

# start the background thread as daemon
try:
    t = threading.Thread(target=_daily_loan_recompute_loop, args=(service,), daemon=True)
    t.start()
except Exception:
    logging.exception('Failed to start daily loan recompute thread')

def verify_webhook_signature(request_data: bytes, headers: dict) -> bool:
    """Verify HMAC signature in X-Hub-Signature or X-Hub-Signature-256 header.
    
    Supports both legacy sha1 and modern sha256 signatures. The signature header
    should be in the format "algorithm=signature" where algorithm is sha1 or sha256
    and signature is the hex-encoded HMAC.
    """
    if not WEBHOOK_SECRET:
        return True  # no verification if secret not configured
    
    # Check both modern and legacy signature headers
    signature = headers.get('X-Hub-Signature-256') or headers.get('X-Hub-Signature')
    if not signature:
        return False
        
    try:
        # Extract algo and signature
        algo, sig = signature.split('=', 1)
        if algo not in ('sha1', 'sha256'):
            return False
            
        # Select appropriate hash algorithm
        hash_algo = hashlib.sha256 if algo == 'sha256' else hashlib.sha1
            
        # Compute expected signature
        mac = hmac.new(WEBHOOK_SECRET.encode('utf-8'), 
                      msg=request_data,
                      digestmod=hash_algo)
        expected = mac.hexdigest()
        
        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(sig.lower(), expected.lower())
    except Exception:
        return False

@app.post('/process')
def process_message():
    try:
        # Verify webhook signature when secret is configured
        if not verify_webhook_signature(request.get_data(), dict(request.headers)):
            logging.warning("Invalid webhook signature")
            return jsonify(error="invalid_signature", message="Invalid HMAC signature"), 403

        if not request.is_json:
            logging.warning("Invalid request format: JSON required")
            return jsonify(error="invalid_request_format", message="JSON required"), 400
            
        data = request.get_json()
        msg = data.get('message', '')
        sender = data.get('sender', '')
        # allow bridges to provide an explicit phone/number field; fall back to sender
        bridge_phone = data.get('phone') or data.get('from') or sender
        rate_key = normalize_sender_for_rate(bridge_phone)
        message_id = data.get('message_id')  # optional idempotency key

        # Rate limiting: simple per-sender token bucket
        try:
            now_ts = time.time()
            with _rate_lock:
                bucket = _rate_buckets.get(rate_key)
                if bucket is None:
                    # initialize full bucket
                    bucket = { 'tokens': float(RATE_LIMIT_CAPACITY), 'last': now_ts }
                # refill tokens
                elapsed = now_ts - bucket['last']
                if elapsed > 0:
                    bucket['tokens'] = min(float(RATE_LIMIT_CAPACITY), bucket['tokens'] + elapsed * RATE_LIMIT_REFILL_PER_SEC)
                    bucket['last'] = now_ts
                if bucket['tokens'] < 1.0:
                    # too many requests
                    return jsonify(reply="❌ Rate limit exceeded. Try again later."), 429
                # consume one token
                bucket['tokens'] -= 1.0
                _rate_buckets[rate_key] = bucket
        except Exception:
            logging.exception('Rate limiter failure; allowing request')

        reply = fsm.handle(sender, msg, message_id)
        return jsonify(reply=reply)
    except ValueError as e:
        # Surface parse/validation errors nicely
        return jsonify(reply=f"❌ {str(e)}"), 400
    except Exception as e:
        logging.exception("Error processing message")
        return jsonify(reply="❌ Internal error"), 500

@app.get('/health')
def health():
    try:
        bal = service.available_balance()
        return {"status": "ok", "balance": fmt_money(bal)}, 200
    except Exception as e:
        return {"status": "error", "error": str(e)}, 500

@app.get('/reports/aging')
def aging_report():
    """Generate aging analysis of outstanding loans."""
    if RECONCILE_TOKEN and request.headers.get('X-Admin-Token') != RECONCILE_TOKEN:
        abort(403)
        
    frames = repo._read()
    loans = frames['loans']
    active = loans[loans['Status'] == 'Active']
    
    now = Znow()
    aging = {
        'Current': Decimal('0.00'),
        '1-30': Decimal('0.00'),
        '31-60': Decimal('0.00'),
        '61-90': Decimal('0.00'),
        '90+': Decimal('0.00'),
    }
    
    # Helper to recompute loan state
    def compute_loan_state(loan) -> tuple[Decimal, str, bool]:
        """Returns (due_amount, aging_bucket, is_overdue)."""
        borrowed_at = parse_stored_datetime(loan['Date borrowed'])
        if borrowed_at is None:
            logging.warning(f"Invalid borrow date for loan {loan.get('Loan ID', 'unknown')}")
            return Decimal('0.00'), 'Current', False
            
        # Recompute current due amount
        principal = money(loan['Amount borrowed'])
        paid = money(loan['Paid'] or 0)
        _, interest_total, due = compute_due(principal, INTEREST_RATE, borrowed_at, paid, now)
        
        # Get correct aging bucket based on due date
        due_date = parse_stored_datetime(loan['Due Date'])
        if due_date is None:
            logging.warning(f"Invalid due date for loan {loan.get('Loan ID', 'unknown')}")
            return due, 'Current', False
            
        current_bucket = aging_bucket(due_date, now)
        is_overdue = current_bucket != 'Current'
        
        return due, current_bucket, is_overdue
    
    # Track statistics
    total_loans = 0
    overdue_loans = 0
    needs_update = 0
    
    for _, loan in active.iterrows():
        due, current_bucket, is_overdue = compute_loan_state(loan)
        if due > 0:
            aging[current_bucket] += due
            total_loans += 1
            if is_overdue:
                overdue_loans += 1
            
            # Check if stored state is stale
            stored_bucket = loan['Aging Bucket']
            if stored_bucket != current_bucket:
                needs_update += 1
                
    total = money(sum(aging.values()))
    return jsonify(
        total_outstanding=fmt_money(total),
        aging={k: fmt_money(v) for k, v in aging.items()},
        stats={
            "total_loans": total_loans,
            "overdue_loans": overdue_loans,
            "overdue_rate": f"{(overdue_loans / total_loans * 100):.1f}%" if total_loans > 0 else "0%",
            "needs_aging_update": needs_update,
        },
        generated_at=store_local(now)
    )

@app.get('/reports/balances')
def balance_report():
    """Get current bank balance and member contribution totals."""
    if RECONCILE_TOKEN and request.headers.get('X-Admin-Token') != RECONCILE_TOKEN:
        abort(403)
        
    frames = repo._read()
    bank = frames['bank']
    contrib = frames['contrib']
    
    # Get member contribution totals
    member_totals = {}
    for _, row in contrib.iterrows():
        name = row['Member Name']
        net = money(row['Net'])
        member_totals[name] = member_totals.get(name, Decimal('0.00')) + net
        
    return jsonify(
        bank_balance=fmt_money(repo.latest_balance()),
        member_contributions={k: fmt_money(v) for k, v in member_totals.items()}
    )

@app.get('/export/xlsx')
def export_workbook():
    """Export a timestamped copy of the Excel workbook."""
    if RECONCILE_TOKEN and request.headers.get('X-Admin-Token') != RECONCILE_TOKEN:
        abort(403)
        
    try:
        # Create a timestamped backup
        ts = Znow().strftime("%Y%m%d-%H%M%S")
        base = os.path.basename(EXCEL_PATH)
        name, ext = os.path.splitext(base)
        export_path = os.path.join(BACKUP_DIR, f"{name}-{ts}{ext}")
        
        # Read current data and recompute balances
        frames = repo._read()
        repo._recompute_bank_balances(frames)
        
        # Write to new file with pandas
        with pd.ExcelWriter(export_path) as writer:
            for sheet, frame in frames.items():
                frame.to_excel(writer, sheet_name=SHEETS[sheet], index=False)
                
        # Send file
        return send_file(
            export_path,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f"stokvel-export-{ts}.xlsx"
        )
    except Exception as e:
        logging.exception("Export failed")
        return jsonify(status="error", error=str(e)), 500


@app.post('/admin/reconcile')
def reconcile_balances():
    """Recompute Bank Balances from transactions and overwrite the Balance column.

    Protect with optional RECONCILE_TOKEN env var. Token may be provided either as
    query param `?token=...` or header `X-Admin-Token`.
    """
    # simple auth with optional token
    token = request.args.get('token') or request.headers.get('X-Admin-Token')
    if RECONCILE_TOKEN and token != RECONCILE_TOKEN:
        abort(403, description="Forbidden")

    try:
        # Read current frames, validate and recompute balances
        frames = repo._read()

        bank = frames.get('bank')
        if bank is None or bank.empty:
            return jsonify(status='ok', rows=0, corrected=0), 200

        # capture stored balances for diffing
        stored = bank['Balance'].fillna('').astype(str).tolist()

        # recompute (mutates frames['bank'])
        repo._recompute_bank_balances(frames)

        recomputed = frames['bank']['Balance'].fillna('').astype(str).tolist()
        corrected = sum(1 for a, b in zip(stored, recomputed) if a != b)

        # persist the corrected workbook
        repo._write(frames)

        return jsonify(status='ok', rows=len(recomputed), corrected=corrected), 200
    except Exception as e:
        logging.exception('Reconciliation failed')
        return jsonify(status='error', error=str(e)), 500


@app.post('/admin/recompute-loans')
def admin_recompute_loans():
    """Admin endpoint to force recompute of all loans (interest, due amounts, aging).

    Protected by optional RECONCILE_TOKEN in header or ?token= query param.
    """
    token = request.args.get('token') or request.headers.get('X-Admin-Token')
    if RECONCILE_TOKEN and token != RECONCILE_TOKEN:
        abort(403, description="Forbidden")
    try:
        stats = service.recompute_all_loans()
        return jsonify(status='ok', stats=stats), 200
    except Exception as e:
        logging.exception('Recompute loans failed')
        return jsonify(status='error', error=str(e)), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host='0.0.0.0', port=port, debug=debug)
