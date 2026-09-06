#!/usr/bin/env python3
"""Sensitive fields are stored encrypted in ClickHouse and decrypt back to the CSV plaintext.

Samples accounts and UTR-bearing transactions from data/raw, reads the stored rows as the
admin user, and checks the ciphertext differs from the plaintext, decrypts to it, and that
no plaintext column exists. A positive control proves the "differs from plaintext"
comparison can fail. Needs CH_PORT and TBX_DATA_KEY (read from .env when unset).
Prints ENCRYPTION_AT_REST_PASS.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bank_fixture import ch_client, data_key, read_csv  # noqa: E402

from app.services.crypto import FieldCipher, load_key  # noqa: E402

SAMPLE = 20
failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(f"{name}: {detail}")


def encrypted_like(stored: str, plaintext: str) -> bool:
    """The detector for at-rest encryption: stored differs from and does not contain the plaintext."""
    return bool(stored) and stored != plaintext and plaintext not in stored


def main() -> int:
    ch = ch_client(timeout=60)
    assert ch.ping(), "ClickHouse is not reachable"
    cipher = FieldCipher(load_key(data_key()))
    rng = random.Random(20260905)

    accounts = read_csv("account.csv")
    for a in rng.sample(accounts, min(SAMPLE, len(accounts))):
        rows = ch.query("SELECT account_number_enc, account_last4 FROM tbx_finance.account FINAL "
                        "WHERE account_id = {id:String}", {"id": a["account_id"]}).rows
        tag = a["account_id"][:8]
        if len(rows) != 1:
            check(f"account {tag} stored once", False, f"{len(rows)} rows")
            continue
        enc, last4 = rows[0]["account_number_enc"], rows[0]["account_last4"]
        plain = a["account_number"]
        check(f"account {tag}: stored value is not the plaintext", encrypted_like(enc, plain), enc[:12])
        try:
            check(f"account {tag}: decrypts to the CSV number", cipher.decrypt(enc) == plain)
        except ValueError as e:
            check(f"account {tag}: decrypts to the CSV number", False, str(e))
        check(f"account {tag}: last4 correct", last4 == plain[-4:], f"{last4} vs {plain[-4:]}")
        check(f"account {tag}: last4 is only four digits", len(last4) == 4 and last4.isdigit())

    txns = [t for t in read_csv("transaction.csv") if t["utr_number"]]
    for t in rng.sample(txns, min(SAMPLE, len(txns))):
        rows = ch.query("SELECT utr_enc, utr_hash FROM tbx_finance.transaction "
                        "WHERE transaction_id = {id:String}", {"id": t["transaction_id"]}).rows
        tag = t["transaction_id"][:8]
        if len(rows) != 1:
            check(f"transaction {tag} stored once", False, f"{len(rows)} rows")
            continue
        enc, h = rows[0]["utr_enc"], rows[0]["utr_hash"]
        plain = t["utr_number"]
        check(f"transaction {tag}: stored utr is not the plaintext", encrypted_like(enc, plain), enc[:12])
        try:
            check(f"transaction {tag}: utr decrypts to the CSV value", cipher.decrypt(enc) == plain)
        except ValueError as e:
            check(f"transaction {tag}: utr decrypts to the CSV value", False, str(e))
        check(f"transaction {tag}: utr_hash is the blind index", h == cipher.blind_index(plain))
        check(f"transaction {tag}: utr_hash is not the plaintext", encrypted_like(h, plain))

    empties = ch.query("SELECT countIf(utr_enc != '') AS enc, countIf(utr_hash != '') AS hashed "
                       "FROM tbx_finance.transaction").rows[0]
    check("utr_enc populated for exactly the CSV rows with a utr", int(empties["enc"]) == len(txns),
          f"{empties['enc']} vs {len(txns)}")
    check("utr_hash populated for exactly the CSV rows with a utr", int(empties["hashed"]) == len(txns))

    cols = ch.query("SELECT table, name FROM system.columns WHERE database = 'tbx_finance' "
                    "AND table IN ('account', 'transaction')").rows
    names = {(c["table"], c["name"]) for c in cols}
    check("no plaintext account_number column", ("account", "account_number") not in names
          and ("transaction", "account_number") not in names)
    check("no plaintext utr_number column", ("transaction", "utr_number") not in names
          and ("account", "utr_number") not in names)
    check("encrypted columns present", {("account", "account_number_enc"), ("account", "account_last4"),
                                        ("transaction", "utr_enc"), ("transaction", "utr_hash")} <= names)
    check("transaction never carries an account number column",
          not any(t == "transaction" and "account_number" in n for t, n in names))

    orphans = ch.query("SELECT count() AS n FROM tbx_finance.transaction AS t "
                       "LEFT ANTI JOIN (SELECT account_id FROM tbx_finance.account FINAL) AS a "
                       "USING account_id").rows[0]
    check("referential integrity: every transaction.account_id exists in account",
          int(orphans["n"]) == 0, f"{orphans['n']} orphans")
    mismatched = ch.query(
        "SELECT count() AS n FROM tbx_finance.transaction AS t "
        "INNER JOIN (SELECT account_id, entity_id, bank_code FROM tbx_finance.account FINAL) AS a "
        "USING account_id WHERE t.entity_id != a.entity_id OR t.bank_code != a.bank_code").rows[0]
    check("denormalised entity_id/bank_code agree with account", int(mismatched["n"]) == 0,
          f"{mismatched['n']} rows disagree")
    bank_orphans = ch.query("SELECT count() AS n FROM tbx_finance.account AS a "
                            "LEFT ANTI JOIN tbx_finance.bank AS b USING bank_code").rows[0]
    check("every account.bank_code exists in bank", int(bank_orphans["n"]) == 0)

    plain = accounts[0]["account_number"]
    check("positive control: an unencrypted value is detected", not encrypted_like(plain, plain),
          "the detector accepted plaintext as encrypted; the suite cannot fail")
    check("positive control: a value embedding the plaintext is detected",
          not encrypted_like(f"enc:{plain}", plain))

    print(f"encryption checks run: {checks}")
    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ENCRYPTION_AT_REST_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
