-- EvoIoT TBox Seed Data (Step 2)
-- Cypher INSERTs for DeviceType, PropertyDef, RelationshipDef nodes
-- This file is a placeholder - full implementation in Step 2

SET search_path TO evoiot, ag_catalog, public;

-- Verify AGE graph exists
SELECT * FROM ag_catalog.ag_graph WHERE name = 'platform';

-- TBox nodes and edges will be added in Step 2:
-- - DeviceType: AHU, VAV, Chiller, Pump, Boiler, Fan, Damper, Valve, Sensor, Meter
-- - PropertyDef: supply_air_temp, return_air_temp, zone_air_temp, power_kw, cop, etc.
-- - RelationshipDef: serves, located_in, connected_to, monitors, feeds
-- - HAS_PROPERTY edges linking DeviceTypes to their PropertyDefs
