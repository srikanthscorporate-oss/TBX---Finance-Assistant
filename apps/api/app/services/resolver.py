"""Deterministic counterparty and account resolution by normalisation and string
similarity in Python; ambiguity becomes CLARIFICATION_REQUIRED."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum


class MatchKind(str, Enum):
    EXACT = "exact"
    UNIQUE_FUZZY = "unique_fuzzy"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


MIN_ACCEPT = 0.72
"""A candidate must clear this to be usable at all."""
AMBIGUITY_MARGIN = 0.08
"""A runner-up this close to the leader makes the match ambiguous."""


@dataclass(frozen=True)
class CounterpartyRecord:
    """One distinct stored counterparty. `entities` lists who has transacted with it."""
    name: str
    txn_count: int = 0
    channel: str = ""
    entities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AccountRecord:
    account_id: str
    entity_id: str
    last4: str
    bank_code: str
    bank_name: str = ""
    program_id: int = 0
    available_balance: float = 0.0

    @property
    def masked(self) -> str:
        return f"XXXXXX{self.last4}"


@dataclass
class Candidate:
    record: CounterpartyRecord
    score: float


@dataclass
class Resolution:
    kind: MatchKind
    query: str
    candidates: list[Candidate]

    @property
    def best(self) -> CounterpartyRecord | None:
        return self.candidates[0].record if self.candidates else None

    @property
    def score(self) -> float:
        return self.candidates[0].score if self.candidates else 0.0

    @property
    def is_usable(self) -> bool:
        return self.kind in {MatchKind.EXACT, MatchKind.UNIQUE_FUZZY}


def normalize(s: str) -> str:
    """Casefold, strip accents, drop corporate suffixes and punctuation.

    'Acme Technologies Pvt. Ltd.' and 'acme technologies' must collide, or every
    lookup against legal names fails.
    """
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    for token in (" private limited", " pvt ltd", " pvt. ltd.", " pvt limited",
                  " limited", " ltd", " llp", " inc", " corp", " corporation",
                  " co", " gmbh", " bv", " sa", " plc", " llc"):
        if s.endswith(token):
            s = s[: -len(token)]
    return " ".join(ch for ch in "".join(
        c if c.isalnum() or c.isspace() else " " for c in s
    ).split())


def _token_score(q_token: str, t_token: str) -> float:
    """How well one query token matches one target token; a 3+ char prefix scores 0.95."""
    if q_token == t_token:
        return 1.0
    if t_token.startswith(q_token) and len(q_token) >= 3:
        return 0.95
    return SequenceMatcher(None, q_token, t_token).ratio()


def _alignment(query: str, target: str) -> float:
    """Mean best-match score of each query token against the target's tokens.

    Lets "acme tech" find Acme Technologies while scoring "acme" identically
    against both Acme vendors, so the ambiguity check applies.
    """
    q_tokens, t_tokens = query.split(), target.split()
    if not q_tokens or not t_tokens:
        return 0.0
    return sum(max(_token_score(q, t) for t in t_tokens) for q in q_tokens) / len(q_tokens)


def _similarity(query: str, target: str) -> float:
    """A full prefix match scores 0.9: a candidate, but not a winner over a sibling
    sharing the prefix."""
    if query == target:
        return 1.0
    ratio = SequenceMatcher(None, query, target).ratio()
    q_tokens, t_tokens = set(query.split()), set(target.split())
    overlap = (len(q_tokens & t_tokens) / len(q_tokens)) * 0.85 if q_tokens else 0.0
    prefix = 0.9 if target.startswith(query + " ") else 0.0
    return max(ratio, overlap, prefix, _alignment(query, target))


def resolve_counterparty(query: str, counterparties: list[CounterpartyRecord]) -> Resolution:
    """A single exact normalised hit wins; several close fuzzy hits are ambiguous.

    "Swiggy" against SWIGGY and SWIGGY INSTAMART is the canonical ambiguous case and
    yields both as options rather than a guess.
    """
    q = normalize(query)
    if not q:
        return Resolution(MatchKind.NOT_FOUND, query, [])

    scored: list[Candidate] = []
    for v in counterparties:
        score = _similarity(q, normalize(v.name))
        if score >= MIN_ACCEPT:
            scored.append(Candidate(record=v, score=round(score, 4)))

    scored.sort(key=lambda c: (-c.score, -c.record.txn_count, c.record.name))

    if not scored:
        return Resolution(MatchKind.NOT_FOUND, query, [])

    exact = [c for c in scored if normalize(c.record.name) == q]
    prefixed = [c for c in scored if normalize(c.record.name).startswith(q + " ")]
    if len(exact) == 1 and prefixed:
        return Resolution(MatchKind.AMBIGUOUS, query, exact + prefixed[:7])
    if len(exact) == 1:
        return Resolution(MatchKind.EXACT, query, exact)
    if len(exact) > 1:
        return Resolution(MatchKind.AMBIGUOUS, query, exact)

    if len(scored) == 1:
        return Resolution(MatchKind.UNIQUE_FUZZY, query, scored)

    if scored[0].score - scored[1].score < AMBIGUITY_MARGIN:
        close = [c for c in scored if scored[0].score - c.score < AMBIGUITY_MARGIN]
        return Resolution(MatchKind.AMBIGUOUS, query, close[:8])

    return Resolution(MatchKind.UNIQUE_FUZZY, query, scored[:1])


@dataclass
class AccountResolution:
    kind: MatchKind
    matches: list[AccountRecord]


def resolve_account(last4: str, accounts: list[AccountRecord]) -> AccountResolution:
    """Accounts are named by their last four digits; two accounts sharing them is
    ambiguous and asks, showing the bank as the hint."""
    hits = [a for a in accounts if a.last4 == last4]
    if not hits:
        return AccountResolution(MatchKind.NOT_FOUND, [])
    if len(hits) == 1:
        return AccountResolution(MatchKind.EXACT, hits)
    return AccountResolution(MatchKind.AMBIGUOUS, hits)
