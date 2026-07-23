"""
E2E test fixtures for EvoIoT platform.

Usage:
    cd tests/e2e
    pip install -r requirements.txt
    pytest -v

The fixtures manage the full docker compose lifecycle:
  - session start: docker compose down -v && docker compose up -d --wait
  - session end:   docker compose down -v
"""

import base64
import json
import os
import subprocess
import time

import httpx
import paho.mqtt.client as mqtt
import psycopg2
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--purge-test-tenants", action="store_true", default=False,
        help="After the session, delete everything created by test-e2e "
             "tenants: graph nodes, readings, events, and Restate "
             "invocation state. Use with E2E_MANAGE_STACK=0 to keep a "
             "live stack clean across runs.",
    )

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COMPOSE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../platform"))
COMPOSE_FILE = os.path.join(COMPOSE_DIR, "docker-compose.yml")

POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DSN = f"host=localhost port={POSTGRES_PORT} dbname=postgres user=postgres password=postgres"
POSTGREST_URL = "http://localhost:3000"
RESTATE_INGRESS_URL = "http://localhost:8180"
RESTATE_ADMIN_URL = "http://localhost:9070"
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

# Core services needed for platform e2e tests (skip observability, exporters, etc.)
CORE_SERVICES = [
    "postgres", "postgrest", "mosquitto", "bento", "restate", "workflows",
]

def _find_docker():
    """Find docker executable, checking common Windows paths."""
    docker = os.environ.get("DOCKER", "docker")
    # Try common Docker Desktop paths on Windows
    if os.name == "nt" and docker == "docker":
        win_paths = [
            r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
            r"C:\Program Files\Docker\Docker\resources\docker.exe",
        ]
        for p in win_paths:
            if os.path.isfile(p):
                return p
    return docker

DOCKER = _find_docker()


def _compose(*args, check=True, timeout=120):
    cmd = [DOCKER, "compose", "-f", COMPOSE_FILE] + list(args)
    result = subprocess.run(cmd, cwd=COMPOSE_DIR, check=False, timeout=timeout,
                            capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"docker compose {' '.join(args)} failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout[-500:] if result.stdout else ''}\n"
            f"stderr: {result.stderr[-500:] if result.stderr else ''}"
        )
    return result


def _wait_for_service(url, path="/", retries=30, interval=2, expect_status=None):
    """Poll an HTTP endpoint until it responds."""
    for i in range(retries):
        try:
            r = httpx.get(f"{url}{path}", timeout=5)
            if expect_status and r.status_code == expect_status:
                return
            elif not expect_status and r.status_code < 500:
                return
        except httpx.ConnectError:
            pass
        time.sleep(interval)
    raise TimeoutError(f"{url}{path} not ready after {retries * interval}s")


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def stack():
    """Bring up a fresh platform stack, tear down after all tests."""
    manage_stack = os.environ.get("E2E_MANAGE_STACK", "1") == "1"

    if manage_stack:
        # Clean slate
        _compose("down", "-v", check=False, timeout=60)
        # Start core services (--build ensures latest code)
        _compose("up", "-d", "--build", *CORE_SERVICES, timeout=300)

    # Wait for services to be ready by polling HTTP endpoints
    _wait_for_service(POSTGREST_URL)
    _wait_for_service(RESTATE_INGRESS_URL, path="/restate/health")
    # Wait for workflow service to register with Restate (admin API returns 200 when registered)
    _wait_for_service(RESTATE_ADMIN_URL, path="/services/classifier", retries=30, expect_status=200)

    yield

    if manage_stack:
        # Tear down
        _compose("down", "-v", check=False, timeout=60)


# ---------------------------------------------------------------------------
# Test-tenant purge (opt-in via --purge-test-tenants)
# ---------------------------------------------------------------------------
TEST_TENANT_PREFIX = "test-e2e"
# Workflow keys are urlsafe base64 of "test-e2e-...", so they share this prefix
_B64_TENANT_PREFIX = base64.b64encode(TEST_TENANT_PREFIX.encode()).decode().rstrip("=")


def _purge_test_tenants(session_started_at):
    """Delete all test-tenant residue. Uses its own connections so it does not
    depend on fixture teardown ordering."""
    like = TEST_TENANT_PREFIX + "%"
    conn = psycopg2.connect(POSTGRES_DSN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # Graph: RawTag + Equipment nodes (and their edges) for test tenants
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = ag_catalog, evoiot, public")
            cur.execute(f"""
                SELECT * FROM cypher('platform', $$
                    MATCH (r:RawTag) WHERE r.tenant_id STARTS WITH '{TEST_TENANT_PREFIX}'
                    DETACH DELETE r
                $$) AS (x agtype)
            """)
            cur.execute(f"""
                SELECT * FROM cypher('platform', $$
                    MATCH (e:Equipment) WHERE e.id STARTS WITH '{TEST_TENANT_PREFIX}'
                    DETACH DELETE e
                $$) AS (x agtype)
            """)

            cur.execute("DELETE FROM evoiot.readings WHERE tenant_id LIKE %s", (like,))
            deleted_readings = cur.rowcount

            # Events referencing test tenants directly, via base64 workflow
            # keys, or in payloads — plus anonymous Bento processor spans
            # emitted during this session (noise from processing test messages).
            cur.execute(
                """DELETE FROM evoiot.events
                   WHERE data_id LIKE %s OR trace_id LIKE %s
                      OR data_id LIKE %s OR trace_id LIKE %s
                      OR payload::text LIKE %s
                      OR (component = 'bento' AND data_id IS NULL
                          AND event_time >= %s)""",
                (like, like, _B64_TENANT_PREFIX + "%", _B64_TENANT_PREFIX + "%",
                 "%" + TEST_TENANT_PREFIX + "%", session_started_at),
            )
            deleted_events = cur.rowcount
    finally:
        conn.close()

    # Restate: purge invocation state for test-tenant workflow keys
    purged = 0
    try:
        r = httpx.post(
            f"{RESTATE_ADMIN_URL}/query",
            json={"query": "SELECT id, target FROM sys_invocation"},
            headers={"Accept": "application/json"},
            timeout=10,
        )
        for row in r.json().get("rows", []):
            if "/" + _B64_TENANT_PREFIX in row.get("target", ""):
                for mode in ("purge", "kill"):
                    resp = httpx.delete(
                        f"{RESTATE_ADMIN_URL}/invocations/{row['id']}?mode={mode}",
                        timeout=10,
                    )
                    if resp.status_code < 300:
                        purged += 1
                        break
    except httpx.HTTPError as e:
        print(f"[purge] Restate purge skipped: {e}")

    print(f"[purge] test tenants removed: {deleted_readings} readings, "
          f"{deleted_events} events, {purged} Restate invocations, "
          f"graph nodes for '{TEST_TENANT_PREFIX}*'")


@pytest.fixture(scope="session", autouse=True)
def purge_test_tenants(request, stack):
    """Optionally wipe all test-tenant data after the session.

    Depends on `stack` so its teardown runs BEFORE the stack is torn down.
    Pointless with E2E_MANAGE_STACK=1 (down -v wipes volumes anyway), but
    harmless there; intended for runs against a persistent stack.
    """
    session_started_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    yield
    if request.config.getoption("--purge-test-tenants"):
        _purge_test_tenants(session_started_at)


@pytest.fixture(scope="session")
def db(stack):
    """Provide a psycopg2 connection to the platform database."""
    for attempt in range(30):
        try:
            conn = psycopg2.connect(POSTGRES_DSN)
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError:
            time.sleep(2)
    raise TimeoutError("Could not connect to PostgreSQL after 60s")


@pytest.fixture(autouse=True, scope="session")
def _cleanup_db(db):
    yield
    db.close()


@pytest.fixture(scope="session")
def api(stack):
    """Provide an httpx client for the PostgREST API."""
    with httpx.Client(base_url=POSTGREST_URL, timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
def restate(stack):
    """Provide an httpx client for the Restate ingress API."""
    with httpx.Client(base_url=RESTATE_INGRESS_URL, timeout=60) as client:
        yield client


@pytest.fixture(scope="session")
def mqtt_client(stack):
    """Provide a connected MQTT client."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="e2e-test")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    yield client
    client.loop_stop()
    client.disconnect()


# ---------------------------------------------------------------------------
# MQTT seed helpers (data flows through Bento → Postgres)
# ---------------------------------------------------------------------------
def publish_discovery(mqtt_client, tenant_id, source_id, devices, building=None):
    """Publish a discovery message to MQTT (triggers Bento discovery pipeline)."""
    topic = f"tenants/{tenant_id}/agents/{source_id}/discovery"
    payload = json.dumps({
        "tenant_id": tenant_id,
        "agent_id": source_id,
        "building": building or tenant_id,
        "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "devices": devices,
    })
    mqtt_client.publish(topic, payload, qos=1)


def publish_telemetry(mqtt_client, tenant_id, source_id, readings):
    """Publish telemetry readings to MQTT (triggers Bento telemetry pipeline).

    Each reading dict should have: value, unit, point_type, object_type, object_instance, device_id
    """
    topic = f"tenants/{tenant_id}/agents/{source_id}/telemetry"
    for reading in readings:
        payload = json.dumps({
            "tenant_id": tenant_id,
            "agent_id": source_id,
            "device_id": reading.get("device_id", "9001"),
            "object_type": reading.get("object_type", "analog-value"),
            "object_instance": reading.get("object_instance", "10"),
            "point_type": reading.get("point_type", "unclassified"),
            "value": reading["value"],
            "unit": reading.get("unit", "degrees-celsius"),
            "agent_read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        mqtt_client.publish(topic, payload, qos=1)


def wait_for_db_rows(db, query, params, min_count=1, retries=30, interval=2):
    """Poll the database until a query returns at least min_count rows."""
    for attempt in range(retries):
        with db.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            if len(rows) >= min_count:
                return rows
        time.sleep(interval)
    raise TimeoutError(f"Expected >= {min_count} rows after {retries * interval}s, got {len(rows)}")
