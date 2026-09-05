"""Closed vocabularies the planner may emit; anything else fails validation."""
from enum import Enum


class Intent(str, Enum):
    """Supported question shapes over bank / account / transaction."""

    SPEND_SUMMARY = "spend_summary"
    COUNTERPARTY_SPEND = "counterparty_spend"
    ACCOUNT_SUMMARY = "account_summary"
    TRANSACTION_LOOKUP = "transaction_lookup"
    REFERENCE_LOOKUP = "reference_lookup"
    LARGEST_TRANSACTIONS = "largest_transactions"
    TOP_COUNTERPARTIES = "top_counterparties"
    CHANNEL_BREAKDOWN = "channel_breakdown"
    BALANCE = "balance"
    ACCOUNT_LIST = "account_list"
    PERIOD_COMPARISON = "period_comparison"
    TREND = "trend"
    ANOMALY_SCAN = "anomaly_scan"


class Metric(str, Enum):
    SUM = "sum"
    COUNT = "count"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"


class GroupBy(str, Enum):
    NONE = "none"
    COUNTERPARTY = "counterparty"
    ACCOUNT = "account"
    BANK = "bank"
    CHANNEL = "channel"
    TRANSACTION_TYPE = "transaction_type"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class DateGrain(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class TransactionType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class Channel(str, Enum):
    NEFT = "NEFT"
    IMPS = "IMPS"
    UPI = "UPI"
    FT = "FT"
    RTGS = "RTGS"
    CHEQUE = "CHEQUE"
    CHARGES = "CHARGES"
    INTEREST = "INTEREST"
    OTHER = "OTHER"


class ReferenceKind(str, Enum):
    """Which reference column a lookup hits. A bare "reference number" means the
    plaintext reference id; UTR only when the user says UTR."""

    REFERENCE = "reference"
    UTR = "utr"


class ResponseState(str, Enum):
    """Every turn ends in exactly one of these."""

    ANSWER = "answer"
    CLARIFICATION_REQUIRED = "clarification_required"
    DATA_UNAVAILABLE = "data_unavailable"
    OUT_OF_SCOPE = "out_of_scope"
    ERROR = "error"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
