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

import os
import subprocess
import time

import httpx
import psycopg2
import pytest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COMPOSE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../platform"))
COMPOSE_FILE = os.path.join(COMPOSE_DIR, "docker-compose.yml")
COMPOSE_OVERRIDE = os.path.join(os.path.dirname(__file__), "docker-compose.override.yml")

POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "15432")  # Use 15432 to avoid conflicts with local postgres
POSTGRES_DSN = f"host=localhost port={POSTGRES_PORT} dbname=postgres user=postgres password=postgres"
POSTGREST_URL = "http://localhost:3000"
RESTATE_URL = "http://localhost:8180"

# Core services needed for platform e2e tests (skip observability, exporters, etc.)
# postgrest has no healthcheck tool in its minimal container, so we wait for it separately
CORE_SERVICES = [
    "postgres", "postgrest", "mosquitto", "bento", "restate", "workflows",
]
WAIT_SERVICES = [
    "postgres", "mosquitto", "bento", "restate", "workflows",
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
    cmd = [DOCKER, "compose", "-f", COMPOSE_FILE, "-f", COMPOSE_OVERRIDE] + list(args)
    result = subprocess.run(cmd, cwd=COMPOSE_DIR, check=False, timeout=timeout,
                            capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"docker compose {' '.join(args)} failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout[-500:] if result.stdout else ''}\n"
            f"stderr: {result.stderr[-500:] if result.stderr else ''}"
        )
    return result


def _wait_for_service(url, path="/", retries=30, interval=2):
    """Poll an HTTP endpoint until it responds."""
    for i in range(retries):
        try:
            r = httpx.get(f"{url}{path}", timeout=5)
            if r.status_code < 500:
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
        # Start core services
        _compose("up", "-d", *CORE_SERVICES, timeout=120)

    # Wait for services to be ready by polling HTTP endpoints
    _wait_for_service(POSTGREST_URL)
    _wait_for_service(RESTATE_URL, path="/restate/health")

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
    with httpx.Client(base_url=RESTATE_URL, timeout=60) as client:
        yield client


def seed_rawtag(db, tenant_id, source_id, device_id, object_type, object_instance, raw_data):
    """Create a RawTag node in the graph via upsert_rawtag()."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT evoiot.upsert_rawtag(%s, %s, %s, %s, %s, %s, %s, %s)",
            (tenant_id, source_id, device_id, object_type, object_instance,
             "bacnet", "object", raw_data),
        )
        return cur.fetchone()[0]


def seed_readings(db, tenant_id, rawtag_id, values):
    """Insert test readings for a given rawtag_id."""
    with db.cursor() as cur:
        for val in values:
            cur.execute(
                """INSERT INTO evoiot.readings
                   (tenant_id, source_type, rawtag_id, point_type, value, unit, observed_at)
                   VALUES (%s, 'sensor', %s, 'unclassified', %s, 'degrees-celsius', now() - interval '%s seconds')""",
                (tenant_id, rawtag_id, val["value"], val["age_seconds"]),
            )
