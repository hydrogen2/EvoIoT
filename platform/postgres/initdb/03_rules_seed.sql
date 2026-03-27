-- EvoIoT Platform Default Rules
-- Source: 'platform' - always-on, operator-managed, read-only to users

SET search_path TO evoiot, public;

INSERT INTO evoiot.rules (building_id, source, name, description, point_type, condition, threshold, severity, device_id, enabled) VALUES
-- Equipment Faults
('*', 'platform', 'equipment_fault', 'Equipment reports fault status', 'fault_status', 'value = 1', 1, 'P1', '*', TRUE),

-- Sensor Offline
('*', 'platform', 'sensor_offline', 'No readings received for extended period', 'any', 'stale > threshold', 900, 'P2', '*', TRUE),

-- Temperature Alarms
('*', 'platform', 'high_zone_temp', 'Zone temperature exceeds comfort threshold', 'zone_air_temp', 'value > threshold', 28, 'P2', '*', TRUE),
('*', 'platform', 'low_zone_temp', 'Zone temperature below comfort threshold', 'zone_air_temp', 'value < threshold', 16, 'P2', '*', TRUE),
('*', 'platform', 'high_supply_air_temp', 'Supply air temperature too high', 'supply_air_temp', 'value > threshold', 35, 'P2', '*', TRUE),
('*', 'platform', 'freeze_protection', 'Temperature approaching freeze point', 'supply_air_temp', 'value < threshold', 4, 'P1', '*', TRUE),

-- Air Quality
('*', 'platform', 'co2_high', 'CO2 level exceeds healthy threshold', 'co2_level', 'value > threshold', 1000, 'P2', '*', TRUE),
('*', 'platform', 'co2_critical', 'CO2 level critically high', 'co2_level', 'value > threshold', 2000, 'P1', '*', TRUE),

-- Humidity
('*', 'platform', 'humidity_high', 'Humidity exceeds acceptable range', 'relative_humidity', 'value > threshold', 70, 'P3', '*', TRUE),
('*', 'platform', 'humidity_low', 'Humidity below acceptable range', 'relative_humidity', 'value < threshold', 30, 'P3', '*', TRUE),

-- Pressure
('*', 'platform', 'duct_pressure_high', 'Duct static pressure too high', 'duct_static_pressure', 'value > threshold', 500, 'P2', '*', TRUE),
('*', 'platform', 'differential_pressure_alarm', 'Filter differential pressure high (filter dirty)', 'differential_pressure', 'value > threshold', 250, 'P3', '*', TRUE),

-- Energy
('*', 'platform', 'energy_spike', 'Sudden energy consumption spike detected', 'power_kw', 'rate_of_change > threshold', 50, 'P2', '*', TRUE),
('*', 'platform', 'power_factor_low', 'Power factor below acceptable level', 'power_factor', 'value < threshold', 0.85, 'P3', '*', TRUE),

-- Chiller/Cooling
('*', 'platform', 'chiller_low_cop', 'Chiller efficiency below expected', 'cop', 'value < threshold', 3.0, 'P3', '*', TRUE),
('*', 'platform', 'condenser_approach_high', 'Condenser approach temperature high', 'condenser_approach_temp', 'value > threshold', 5, 'P3', '*', TRUE),
('*', 'platform', 'evaporator_approach_high', 'Evaporator approach temperature high', 'evaporator_approach_temp', 'value > threshold', 3, 'P3', '*', TRUE),

-- Flow
('*', 'platform', 'low_water_flow', 'Water flow rate below minimum', 'water_flow_rate', 'value < threshold', 10, 'P2', '*', TRUE),
('*', 'platform', 'low_air_flow', 'Air flow rate below setpoint', 'air_flow_rate', 'value < threshold', 100, 'P2', '*', TRUE),

-- Damper/Valve Position
('*', 'platform', 'damper_stuck', 'Damper position not responding to commands', 'damper_position', 'abs(commanded - actual) > threshold', 10, 'P2', '*', TRUE),
('*', 'platform', 'valve_stuck', 'Valve position not responding to commands', 'valve_position', 'abs(commanded - actual) > threshold', 10, 'P2', '*', TRUE),

-- VFD/Motor
('*', 'platform', 'vfd_fault', 'Variable frequency drive fault', 'vfd_fault_status', 'value = 1', 1, 'P1', '*', TRUE),
('*', 'platform', 'motor_overload', 'Motor current exceeds rated value', 'motor_current', 'value > threshold', 100, 'P1', '*', TRUE);
