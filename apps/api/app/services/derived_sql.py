"""Columns the canonical schema has but the live MySQL source does not.

The remote `transaction` table carries only the raw narration. `counterparty` and
`channel` are derived from it here, in SQL, so that every reader -- the compiler,
the dataset context, the anomaly agent -- uses one definition and a grouped answer
can never disagree with the list the resolver matched against.

The rules mirror `services/narration.py` for the rails present in the source:

    UPI-<NAME>-<ref>-<IFSC>-...            second '-' field
    NEFT - <IFSC> - <acct> - <ref> - NAME  last ' - ' field
    FT-<acct>-<acct>-<NAME>                last '-' field
    RTGS-<ref>-<BANK>/<NAME>               after the last '/'
    IMPS-<ref>-<BANK>/<NAME>               after the last '/'
    IMPS/CR/<ref>/<NAME>/<BANK>/<acct>     fourth '/' field
    A2AINT|N|SWIFT/<ref>/<BANK>/<NAME>     last '/' field
    CASHWITHDRAWAL|CASHDEPOSIT/<ref>       fixed label

These strings are SQL fragments interpolated by the compiler; they contain no
user-supplied value. `%%` is a literal percent because the driver formats `%(name)s`
placeholders. `{t}` is the transaction table alias.
"""
from __future__ import annotations

COUNTERPARTY_EXPR = (
    "UPPER(TRIM(CASE"
    " WHEN {t}.description LIKE 'UPI%%' THEN"
    "   SUBSTRING_INDEX(SUBSTRING_INDEX({t}.description, '-', 2), '-', -1)"
    " WHEN {t}.description LIKE 'NEFT%%' THEN SUBSTRING_INDEX({t}.description, ' - ', -1)"
    " WHEN {t}.description LIKE 'FT-%%' THEN SUBSTRING_INDEX({t}.description, '-', -1)"
    " WHEN {t}.description LIKE 'RTGS%%' OR {t}.description LIKE 'IMPS-%%' THEN"
    "   SUBSTRING_INDEX({t}.description, '/', -1)"
    " WHEN {t}.description LIKE 'IMPS/%%' THEN"
    "   SUBSTRING_INDEX(SUBSTRING_INDEX({t}.description, '/', 4), '/', -1)"
    " WHEN {t}.description LIKE 'CASHWITHDRAWAL%%' THEN 'CASH WITHDRAWAL'"
    " WHEN {t}.description LIKE 'CASHDEPOSIT%%' THEN 'CASH DEPOSIT'"
    " WHEN {t}.description LIKE 'A2AINT/%%' OR {t}.description LIKE 'N/%%'"
    "   OR {t}.description LIKE 'SWIFT/%%' THEN SUBSTRING_INDEX({t}.description, '/', -1)"
    " WHEN {t}.description LIKE '%%CHEQUE%%' OR {t}.description LIKE '%%CHQ%%' THEN 'CHEQUE DEPOSIT'"
    " WHEN {t}.description LIKE '%%INTEREST%%' THEN 'INTEREST'"
    " ELSE {t}.description END))"
)

CHANNEL_EXPR = (
    "CASE"
    " WHEN {t}.description LIKE 'UPI%%' THEN 'UPI'"
    " WHEN {t}.description LIKE 'NEFT%%' THEN 'NEFT'"
    " WHEN {t}.description LIKE 'RTGS%%' THEN 'RTGS'"
    " WHEN {t}.description LIKE 'IMPS%%' THEN 'IMPS'"
    " WHEN {t}.description LIKE 'FT-%%' THEN 'FT'"
    " WHEN {t}.description LIKE '%%CHARGE%%' OR {t}.description LIKE '%% FEE%%'"
    "   OR {t}.description LIKE 'GST%%' THEN 'CHARGES'"
    " WHEN {t}.description LIKE '%%CHEQUE%%' OR {t}.description LIKE '%%CHQ%%' THEN 'CHEQUE'"
    " WHEN {t}.description LIKE '%%INTEREST%%' THEN 'INTEREST'"
    " ELSE 'OTHER' END"
)

TXN_DATE_EXPR = "DATE({t}.transaction_date)"
"""Calendar day of a transaction; the source stores a timestamp."""

ACCOUNT_LAST4_EXPR = "RIGHT({a}.account_id, 4)"
"""The four-character handle an account is referred to by ("the account ending 7c23").

The source stores `account_number` as ciphertext under a key this service does not
hold, so no digit of the real number is derivable here -- which also means none
can leak. The handle is the tail of the stable `account_id` instead; the
`account_number` column is never selected."""


def counterparty(alias: str = "t") -> str:
    return COUNTERPARTY_EXPR.format(t=alias)


def channel(alias: str = "t") -> str:
    return CHANNEL_EXPR.format(t=alias)


def txn_date(alias: str = "t") -> str:
    return TXN_DATE_EXPR.format(t=alias)


def account_last4(alias: str = "a") -> str:
    return ACCOUNT_LAST4_EXPR.format(a=alias)
