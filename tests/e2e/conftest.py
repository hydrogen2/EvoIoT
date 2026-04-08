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

POSTGRES_DSN = "host=localhost port=5432 dbname=postgres user=postgres password=postgres"
POSTGREST_URL = "http://localhost:3000"
RESTATE_URL = "http://localhost:8180"

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
    # Clean slate
    _compose("down", "-v", check=False, timeout=60)
    # Start only core services
    _compose("up", "-d", "--wait", *CORE_SERVICES, timeout=300)

    # Extra wait for PostgREST and Restate to be fully ready
    _wait_for_service(POSTGREST_URL)
    _wait_for_service(RESTATE_URL, path="/restate/health")

    yield

    # Tear down
    _compose("down", "-v", check=False, timeout=60)


@pytest.fixture(scope="session")
def db(stack):
    """Provide a psycopg2 connection to the platform database."""
    conn = psycopg2.connect(POSTGRES_DSN)
    conn.autocommit = True
    yield conn
    conn.close()


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
