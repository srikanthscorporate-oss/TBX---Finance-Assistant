-- Read-only user the agent connects as; a backstop behind the compiler allowlist.
CREATE USER IF NOT EXISTS tbx_agent IDENTIFIED WITH sha256_password BY '{{TBX_CH_AGENT_PASSWORD}}';

CREATE ROLE IF NOT EXISTS tbx_readonly;
GRANT SELECT ON tbx_finance.* TO tbx_readonly;
GRANT tbx_readonly TO tbx_agent;

-- Server-side ceilings the application cannot raise.
CREATE SETTINGS PROFILE IF NOT EXISTS tbx_agent_profile SETTINGS
    max_execution_time = 10 READONLY,
    max_result_rows = 50000 READONLY,
    -- 100M rather than 20M: whole granules are read, so a 20M ceiling rejects the scale test.
    max_rows_to_read = 100000000 READONLY,
    max_memory_usage = 2000000000 READONLY,
    readonly = 1;

ALTER USER tbx_agent SETTINGS PROFILE tbx_agent_profile;
