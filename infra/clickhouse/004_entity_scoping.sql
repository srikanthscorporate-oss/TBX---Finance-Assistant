-- Optional. Entity scoping enforced in the database with ONE read-only user.
--
-- Not applied by default: the problem statement puts multi-tenant security out of
-- scope and the application does not yet pass an entity per request. Apply by hand
-- once the API sends `SETTINGS SQL_tbx_entity = {entity_id}` on every query:
--
--   docker compose exec clickhouse clickhouse-client --user tbx_admin --password ... \
--       --multiquery < infra/clickhouse/004_entity_scoping.sql
--
-- How it works: the agent user moves from readonly=1 to readonly=2, which still
-- forbids writes but allows per-query settings. Every ceiling in tbx_agent_profile
-- is pinned READONLY, so the only setting a query can add is the custom one below.
-- A query with no entity setting fails (unknown setting) rather than returning
-- everything, and rows from other entities are invisible even without a WHERE.
-- The SQL_ prefix is what the stock ClickHouse image registers for custom settings.
--
-- This is preferable to one database user per entity: 400 entities would mean 400
-- users and a connection per entity in the API, with no gain in isolation.

ALTER SETTINGS PROFILE tbx_agent_profile SETTINGS
    max_execution_time = 10 READONLY,
    max_result_rows = 50000 READONLY,
    max_rows_to_read = 100000000 READONLY,
    max_memory_usage = 2000000000 READONLY,
    readonly = 2 READONLY;

CREATE ROW POLICY IF NOT EXISTS entity_scope ON tbx_finance.transaction
    USING entity_id = getSetting('SQL_tbx_entity') TO tbx_agent;

CREATE ROW POLICY IF NOT EXISTS entity_scope ON tbx_finance.account
    USING entity_id = getSetting('SQL_tbx_entity') TO tbx_agent;
