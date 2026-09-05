CREATE DATABASE IF NOT EXISTS tbx_finance;

CREATE TABLE IF NOT EXISTS tbx_finance.accounts
(
    account_code   String,
    account_name   String,
    account_type   LowCardinality(String),   -- asset/liability/equity/revenue/expense
    parent_code    String,
    is_active      UInt8 DEFAULT 1
)
ENGINE = MergeTree
ORDER BY account_code;

CREATE TABLE IF NOT EXISTS tbx_finance.vendors
(
    vendor_id      String,
    vendor_name    String,
    legal_name     String,
    category       LowCardinality(String),
    status         LowCardinality(String),   -- active/inactive/on_hold
    country        LowCardinality(String),
    currency       LowCardinality(String),
    onboarded_at   Date
)
ENGINE = MergeTree
ORDER BY vendor_id;

CREATE TABLE IF NOT EXISTS tbx_finance.transactions
(
    transaction_id      String,
    txn_date            Date,
    posted_at           DateTime,
    vendor_id           String,
    account_code        String,
    category            LowCardinality(String),
    description         String,
    amount              Decimal64(2),
    currency            LowCardinality(String),
    direction           LowCardinality(String),   -- debit/credit
    status              LowCardinality(String),   -- posted/pending/failed/reversed
    payment_method      LowCardinality(String),
    reconciliation_status LowCardinality(String), -- matched/unmatched/pending/disputed
    invoice_ref         String,
    payout_id           String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(txn_date)
ORDER BY (txn_date, vendor_id, transaction_id)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS tbx_finance.vendor_payouts
(
    payout_id       String,
    payout_date     Date,
    vendor_id       String,
    amount          Decimal64(2),
    currency        LowCardinality(String),
    status          LowCardinality(String),   -- completed/pending/failed/scheduled
    method          LowCardinality(String),
    invoice_count   UInt32,
    reference       String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(payout_date)
ORDER BY (payout_date, vendor_id, payout_id);

CREATE TABLE IF NOT EXISTS tbx_finance.reconciliation
(
    recon_id         String,
    transaction_id   String,
    status           LowCardinality(String),  -- matched/unmatched/pending/disputed
    matched_at       Nullable(DateTime),
    bank_reference   String,
    variance_amount  Decimal64(2),
    note             String
)
ENGINE = MergeTree
ORDER BY (transaction_id, recon_id);

CREATE TABLE IF NOT EXISTS tbx_finance.dataset_versions
(
    dataset_version String,
    loaded_at       DateTime,
    source_files    String,
    row_counts      String,
    checksum        String
)
ENGINE = MergeTree
ORDER BY loaded_at;
