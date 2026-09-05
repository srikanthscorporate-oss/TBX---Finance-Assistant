"""Closed vocabularies the planner may emit; anything else fails validation."""
from enum import Enum


class Intent(str, Enum):
    """Supported question shapes."""

    TOTAL_SPEND = "total_spend"
    VENDOR_SPEND = "vendor_spend"
    CATEGORY_SPEND = "category_spend"
    ACCOUNT_SPEND = "account_spend"
    VENDOR_PAYOUTS = "vendor_payouts"
    PAYOUT_STATUS = "payout_status"
    TRANSACTION_LOOKUP = "transaction_lookup"
    UNRECONCILED = "unreconciled"
    RECONCILIATION_RATE = "reconciliation_rate"
    RECONCILIATION_SUMMARY = "reconciliation_summary"
    PERIOD_COMPARISON = "period_comparison"
    TOP_VENDORS = "top_vendors"
    TREND = "trend"
    ANOMALY_SCAN = "anomaly_scan"
    VENDOR_LOOKUP = "vendor_lookup"


class Metric(str, Enum):
    SUM = "sum"
    COUNT = "count"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"


class GroupBy(str, Enum):
    NONE = "none"
    VENDOR = "vendor"
    CATEGORY = "category"
    ACCOUNT = "account"
    STATUS = "status"
    RECON_STATUS = "recon_status"
    PAYMENT_METHOD = "payment_method"
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


class TxnStatus(str, Enum):
    POSTED = "posted"
    PENDING = "pending"
    FAILED = "failed"
    REVERSED = "reversed"


class ReconStatus(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    PENDING = "pending"
    DISPUTED = "disputed"


class Direction(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


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
