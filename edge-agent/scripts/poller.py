#!/usr/bin/env python3
"""
BACnet polling using BAC0.
Reads device/object list from SQLite, polls BACnet, writes readings to SQLite.
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

import BAC0

# Configuration
BACNET_IP = os.environ.get("BACNET_IP", "192.168.100.5")
BACNET_SUBNET = os.environ.get("BACNET_SUBNET", "24")
NETWORK = f"{BACNET_IP}/{BACNET_SUBNET}"
DB_PATH = os.environ.get("EDGE_DB_PATH", "/data/edge.db")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))  # seconds
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def get_db():
    """Get SQLite connection."""
    return sqlite3.connect(DB_PATH)


def get_devices_and_objects(conn):
    """Get all devices and their objects from SQLite."""
    cursor = conn.execute("""
        SELECT d.device_id, d.address, o.object_type, o.object_instance, o.object_name, o.unit
        FROM devices d
        JOIN objects o ON d.device_id = o.device_id
        ORDER BY d.device_id, o.object_type, o.object_instance
    """)

    # Group by device
    devices = {}
    for row in cursor:
        device_id, address, obj_type, obj_instance, obj_name, unit = row
        if device_id not in devices:
            devices[device_id] = {
                "address": address,
                "objects": []
            }
        devices[device_id]["objects"].append({
            "type": obj_type,
            "instance": obj_instance,
            "name": obj_name,
            "unit": unit
        })

    return devices


def save_reading(conn, device_id: int, object_type: str, object_instance: int,
                 value: float, status_flags: dict = None):
    """Save a reading to the SQLite buffer."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO readings (device_id, object_type, object_instance, value, status_flags, read_at, uploaded)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    """, (device_id, object_type, object_instance, value,
          json.dumps(status_flags) if status_flags else None, now))


async def poll_device(bacnet, device_id: int, address: str, objects: list):
    """Poll all objects on a device using direct reads."""
    readings = []

    for obj in objects:
        try:
            obj_type = obj['type']
            obj_instance = obj['instance']

            # Read present value directly
            value = await bacnet.read(f"{address} {obj_type} {obj_instance} presentValue")

            # Try to read status flags
            status_flags = None
            try:
                sf = await bacnet.read(f"{address} {obj_type} {obj_instance} statusFlags")
                if sf and hasattr(sf, '__iter__'):
                    status_flags = {
                        "in_alarm": bool(sf[0]) if len(sf) > 0 else False,
                        "fault": bool(sf[1]) if len(sf) > 1 else False,
                        "overridden": bool(sf[2]) if len(sf) > 2 else False,
                        "out_of_service": bool(sf[3]) if len(sf) > 3 else False
                    }
            except:
                pass

            readings.append({
                "device_id": device_id,
                "object_type": obj_type,
                "object_instance": obj_instance,
                "value": float(value) if value is not None else None,
                "status_flags": status_flags
            })
            logger.debug(f"Read {obj_type}:{obj_instance} = {value}")

        except Exception as e:
            logger.warning(f"Failed to read {obj['type']}:{obj['instance']} from device {device_id}: {e}")

    return readings


async def run_poll_cycle(bacnet):
    """Run a single polling cycle."""
    conn = get_db()

    try:
        devices = get_devices_and_objects(conn)

        if not devices:
            logger.warning("No devices found in database. Waiting for discovery...")
            return 0

        total_readings = 0

        for device_id, device_info in devices.items():
            readings = await poll_device(
                bacnet, device_id,
                device_info["address"],
                device_info["objects"]
            )

            for r in readings:
                save_reading(
                    conn, r["device_id"], r["object_type"],
                    r["object_instance"], r["value"], r["status_flags"]
                )
                total_readings += 1

        conn.commit()
        logger.info(f"Poll cycle complete. Saved {total_readings} readings.")
        return total_readings

    except Exception as e:
        logger.error(f"Poll cycle failed: {e}")
        raise
    finally:
        conn.close()


async def main():
    """Main loop - poll continuously."""
    logger.info(f"Starting BACnet polling service")
    logger.info(f"Network: {NETWORK}")
    logger.info(f"Database: {DB_PATH}")
    logger.info(f"Interval: {POLL_INTERVAL}s")

    # Wait for initial discovery to populate devices
    conn = get_db()
    while True:
        cursor = conn.execute("SELECT COUNT(*) FROM devices")
        count = cursor.fetchone()[0]
        if count > 0:
            logger.info(f"Found {count} devices in database, starting polling...")
            break
        logger.info("Waiting for device discovery...")
        await asyncio.sleep(5)
    conn.close()

    # Main polling loop
    async with BAC0.start(ip=NETWORK) as bacnet:
        while True:
            try:
                await run_poll_cycle(bacnet)
            except Exception as e:
                logger.error(f"Poll cycle failed: {e}")

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
