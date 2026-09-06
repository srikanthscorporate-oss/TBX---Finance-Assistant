"""Gate verifier for the live MySQL source (see .unlazy/live-mysql/GATES.md).

Every expected value is recomputed here with plain SQL over the source through
pymysql, never through the application: the compiler, pipeline and derived
expressions are the thing under test. The API is exercised through nginx
(TBX_API, default http://localhost:8080) so the whole running stack is what passes.

    python scripts/verify/live_mysql.py <source|entities|dataset|grounded|no_clickhouse|masking|startup>
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[2]
API = os.getenv("TBX_API", "http://localhost:8080").rstrip("/")


def env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def mysql():
    e = env()
    host, port = e["MYSQL_HOST"], int(e.get("MYSQL_PORT", 3306))
    if host == "mysql":  # the compose stand-in, published on the loopback for the host
        host, port = "127.0.0.1", 13306
    return pymysql.connect(host=host, port=port,
                           user=e["MYSQL_USER"], password=e["MYSQL_PASSWORD"],
                           database=e["MYSQL_DB"], read_timeout=180, connect_timeout=15)


def sql(q: str, args=None):
    c = mysql()
    try:
        with c.cursor() as cur:
            cur.execute("SET SESSION MAX_EXECUTION_TIME=170000")
            cur.execute(q, args)
            return cur.fetchall()
    finally:
        c.close()


def get(path: str):
    with urllib.request.urlopen(f"{API}{path}", timeout=200) as r:
        return json.loads(r.read().decode())


def post(path: str, body: dict):
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode()), r.read


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def check_source() -> None:
    e = env()
    h = get("/health")
    if not h.get("ready"):
        fail(f"API not ready: {h}")
    want = f"{e['MYSQL_HOST']}:{e.get('MYSQL_PORT', 3306)}/{e['MYSQL_DB']}"
    if h.get("source") != want:
        fail(f"source is {h.get('source')!r}, expected {want!r}")
    if not str(h.get("dataset_version", "")).startswith("mysql-live-"):
        fail(f"dataset_version {h.get('dataset_version')!r} is not a live-source version")
    st = get("/api/v1/sources/status")
    if st.get("bundled") is not False or st.get("live") is not True:
        fail(f"sources/status does not report a live, non-bundled source: {st}")
    print(f"source={h['source']} version={h['dataset_version']}")
    print("LIVE_SOURCE_PASS")


def check_entities() -> None:
    (n_expected,) = sql("SELECT COUNT(DISTINCT entity_id) FROM account")[0]
    ents = get("/api/v1/entities")
    if len(ents) != n_expected:
        fail(f"API shows {len(ents)} entities, source has {n_expected}")
    (accts,) = sql("SELECT COUNT(*) FROM account")[0]
    if sum(e["accounts"] for e in ents) != accts:
        fail(f"entity account counts sum to {sum(e['accounts'] for e in ents)}, source has {accts}")
    raw_ids = [r[0] for r in sql("SELECT DISTINCT entity_id FROM account")]
    body = json.dumps(ents)
    for rid in raw_ids:
        if rid in body:
            fail(f"raw entity id {rid!r} leaked in /entities")
    print(f"entities={len(ents)} accounts={accts}")
    print("LIVE_ENTITIES_PASS")


def check_dataset() -> None:
    lo, hi = sql("SELECT DATE(MIN(transaction_date)), DATE(MAX(transaction_date)) FROM transaction")[0]
    (accts,) = sql("SELECT COUNT(*) FROM account")[0]
    d = get("/api/v1/dataset")
    if d["min_date"] != lo.isoformat() or d["max_date"] != hi.isoformat():
        fail(f"window {d['min_date']}..{d['max_date']} != source {lo}..{hi}")
    if d["account_count"] != accts:
        fail(f"account_count {d['account_count']} != source {accts}")
    print(f"window={lo}..{hi} accounts={accts}")
    print("LIVE_DATASET_PASS")


def check_grounded() -> None:
    """Ask for yesterday's spend (relative to the dataset's newest day) and recompute it."""
    (hi,) = sql("SELECT DATE(MAX(transaction_date)) FROM transaction")[0]
    day = hi.fromordinal(hi.toordinal() - 1)
    (total, n) = sql(
        "SELECT SUM(t.transaction_amount), COUNT(*) FROM transaction t "
        "WHERE t.transaction_type='debit' AND t.transaction_date >= %s "
        "AND t.transaction_date < DATE_ADD(%s, INTERVAL 1 DAY)", (day, day))[0]
    ent = get("/api/v1/entities")[0]["entity_id"]
    resp, _ = post("/api/v1/chat", {"message": "how much did I spend yesterday",
                                    "conversation_id": f"gate-grounded-{int(time.time())}",
                                    "entity_id": ent})
    if resp.get("state") != "answer":
        fail(f"state {resp.get('state')}: {resp.get('message')}")
    facts = {f["key"]: f for f in resp["evidence"]["facts"]}
    got = Decimal(str(facts["total"]["value"]))
    if abs(got - Decimal(total)) > Decimal("0.01"):
        fail(f"total {got} != independent {total}")
    if int(facts["record_count"]["value"]) != n:
        fail(f"record_count {facts['record_count']['value']} != independent {n}")
    if "yesterday" not in resp["evidence"]["sql"].lower() and "%(d_start)s" not in resp["evidence"]["sql"]:
        fail("evidence SQL does not show the bound date parameters")
    if re.search(r"\d{4,}", resp["answer"].replace(f"{got:,.2f}", "").replace(f"{n:,}", "")
                 .replace(day.isoformat(), "")):
        fail(f"answer carries a figure outside the verified facts: {resp['answer']}")
    print(f"day={day} total={got} count={n} query_ms={resp['evidence'].get('query_duration_ms')}")
    print("LIVE_GROUNDED_PASS")


def check_no_clickhouse() -> None:
    services = subprocess.run(["docker", "compose", "config", "--services"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.split()
    if "clickhouse" in services:
        fail("compose default profile still defines a clickhouse service")
    ps = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True,
                        text=True, check=True).stdout
    if "clickhouse" in ps:
        fail("a clickhouse container exists")
    hits = [p for p in (ROOT / "apps/api/app").rglob("*.py")
            if re.search(r"^\s*(from|import)\s+.*clickhouse", p.read_text(), re.M)]
    if hits:
        fail(f"API imports clickhouse: {[str(h) for h in hits]}")
    h = get("/health")
    if not h.get("ready"):
        fail("API not ready without ClickHouse")
    print("LIVE_NO_CLICKHOUSE_PASS")


def check_masking() -> None:
    numbers = [str(r[0]) for r in sql("SELECT account_number FROM account LIMIT 500")]
    detector = re.compile("|".join(re.escape(n) for n in numbers))
    if not detector.search(f"noise {numbers[3]} noise"):
        fail("positive control: detector missed a planted account number")
    ent = get("/api/v1/entities")[0]["entity_id"]
    q = urllib.parse.quote(ent, safe="")
    bodies = [json.dumps(get(f"/api/v1/accounts?entity_id={q}")),
              json.dumps(get(f"/api/v1/transactions?entity_id={q}&relative=yesterday&limit=50"))]
    resp, _ = post("/api/v1/chat", {"message": "what is my balance",
                                    "conversation_id": f"gate-mask-{int(time.time())}",
                                    "entity_id": ent})
    bodies.append(json.dumps(resp))
    for b in bodies:
        m = detector.search(b)
        if m:
            fail(f"full account number {m.group(0)} appeared in a response body")
    print(f"checked {len(bodies)} bodies against {len(numbers)} account numbers")
    print("LIVE_MASKING_PASS")


def check_startup() -> None:
    subprocess.run(["docker", "compose", "restart", "api"], cwd=ROOT, check=True,
                   capture_output=True)
    t0 = time.time()
    while time.time() - t0 < 45:
        try:
            if get("/health").get("ready"):
                print(f"ready after {time.time() - t0:.1f}s")
                print("LIVE_STARTUP_PASS")
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    fail("API not ready within 45s of restart")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"source": check_source, "entities": check_entities, "dataset": check_dataset,
          "grounded": check_grounded, "no_clickhouse": check_no_clickhouse,
          "masking": check_masking, "startup": check_startup}.get(cmd)
    if fn is None:
        print(__doc__)
        sys.exit(2)
    fn()
