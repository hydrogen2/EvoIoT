-- EvoIoT TBox Seed Data (Step 2)
-- Cypher INSERTs for DeviceType, PropertyDef, RelationshipDef nodes
-- and HAS_PROPERTY edges linking types to properties

LOAD 'age';
SET search_path = ag_catalog, evoiot, public;

-- =============================================================================
-- DeviceType Nodes
-- =============================================================================

-- HVAC Equipment
SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'AHU',
    label: 'Air Handling Unit',
    description: 'Equipment that conditions and circulates air as part of HVAC system',
    category: 'hvac',
    brick_class: 'https://brickschema.org/schema/Brick#Air_Handling_Unit'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'VAV',
    label: 'Variable Air Volume Box',
    description: 'Terminal unit that regulates airflow to a zone',
    category: 'hvac',
    brick_class: 'https://brickschema.org/schema/Brick#Variable_Air_Volume_Box'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'FCU',
    label: 'Fan Coil Unit',
    description: 'Terminal unit with fan and heating/cooling coil',
    category: 'hvac',
    brick_class: 'https://brickschema.org/schema/Brick#Fan_Coil_Unit'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'RTU',
    label: 'Rooftop Unit',
    description: 'Packaged HVAC unit installed on roof',
    category: 'hvac',
    brick_class: 'https://brickschema.org/schema/Brick#Rooftop_Unit'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'MAU',
    label: 'Makeup Air Unit',
    description: 'Unit that provides conditioned outdoor air',
    category: 'hvac',
    brick_class: 'https://brickschema.org/schema/Brick#Makeup_Air_Unit'
  }) RETURN n
$$) AS (n agtype);

-- Cooling Equipment
SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'Chiller',
    label: 'Chiller',
    description: 'Machine that removes heat from a liquid via vapor-compression or absorption',
    category: 'cooling',
    brick_class: 'https://brickschema.org/schema/Brick#Chiller'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'CoolingTower',
    label: 'Cooling Tower',
    description: 'Heat rejection device that rejects waste heat to atmosphere',
    category: 'cooling',
    brick_class: 'https://brickschema.org/schema/Brick#Cooling_Tower'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'CRAC',
    label: 'Computer Room Air Conditioner',
    description: 'Precision cooling unit for data centers',
    category: 'cooling',
    brick_class: 'https://brickschema.org/schema/Brick#Computer_Room_Air_Conditioner'
  }) RETURN n
$$) AS (n agtype);

-- Heating Equipment
SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'Boiler',
    label: 'Boiler',
    description: 'Vessel in which water is heated',
    category: 'heating',
    brick_class: 'https://brickschema.org/schema/Brick#Boiler'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'HeatExchanger',
    label: 'Heat Exchanger',
    description: 'Device for transferring heat between fluids',
    category: 'heating',
    brick_class: 'https://brickschema.org/schema/Brick#Heat_Exchanger'
  }) RETURN n
$$) AS (n agtype);

-- Pumps and Fans
SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'Pump',
    label: 'Pump',
    description: 'Device that moves fluids by mechanical action',
    category: 'distribution',
    brick_class: 'https://brickschema.org/schema/Brick#Pump'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'Fan',
    label: 'Fan',
    description: 'Device that creates airflow',
    category: 'distribution',
    brick_class: 'https://brickschema.org/schema/Brick#Fan'
  }) RETURN n
$$) AS (n agtype);

-- Actuators
SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'Damper',
    label: 'Damper',
    description: 'Valve or plate that regulates airflow',
    category: 'actuator',
    brick_class: 'https://brickschema.org/schema/Brick#Damper'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'Valve',
    label: 'Valve',
    description: 'Device that regulates fluid flow',
    category: 'actuator',
    brick_class: 'https://brickschema.org/schema/Brick#Valve'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'VFD',
    label: 'Variable Frequency Drive',
    description: 'Motor controller that varies frequency and voltage',
    category: 'actuator',
    brick_class: 'https://brickschema.org/schema/Brick#Variable_Frequency_Drive'
  }) RETURN n
$$) AS (n agtype);

-- Sensors
SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'TemperatureSensor',
    label: 'Temperature Sensor',
    description: 'Sensor that measures temperature',
    category: 'sensor',
    brick_class: 'https://brickschema.org/schema/Brick#Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'HumiditySensor',
    label: 'Humidity Sensor',
    description: 'Sensor that measures relative humidity',
    category: 'sensor',
    brick_class: 'https://brickschema.org/schema/Brick#Humidity_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'CO2Sensor',
    label: 'CO2 Sensor',
    description: 'Sensor that measures carbon dioxide concentration',
    category: 'sensor',
    brick_class: 'https://brickschema.org/schema/Brick#CO2_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'PressureSensor',
    label: 'Pressure Sensor',
    description: 'Sensor that measures pressure',
    category: 'sensor',
    brick_class: 'https://brickschema.org/schema/Brick#Pressure_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'FlowSensor',
    label: 'Flow Sensor',
    description: 'Sensor that measures fluid flow rate',
    category: 'sensor',
    brick_class: 'https://brickschema.org/schema/Brick#Flow_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'OccupancySensor',
    label: 'Occupancy Sensor',
    description: 'Sensor that detects presence of people',
    category: 'sensor',
    brick_class: 'https://brickschema.org/schema/Brick#Occupancy_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Meters
SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'ElectricMeter',
    label: 'Electric Meter',
    description: 'Device that measures electrical energy consumption',
    category: 'meter',
    brick_class: 'https://brickschema.org/schema/Brick#Electrical_Meter'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'WaterMeter',
    label: 'Water Meter',
    description: 'Device that measures water consumption',
    category: 'meter',
    brick_class: 'https://brickschema.org/schema/Brick#Water_Meter'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'GasMeter',
    label: 'Gas Meter',
    description: 'Device that measures gas consumption',
    category: 'meter',
    brick_class: 'https://brickschema.org/schema/Brick#Gas_Meter'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'BTUMeter',
    label: 'BTU Meter',
    description: 'Device that measures thermal energy',
    category: 'meter',
    brick_class: 'https://brickschema.org/schema/Brick#Thermal_Power_Meter'
  }) RETURN n
$$) AS (n agtype);

-- Spatial
SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'Thermostat',
    label: 'Thermostat',
    description: 'Device that regulates temperature',
    category: 'controller',
    brick_class: 'https://brickschema.org/schema/Brick#Thermostat'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:DeviceType {
    name: 'BACnetGateway',
    label: 'BACnet Gateway',
    description: 'Device that translates between BACnet and other protocols',
    category: 'infrastructure',
    brick_class: 'https://brickschema.org/schema/Brick#Gateway'
  }) RETURN n
$$) AS (n agtype);

-- =============================================================================
-- PropertyDef Nodes (Point Types)
-- =============================================================================

-- Temperature Properties
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'supply_air_temp',
    label: 'Supply Air Temperature',
    description: 'Temperature of air leaving equipment',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Supply_Air_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'return_air_temp',
    label: 'Return Air Temperature',
    description: 'Temperature of air returning to equipment',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Return_Air_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'zone_air_temp',
    label: 'Zone Air Temperature',
    description: 'Temperature of air in a zone',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Zone_Air_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'outdoor_air_temp',
    label: 'Outdoor Air Temperature',
    description: 'Temperature of outdoor air',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    source_type: 'context',
    brick_class: 'https://brickschema.org/schema/Brick#Outside_Air_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'mixed_air_temp',
    label: 'Mixed Air Temperature',
    description: 'Temperature of mixed outdoor and return air',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Mixed_Air_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'discharge_air_temp',
    label: 'Discharge Air Temperature',
    description: 'Temperature of air discharged from terminal unit',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Discharge_Air_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'chilled_water_supply_temp',
    label: 'Chilled Water Supply Temperature',
    description: 'Temperature of chilled water leaving chiller',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Chilled_Water_Supply_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'chilled_water_return_temp',
    label: 'Chilled Water Return Temperature',
    description: 'Temperature of chilled water returning to chiller',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Chilled_Water_Return_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'hot_water_supply_temp',
    label: 'Hot Water Supply Temperature',
    description: 'Temperature of hot water leaving boiler',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Hot_Water_Supply_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'hot_water_return_temp',
    label: 'Hot Water Return Temperature',
    description: 'Temperature of hot water returning to boiler',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Hot_Water_Return_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'condenser_water_supply_temp',
    label: 'Condenser Water Supply Temperature',
    description: 'Temperature of condenser water supply',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Condenser_Water_Supply_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'condenser_water_return_temp',
    label: 'Condenser Water Return Temperature',
    description: 'Temperature of condenser water return',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Condenser_Water_Return_Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Setpoints
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'zone_temp_setpoint',
    label: 'Zone Temperature Setpoint',
    description: 'Target temperature for zone',
    unit: 'celsius',
    data_type: 'float',
    category: 'setpoint',
    brick_class: 'https://brickschema.org/schema/Brick#Zone_Air_Temperature_Setpoint'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'supply_air_temp_setpoint',
    label: 'Supply Air Temperature Setpoint',
    description: 'Target temperature for supply air',
    unit: 'celsius',
    data_type: 'float',
    category: 'setpoint',
    brick_class: 'https://brickschema.org/schema/Brick#Supply_Air_Temperature_Setpoint'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'chilled_water_temp_setpoint',
    label: 'Chilled Water Temperature Setpoint',
    description: 'Target temperature for chilled water',
    unit: 'celsius',
    data_type: 'float',
    category: 'setpoint',
    brick_class: 'https://brickschema.org/schema/Brick#Chilled_Water_Temperature_Setpoint'
  }) RETURN n
$$) AS (n agtype);

-- Humidity Properties
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'relative_humidity',
    label: 'Relative Humidity',
    description: 'Relative humidity measurement',
    unit: 'percent',
    data_type: 'float',
    category: 'humidity',
    brick_class: 'https://brickschema.org/schema/Brick#Relative_Humidity_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'zone_humidity',
    label: 'Zone Humidity',
    description: 'Humidity level in a zone',
    unit: 'percent',
    data_type: 'float',
    category: 'humidity',
    brick_class: 'https://brickschema.org/schema/Brick#Zone_Humidity_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Air Quality Properties
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'co2_level',
    label: 'CO2 Level',
    description: 'Carbon dioxide concentration',
    unit: 'ppm',
    data_type: 'float',
    category: 'air_quality',
    brick_class: 'https://brickschema.org/schema/Brick#CO2_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'pm25',
    label: 'PM2.5',
    description: 'Particulate matter 2.5 microns or smaller',
    unit: 'ug/m3',
    data_type: 'float',
    category: 'air_quality',
    brick_class: 'https://brickschema.org/schema/Brick#PM2.5_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'tvoc',
    label: 'Total VOC',
    description: 'Total volatile organic compounds',
    unit: 'ppb',
    data_type: 'float',
    category: 'air_quality',
    brick_class: 'https://brickschema.org/schema/Brick#TVOC_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Pressure Properties
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'duct_static_pressure',
    label: 'Duct Static Pressure',
    description: 'Static pressure in ductwork',
    unit: 'pascal',
    data_type: 'float',
    category: 'pressure',
    brick_class: 'https://brickschema.org/schema/Brick#Duct_Static_Pressure_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'differential_pressure',
    label: 'Differential Pressure',
    description: 'Pressure difference across component',
    unit: 'pascal',
    data_type: 'float',
    category: 'pressure',
    brick_class: 'https://brickschema.org/schema/Brick#Differential_Pressure_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'building_static_pressure',
    label: 'Building Static Pressure',
    description: 'Static pressure in building',
    unit: 'pascal',
    data_type: 'float',
    category: 'pressure',
    brick_class: 'https://brickschema.org/schema/Brick#Building_Static_Pressure_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Flow Properties
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'air_flow_rate',
    label: 'Air Flow Rate',
    description: 'Rate of airflow',
    unit: 'cfm',
    data_type: 'float',
    category: 'flow',
    brick_class: 'https://brickschema.org/schema/Brick#Air_Flow_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'water_flow_rate',
    label: 'Water Flow Rate',
    description: 'Rate of water flow',
    unit: 'gpm',
    data_type: 'float',
    category: 'flow',
    brick_class: 'https://brickschema.org/schema/Brick#Water_Flow_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Energy Properties
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'power_kw',
    label: 'Power',
    description: 'Electrical power consumption',
    unit: 'kW',
    data_type: 'float',
    category: 'energy',
    brick_class: 'https://brickschema.org/schema/Brick#Electric_Power_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'energy_kwh',
    label: 'Energy Consumption',
    description: 'Cumulative electrical energy consumption',
    unit: 'kWh',
    data_type: 'float',
    category: 'energy',
    brick_class: 'https://brickschema.org/schema/Brick#Electric_Energy_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'power_factor',
    label: 'Power Factor',
    description: 'Ratio of real power to apparent power',
    unit: 'ratio',
    data_type: 'float',
    category: 'energy',
    brick_class: 'https://brickschema.org/schema/Brick#Power_Factor_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'cop',
    label: 'Coefficient of Performance',
    description: 'Ratio of cooling provided to energy consumed',
    unit: 'ratio',
    data_type: 'float',
    category: 'efficiency',
    brick_class: 'https://brickschema.org/schema/Brick#Efficiency_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'thermal_power',
    label: 'Thermal Power',
    description: 'Thermal energy transfer rate',
    unit: 'kW',
    data_type: 'float',
    category: 'energy',
    brick_class: 'https://brickschema.org/schema/Brick#Thermal_Power_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Position Properties
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'damper_position',
    label: 'Damper Position',
    description: 'Position of damper (0-100%)',
    unit: 'percent',
    data_type: 'float',
    category: 'position',
    brick_class: 'https://brickschema.org/schema/Brick#Damper_Position_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'valve_position',
    label: 'Valve Position',
    description: 'Position of valve (0-100%)',
    unit: 'percent',
    data_type: 'float',
    category: 'position',
    brick_class: 'https://brickschema.org/schema/Brick#Valve_Position_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Speed Properties
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'fan_speed',
    label: 'Fan Speed',
    description: 'Speed of fan (0-100% or RPM)',
    unit: 'percent',
    data_type: 'float',
    category: 'speed',
    brick_class: 'https://brickschema.org/schema/Brick#Speed_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'pump_speed',
    label: 'Pump Speed',
    description: 'Speed of pump (0-100% or RPM)',
    unit: 'percent',
    data_type: 'float',
    category: 'speed',
    brick_class: 'https://brickschema.org/schema/Brick#Speed_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'motor_current',
    label: 'Motor Current',
    description: 'Electrical current drawn by motor',
    unit: 'ampere',
    data_type: 'float',
    category: 'electrical',
    brick_class: 'https://brickschema.org/schema/Brick#Current_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Status Properties
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'on_off_status',
    label: 'On/Off Status',
    description: 'Binary on/off status',
    unit: 'binary',
    data_type: 'boolean',
    category: 'status',
    brick_class: 'https://brickschema.org/schema/Brick#On_Off_Status'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'fault_status',
    label: 'Fault Status',
    description: 'Equipment fault indicator',
    unit: 'binary',
    data_type: 'boolean',
    category: 'status',
    brick_class: 'https://brickschema.org/schema/Brick#Fault_Status'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'vfd_fault_status',
    label: 'VFD Fault Status',
    description: 'Variable frequency drive fault indicator',
    unit: 'binary',
    data_type: 'boolean',
    category: 'status',
    brick_class: 'https://brickschema.org/schema/Brick#Fault_Status'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'occupancy_status',
    label: 'Occupancy Status',
    description: 'Zone occupancy indicator',
    unit: 'binary',
    data_type: 'boolean',
    category: 'status',
    brick_class: 'https://brickschema.org/schema/Brick#Occupancy_Status'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'occupancy_count',
    label: 'Occupancy Count',
    description: 'Number of occupants',
    unit: 'count',
    data_type: 'integer',
    category: 'occupancy',
    source_type: 'context',
    brick_class: 'https://brickschema.org/schema/Brick#Occupancy_Count_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Approach Temperatures
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'condenser_approach_temp',
    label: 'Condenser Approach Temperature',
    description: 'Temperature difference across condenser',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'evaporator_approach_temp',
    label: 'Evaporator Approach Temperature',
    description: 'Temperature difference across evaporator',
    unit: 'celsius',
    data_type: 'float',
    category: 'temperature',
    brick_class: 'https://brickschema.org/schema/Brick#Temperature_Sensor'
  }) RETURN n
$$) AS (n agtype);

-- Context Properties (external data)
SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'electricity_rate',
    label: 'Electricity Rate',
    description: 'Current electricity price',
    unit: 'currency_per_kwh',
    data_type: 'float',
    category: 'context',
    source_type: 'context',
    brick_class: null
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:PropertyDef {
    name: 'weather_condition',
    label: 'Weather Condition',
    description: 'Current weather description',
    unit: 'text',
    data_type: 'string',
    category: 'context',
    source_type: 'context',
    brick_class: null
  }) RETURN n
$$) AS (n agtype);

-- =============================================================================
-- RelationshipDef Nodes
-- =============================================================================

SELECT * FROM cypher('platform', $$
  CREATE (n:RelationshipDef {
    name: 'serves',
    label: 'Serves',
    description: 'Equipment serves a zone or another equipment',
    inverse: 'served_by',
    brick_class: 'https://brickschema.org/schema/Brick#feeds'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:RelationshipDef {
    name: 'feeds',
    label: 'Feeds',
    description: 'Equipment feeds another equipment (fluid/air flow)',
    inverse: 'fed_by',
    brick_class: 'https://brickschema.org/schema/Brick#feeds'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:RelationshipDef {
    name: 'located_in',
    label: 'Located In',
    description: 'Equipment is physically located in a space',
    inverse: 'contains',
    brick_class: 'https://brickschema.org/schema/Brick#hasLocation'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:RelationshipDef {
    name: 'monitors',
    label: 'Monitors',
    description: 'Sensor monitors equipment or zone',
    inverse: 'monitored_by',
    brick_class: 'https://brickschema.org/schema/Brick#hasPoint'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:RelationshipDef {
    name: 'controls',
    label: 'Controls',
    description: 'Controller controls equipment',
    inverse: 'controlled_by',
    brick_class: 'https://brickschema.org/schema/Brick#controls'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:RelationshipDef {
    name: 'part_of',
    label: 'Part Of',
    description: 'Equipment is part of a larger system',
    inverse: 'has_part',
    brick_class: 'https://brickschema.org/schema/Brick#isPartOf'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:RelationshipDef {
    name: 'connected_to',
    label: 'Connected To',
    description: 'Equipment is physically connected to another',
    inverse: 'connected_to',
    brick_class: 'https://brickschema.org/schema/Brick#connectedTo'
  }) RETURN n
$$) AS (n agtype);

SELECT * FROM cypher('platform', $$
  CREATE (n:RelationshipDef {
    name: 'adjacent_to',
    label: 'Adjacent To',
    description: 'Space is adjacent to another space',
    inverse: 'adjacent_to',
    brick_class: 'https://brickschema.org/schema/Brick#adjacentTo'
  }) RETURN n
$$) AS (n agtype);

-- =============================================================================
-- HAS_PROPERTY Edges (linking DeviceTypes to PropertyDefs)
-- =============================================================================

-- AHU Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'supply_air_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'return_air_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'mixed_air_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'outdoor_air_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'supply_air_temp_setpoint'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'duct_static_pressure'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'air_flow_rate'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'fan_speed'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'damper_position'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'on_off_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'fault_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'AHU'}), (p:PropertyDef {name: 'power_kw'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

-- VAV Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VAV'}), (p:PropertyDef {name: 'discharge_air_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VAV'}), (p:PropertyDef {name: 'zone_air_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VAV'}), (p:PropertyDef {name: 'zone_temp_setpoint'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VAV'}), (p:PropertyDef {name: 'air_flow_rate'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VAV'}), (p:PropertyDef {name: 'damper_position'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VAV'}), (p:PropertyDef {name: 'valve_position'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VAV'}), (p:PropertyDef {name: 'co2_level'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VAV'}), (p:PropertyDef {name: 'occupancy_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

-- Chiller Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'chilled_water_supply_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'chilled_water_return_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'chilled_water_temp_setpoint'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'condenser_water_supply_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'condenser_water_return_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'condenser_approach_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'evaporator_approach_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'power_kw'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'cop'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'thermal_power'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'on_off_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Chiller'}), (p:PropertyDef {name: 'fault_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

-- Boiler Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Boiler'}), (p:PropertyDef {name: 'hot_water_supply_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Boiler'}), (p:PropertyDef {name: 'hot_water_return_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Boiler'}), (p:PropertyDef {name: 'power_kw'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Boiler'}), (p:PropertyDef {name: 'on_off_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Boiler'}), (p:PropertyDef {name: 'fault_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

-- Pump Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Pump'}), (p:PropertyDef {name: 'pump_speed'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Pump'}), (p:PropertyDef {name: 'water_flow_rate'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Pump'}), (p:PropertyDef {name: 'differential_pressure'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Pump'}), (p:PropertyDef {name: 'power_kw'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Pump'}), (p:PropertyDef {name: 'on_off_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Pump'}), (p:PropertyDef {name: 'fault_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

-- Fan Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Fan'}), (p:PropertyDef {name: 'fan_speed'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Fan'}), (p:PropertyDef {name: 'air_flow_rate'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Fan'}), (p:PropertyDef {name: 'power_kw'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Fan'}), (p:PropertyDef {name: 'on_off_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

-- VFD Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VFD'}), (p:PropertyDef {name: 'fan_speed'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VFD'}), (p:PropertyDef {name: 'motor_current'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VFD'}), (p:PropertyDef {name: 'power_kw'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'VFD'}), (p:PropertyDef {name: 'vfd_fault_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

-- Meter Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'ElectricMeter'}), (p:PropertyDef {name: 'power_kw'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'ElectricMeter'}), (p:PropertyDef {name: 'energy_kwh'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'ElectricMeter'}), (p:PropertyDef {name: 'power_factor'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'BTUMeter'}), (p:PropertyDef {name: 'thermal_power'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

-- Thermostat Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Thermostat'}), (p:PropertyDef {name: 'zone_air_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Thermostat'}), (p:PropertyDef {name: 'zone_temp_setpoint'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Thermostat'}), (p:PropertyDef {name: 'relative_humidity'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'Thermostat'}), (p:PropertyDef {name: 'occupancy_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

-- Cooling Tower Properties
SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'CoolingTower'}), (p:PropertyDef {name: 'condenser_water_supply_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'CoolingTower'}), (p:PropertyDef {name: 'condenser_water_return_temp'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'CoolingTower'}), (p:PropertyDef {name: 'fan_speed'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'CoolingTower'}), (p:PropertyDef {name: 'power_kw'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);

SELECT * FROM cypher('platform', $$
  MATCH (dt:DeviceType {name: 'CoolingTower'}), (p:PropertyDef {name: 'on_off_status'})
  CREATE (dt)-[r:HAS_PROPERTY]->(p) RETURN r
$$) AS (r agtype);
