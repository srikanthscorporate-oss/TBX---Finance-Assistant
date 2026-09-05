-- Reference MySQL schema for the Data Source page.
--
-- Any MySQL database can be pointed at the assistant; this is the shape the
-- mapper (apps/api/app/services/source_mapping.py) recognises without needing
-- synonyms. Seed it from the bundled CSVs with scripts/seed_mysql.py and enter
-- host `mysql`, port 3306 on the Data Source page to try the flow end to end.

CREATE TABLE IF NOT EXISTS bank (
    bank_code   VARCHAR(16)  NOT NULL PRIMARY KEY,
    bank_name   VARCHAR(128) NOT NULL
);

CREATE TABLE IF NOT EXISTS account (
    account_id         VARCHAR(64)    NOT NULL PRIMARY KEY,
    entity_id          VARCHAR(64)    NOT NULL,
    account_number     VARCHAR(34)    NOT NULL,
    program_id         INT            NOT NULL DEFAULT 0,
    available_balance  DECIMAL(18, 2) NOT NULL,
    bank_code          VARCHAR(16)    NOT NULL,
    INDEX idx_account_entity (entity_id)
);

CREATE TABLE IF NOT EXISTS transaction (
    transaction_id            VARCHAR(64)    NOT NULL PRIMARY KEY,
    account_id                VARCHAR(64)    NOT NULL,
    transaction_date          DATETIME(6)    NOT NULL,
    transaction_type          VARCHAR(8)     NOT NULL,   -- credit / debit
    description               VARCHAR(512)   NULL,
    transaction_amount        DECIMAL(18, 2) NOT NULL,
    transaction_reference_id  VARCHAR(64)    NULL,
    utr_number                VARCHAR(64)    NULL,
    INDEX idx_txn_account_date (account_id, transaction_date)
);
