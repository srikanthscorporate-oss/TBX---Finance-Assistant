-- Bank statement schema from docs/TBX - Database Schema.md: bank -> account -> transaction.
-- Sensitive fields are stored AES-256-GCM encrypted by the loader; the key never reaches
-- ClickHouse. Searchable encrypted fields carry an HMAC blind index for equality lookup.

CREATE DATABASE IF NOT EXISTS tbx_finance;

CREATE TABLE IF NOT EXISTS tbx_finance.bank
(
    bank_code   LowCardinality(String),
    bank_name   String
)
ENGINE = ReplacingMergeTree
ORDER BY bank_code;

CREATE TABLE IF NOT EXISTS tbx_finance.account
(
    account_id          String,
    entity_id           String,
    account_number_enc  String,           -- AES-256-GCM, base64(nonce||ct||tag)
    account_last4       String,           -- for masked display and "ending 1234" matching
    program_id          UInt16,
    available_balance   Decimal64(2),
    bank_code           LowCardinality(String)
)
ENGINE = ReplacingMergeTree
ORDER BY (entity_id, account_id);

-- entity_id and bank_code are copied from account at load time so entity-scoped queries
-- never join across 20M rows. counterparty and channel are parsed from the narration by
-- the loader (scripts/load_dataset.py, parse_narration) so "payments to Swiggy" is a
-- LowCardinality equality filter instead of a substring scan.
CREATE TABLE IF NOT EXISTS tbx_finance.transaction
(
    transaction_id            String,
    account_id                String,
    entity_id                 String,
    bank_code                 LowCardinality(String),
    transaction_date          DateTime64(6),
    txn_date                  Date MATERIALIZED toDate(transaction_date),
    transaction_type          LowCardinality(String),  -- credit/debit
    description               String,
    counterparty              LowCardinality(String),
    channel                   LowCardinality(String),  -- NEFT/IMPS/UPI/FT/RTGS/CHEQUE/CHARGES/INTEREST/OTHER
    transaction_amount        Decimal64(2),
    transaction_reference_id  String,
    utr_enc                   String,                  -- AES-256-GCM
    utr_hash                  String,                  -- HMAC-SHA256 blind index
    INDEX idx_ref transaction_reference_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_utr utr_hash TYPE bloom_filter GRANULARITY 4,
    INDEX idx_amount transaction_amount TYPE minmax GRANULARITY 4
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(transaction_date)
ORDER BY (entity_id, account_id, transaction_date, transaction_id)
SETTINGS index_granularity = 8192;

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
