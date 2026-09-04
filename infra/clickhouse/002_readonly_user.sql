-- The agent connects as this user. It can read finance tables and nothing else.
-- Defence in depth behind the compiler allowlist: even a compiler bug cannot
-- mutate or drop financial data.
CREATE USER IF NOT EXISTS tbx_agent IDENTIFIED WITH sha256_password BY '{{TBX_CH_AGENT_PASSWORD}}';

CREATE ROLE IF NOT EXISTS tbx_readonly;
GRANT SELECT ON tbx_finance.* TO tbx_readonly;
GRANT tbx_readonly TO tbx_agent;

-- Hard server-side ceilings. The application sets its own limits too; these
-- are the ones an application bug cannot raise.
CREATE SETTINGS PROFILE IF NOT EXISTS tbx_agent_profile SETTINGS
    max_execution_time = 10 READONLY,
    max_result_rows = 50000 READONLY,
    -- The prototype is tested at 20M records and ClickHouse reads whole
    -- granules, so a ceiling AT 20M rejects a full-table aggregate. 100M
    -- leaves headroom while still bounding a runaway scan.
    max_rows_to_read = 100000000 READONLY,
    max_memory_usage = 2000000000 READONLY,
    readonly = 1;

ALTER USER tbx_agent SETTINGS PROFILE tbx_agent_profile;
