"""Map an arbitrary MySQL schema onto the canonical bank/account/transaction model.

The assistant's whole grounding chain -- planner enums, compiler allowlist,
verification, evidence -- is written against the canonical schema in
`infra/clickhouse/001_schema.sql`. So a user-supplied MySQL database is not
queried directly; it is mapped onto that schema and ingested. This module owns
the mapping, and it is deterministic: a synonym table plus name normalisation,
no model call and no guessing beyond what is written here.

What cannot be mapped is reported, not invented. `transaction` and `account`
must both resolve or initialisation refuses -- an account table is where
balances come from, and a fabricated balance is exactly the failure this
product exists to prevent. `bank` is optional; its absence costs display names
only, never a figure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .mysql_source import SourceTable

CANONICAL_TABLES = ("bank", "account", "transaction")

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "bank": ["bank_code", "bank_name"],
    "account": ["account_id", "available_balance"],
    "transaction": ["transaction_id", "account_id", "transaction_date", "transaction_amount"],
}
"""Without these a canonical table cannot be built at all."""

OPTIONAL_COLUMNS: dict[str, list[str]] = {
    "bank": [],
    "account": ["entity_id", "account_number", "program_id", "bank_code"],
    "transaction": ["transaction_type", "description", "transaction_reference_id",
                    "utr_number", "counterparty"],
}
"""Absent optional columns get the documented defaults in DEFAULTS below."""

REQUIRED_TABLES = ("account", "transaction")

DEFAULTS: dict[str, str] = {
    "entity_id": "ENT-001",
    "program_id": "0",
    "bank_code": "SRC",
    "account_number": "",
    "description": "",
    "transaction_reference_id": "",
    "utr_number": "",
    "counterparty": "",
    "transaction_type": "",
}
"""Defaults for absent OPTIONAL columns only. Every one of these is a label or an
identifier -- never an amount, a balance, a date or a count."""

SYNONYMS: dict[str, tuple[str, ...]] = {
    "bank_code": ("bankcode", "bankid", "bank", "ifsc", "bankshortcode", "bankcd"),
    "bank_name": ("bankname", "name", "bankdescription", "banktitle", "institution"),
    "account_id": ("accountid", "acctid", "account", "accountnumberid", "accno", "acctno",
                   "accountno", "accountnum", "acctnum", "accountkey"),
    "entity_id": ("entityid", "customerid", "custid", "clientid", "userid", "ownerid",
                  "orgid", "companyid", "tenantid", "entity", "customer"),
    "account_number": ("accountnumber", "acctnumber", "accountnumberfull", "iban",
                       "accountnumbermasked", "acnumber"),
    "program_id": ("programid", "program", "producttype", "producttypeid", "schemecode",
                   "productid", "accounttypeid"),
    "available_balance": ("availablebalance", "balance", "currentbalance", "closingbalance",
                          "availbal", "ledgerbalance", "accountbalance", "bal"),
    "transaction_id": ("transactionid", "txnid", "trnid", "id", "transactionref",
                       "transactionkey", "txnkey", "trxid", "entryid"),
    "transaction_date": ("transactiondate", "txndate", "date", "valuedate", "postingdate",
                         "bookingdate", "createdat", "transactiontime", "trndate", "timestamp"),
    "transaction_type": ("transactiontype", "txntype", "type", "drcr", "debitcredit",
                         "crdr", "direction", "trntype", "indicator"),
    "description": ("description", "narration", "particulars", "remarks", "details",
                    "memo", "narrative", "transactiondescription", "note"),
    "transaction_amount": ("transactionamount", "amount", "txnamount", "amt", "value",
                           "transactionvalue", "trnamount", "debitamount"),
    "transaction_reference_id": ("transactionreferenceid", "referenceid", "reference",
                                 "refno", "referenceno", "chequeno", "instrumentid",
                                 "externalref", "refid"),
    "utr_number": ("utrnumber", "utr", "utrno", "rrn", "networkreference", "upitxnid",
                   "bankreference", "utrref"),
    "counterparty": ("counterparty", "payee", "merchant", "beneficiary", "vendor",
                     "payeename", "merchantname", "beneficiaryname", "counterpartyname"),
}
"""Normalised synonyms, best match first. The canonical name itself always wins."""

TABLE_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "bank": ("bank", "banks", "institution", "bankmaster"),
    "account": ("account", "accounts", "accountmaster", "customeraccount", "acct"),
    "transaction": ("transaction", "transactions", "txn", "txns", "ledger", "entries",
                    "statement", "banktransaction", "accountstatement"),
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass
class TableMapping:
    """One canonical table and where each of its columns comes from."""

    canonical: str
    source_table: str | None
    columns: dict[str, str] = field(default_factory=dict)
    """canonical column -> source column."""
    defaulted: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    rows: int = 0
    derive_type_from_sign: bool = False
    """True when the source has no debit/credit column: direction is then taken
    from the sign of the amount, which is arithmetic, not a guess."""

    @property
    def usable(self) -> bool:
        return self.source_table is not None and not self.missing_required

    def public(self) -> dict[str, Any]:
        return {
            "canonical": self.canonical, "source_table": self.source_table,
            "rows": self.rows, "columns": dict(self.columns),
            "defaulted": list(self.defaulted),
            "missing_required": list(self.missing_required),
            "usable": self.usable,
            "derive_type_from_sign": self.derive_type_from_sign,
        }


@dataclass
class SourceMapping:
    tables: dict[str, TableMapping]
    unmapped_tables: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """Initialisation is allowed only when both required tables resolve."""
        return all(self.tables[t].usable for t in REQUIRED_TABLES)

    def problems(self) -> list[str]:
        out: list[str] = []
        for name in REQUIRED_TABLES:
            m = self.tables[name]
            if m.source_table is None:
                out.append(
                    f"No table in this database looks like `{name}` "
                    f"(needs {', '.join(REQUIRED_COLUMNS[name])}).")
            elif m.missing_required:
                out.append(
                    f"`{m.source_table}` was matched to `{name}` but has no column for "
                    f"{', '.join(m.missing_required)}.")
        return out

    def public(self) -> dict[str, Any]:
        return {"tables": [self.tables[t].public() for t in CANONICAL_TABLES],
                "unmapped_tables": list(self.unmapped_tables),
                "ready": self.ready, "problems": self.problems()}


def _match_column(canonical: str, available: dict[str, str]) -> str | None:
    """`available` is normalised source column -> real source column."""
    for candidate in (canonical, *SYNONYMS.get(canonical, ())):
        hit = available.get(_norm(candidate))
        if hit:
            return hit
    return None


def _score(canonical: str, table: SourceTable) -> float:
    available = {_norm(c.name): c.name for c in table.columns}
    required = REQUIRED_COLUMNS[canonical]
    hits = sum(1 for c in required if _match_column(c, available))
    if not hits:
        return 0.0
    score = hits / len(required)
    optional = OPTIONAL_COLUMNS[canonical]
    if optional:
        score += 0.25 * sum(1 for c in optional if _match_column(c, available)) / len(optional)
    if _norm(table.name) in {_norm(h) for h in TABLE_NAME_HINTS[canonical]}:
        score += 0.5
    elif any(h in _norm(table.name) for h in TABLE_NAME_HINTS[canonical]):
        score += 0.2
    return score


def build_mapping(tables: list[SourceTable]) -> SourceMapping:
    """Assign at most one source table to each canonical table, best score first.

    A source table is claimed by one canonical role only, so an `account` table
    cannot also be read as `transaction`.
    """
    candidates = [(_score(canon, t), canon, t)
                  for canon in CANONICAL_TABLES for t in tables]
    candidates = [c for c in candidates if c[0] > 0]
    candidates.sort(key=lambda c: (-c[0], c[1], c[2].name))

    chosen: dict[str, SourceTable] = {}
    claimed: set[str] = set()
    for score, canon, candidate in candidates:
        if canon in chosen or candidate.name in claimed:
            continue
        # A role needs at least its required columns half-covered to be plausible.
        if score < 0.5:
            continue
        chosen[canon] = candidate
        claimed.add(candidate.name)

    mappings: dict[str, TableMapping] = {}
    for canon in CANONICAL_TABLES:
        table: SourceTable | None = chosen.get(canon)
        if table is None:
            mappings[canon] = TableMapping(canonical=canon, source_table=None,
                                           missing_required=list(REQUIRED_COLUMNS[canon]))
            continue
        available = {_norm(c.name): c.name for c in table.columns}
        cols: dict[str, str] = {}
        missing: list[str] = []
        for c in REQUIRED_COLUMNS[canon]:
            hit = _match_column(c, available)
            if hit:
                cols[c] = hit
            else:
                missing.append(c)
        defaulted: list[str] = []
        for c in OPTIONAL_COLUMNS[canon]:
            hit = _match_column(c, available)
            if hit:
                cols[c] = hit
            else:
                defaulted.append(c)
        mappings[canon] = TableMapping(
            canonical=canon, source_table=table.name, columns=cols, defaulted=defaulted,
            missing_required=missing, rows=table.rows,
            derive_type_from_sign=(canon == "transaction" and "transaction_type" not in cols),
        )

    return SourceMapping(tables=mappings,
                         unmapped_tables=sorted(t.name for t in tables
                                                if t.name not in claimed))
