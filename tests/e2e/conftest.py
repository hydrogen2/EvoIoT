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

import json
import os
import subprocess
import time

import httpx
import paho.mqtt.client as mqtt
import psycopg2
import pytest

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
def publish_discovery(mqtt_client, tenant_id, source_id, devices):
    """Publish a discovery message to MQTT (triggers Bento discovery pipeline)."""
    topic = f"buildings/{tenant_id}/agents/{source_id}/discovery"
    payload = json.dumps({
        "building_id": tenant_id,
        "source_id": source_id,
        "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "devices": devices,
    })
    mqtt_client.publish(topic, payload, qos=1)


def publish_telemetry(mqtt_client, tenant_id, source_id, readings):
    """Publish telemetry readings to MQTT (triggers Bento telemetry pipeline).

    Each reading dict should have: value, unit, point_type, object_type, object_instance, device_id
    """
    topic = f"buildings/{tenant_id}/agents/{source_id}/telemetry"
    for reading in readings:
        payload = json.dumps({
            "building_id": tenant_id,
            "source_id": source_id,
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
