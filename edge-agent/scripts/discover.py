#!/usr/bin/env python3
"""
BACnet device discovery using BAC0.
Discovers devices on the network and writes to SQLite.
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
DISCOVERY_INTERVAL = int(os.environ.get("DISCOVERY_INTERVAL", "300"))  # 5 minutes
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def get_db():
    """Get SQLite connection."""
    return sqlite3.connect(DB_PATH)


def save_device(conn, device_id: int, address: str, name: str = None,
                vendor: str = None, model: str = None):
    """Insert or update a device in the database."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO devices (device_id, address, name, vendor, model, discovered_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            address = excluded.address,
            name = excluded.name,
            vendor = excluded.vendor,
            model = excluded.model,
            last_seen_at = excluded.last_seen_at
    """, (device_id, address, name, vendor, model, now, now))


def save_object(conn, device_id: int, object_type: str, object_instance: int,
                object_name: str = None, unit: str = None):
    """Insert or update an object in the database."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO objects (device_id, object_type, object_instance, object_name, unit, discovered_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id, object_type, object_instance) DO UPDATE SET
            object_name = excluded.object_name,
            unit = excluded.unit
    """, (device_id, object_type, object_instance, object_name, unit, now))


async def discover_devices(bacnet):
    """Discover all BACnet devices on the network."""
    logger.info("Starting device discovery...")

    # Broadcast Who-Is and wait for responses
    await bacnet._discover(global_broadcast=True)
    await asyncio.sleep(5)  # Wait for I-Am responses

    # In BAC0 async mode, discovered devices are in discoveredDevices dict
    # Format: {"device,<id>": {'address': IPv4Address, 'object_instance': tuple, ...}}
    discovered = bacnet.discoveredDevices or {}
    logger.debug(f"discoveredDevices raw: {discovered}")

    devices = []
    for device_key, device_info in discovered.items():
        # device_key is like "device,1113"
        # Extract numeric device_id
        try:
            device_id = int(device_key.split(",")[1])
        except (IndexError, ValueError):
            logger.warning(f"Could not parse device_id from key: {device_key}")
            continue

        # Extract IP address from device_info dict
        if isinstance(device_info, dict) and 'address' in device_info:
            address = str(device_info['address'])
        elif hasattr(device_info, 'address'):
            address = str(device_info.address)
        else:
            logger.warning(f"Could not find address for device {device_key}: {device_info}")
            continue

        devices.append((address, device_id))
        logger.debug(f"Found device {device_id} at {address}")

    logger.info(f"Discovered {len(devices)} devices")
    return devices


async def discover_objects(bacnet, device_address, device_id):
    """Discover all objects on a device."""
    logger.info(f"Discovering objects on device {device_id} at {device_address}")

    try:
        # Read device name
        device_name = await bacnet.read(f"{device_address} device {device_id} objectName")
        vendor_name = await bacnet.read(f"{device_address} device {device_id} vendorName")
        model_name = None
        try:
            model_name = await bacnet.read(f"{device_address} device {device_id} modelName")
        except:
            pass

        device_info = {
            "name": str(device_name) if device_name else None,
            "vendor": str(vendor_name) if vendor_name else None,
            "model": str(model_name) if model_name else None
        }

        # Read object list from device
        object_list = await bacnet.read(f"{device_address} device {device_id} objectList")
        logger.debug(f"Object list for device {device_id}: {object_list}")

        objects = []
        if object_list:
            for obj_id in object_list:
                # obj_id is typically (object_type, instance)
                if isinstance(obj_id, tuple) and len(obj_id) >= 2:
                    obj_type, obj_instance = obj_id[0], obj_id[1]
                else:
                    continue

                # Skip device object itself
                obj_type_str = str(obj_type)
                if "device" in obj_type_str.lower():
                    continue

                # Read object name
                obj_name = None
                unit = None
                try:
                    obj_name = await bacnet.read(f"{device_address} {obj_type_str} {obj_instance} objectName")
                except:
                    pass
                try:
                    unit = await bacnet.read(f"{device_address} {obj_type_str} {obj_instance} units")
                except:
                    pass

                objects.append({
                    "object_type": obj_type_str,
                    "object_instance": int(obj_instance),
                    "object_name": str(obj_name) if obj_name else None,
                    "unit": str(unit) if unit else None
                })

        logger.info(f"Found {len(objects)} objects on device {device_id}")
        return objects, device_info

    except Exception as e:
        logger.error(f"Failed to read objects from device {device_id}: {e}")
        import traceback
        traceback.print_exc()
        return [], None


async def run_discovery():
    """Run a single discovery cycle."""
    conn = get_db()

    try:
        async with BAC0.start(ip=NETWORK) as bacnet:
            # Discover devices
            devices = await discover_devices(bacnet)

            for device_address, device_id in devices:
                # Get device details and objects
                objects, device_info = await discover_objects(bacnet, device_address, device_id)

                # Save device
                device_name = device_info.get("name") if device_info else None
                vendor = device_info.get("vendor") if device_info else None
                model = device_info.get("model") if device_info else None

                save_device(conn, device_id, str(device_address), device_name, vendor, model)

                # Save objects
                for obj in objects:
                    save_object(
                        conn, device_id,
                        obj["object_type"],
                        obj["object_instance"],
                        obj["object_name"],
                        obj["unit"]
                    )

            conn.commit()
            logger.info(f"Discovery complete. Saved {len(devices)} devices to database.")

    except Exception as e:
        logger.error(f"Discovery failed: {e}")
        raise
    finally:
        conn.close()


async def main():
    """Main loop - run discovery periodically."""
    logger.info(f"Starting BACnet discovery service")
    logger.info(f"Network: {NETWORK}")
    logger.info(f"Database: {DB_PATH}")
    logger.info(f"Interval: {DISCOVERY_INTERVAL}s")

    while True:
        try:
            await run_discovery()
        except Exception as e:
            logger.error(f"Discovery cycle failed: {e}")

        logger.info(f"Sleeping {DISCOVERY_INTERVAL}s until next discovery...")
        await asyncio.sleep(DISCOVERY_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
