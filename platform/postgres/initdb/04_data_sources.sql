-- EvoIoT Platform Default Data Sources
-- registered_by: 'platform' - shipped defaults

SET search_path TO evoiot, public;

INSERT INTO evoiot.data_sources (building_id, name, source_type, config, transform, registered_by, classification) VALUES
-- Edge Agent MQTT (default for all buildings)
('*', 'edge_agent_mqtt', 'mqtt',
 '{"topic_pattern": "buildings/+/agents/+/telemetry", "qos": 1}',
 NULL,  -- No transform needed, edge agent sends normalized format
 'platform', 'classified'),

-- Edge Agent Discovery (default for all buildings)
('*', 'edge_agent_discovery', 'mqtt',
 '{"topic_pattern": "buildings/+/agents/+/discovery", "qos": 1, "retained": true}',
 NULL,
 'platform', 'classified'),

-- Edge Agent Command Acknowledgements
('*', 'edge_agent_command_ack', 'mqtt',
 '{"topic_pattern": "buildings/+/agents/+/commands/ack", "qos": 1}',
 NULL,
 'platform', 'classified'),

-- Weather API (OpenWeatherMap template)
('*', 'weather_openweathermap', 'http_poll',
 '{"url_template": "https://api.openweathermap.org/data/2.5/weather?lat=${lat}&lon=${lon}&appid=${api_key}&units=metric", "interval_seconds": 900, "headers": {}}',
 'root.point_type = "outdoor_temperature"; root.value = this.main.temp; root.unit = "celsius"; root.scope = "building"',
 'platform', 'classified'),

-- Electricity Rate API (template - requires configuration)
('*', 'electricity_rates', 'http_poll',
 '{"url_template": "https://api.example.com/rates?region=${region}", "interval_seconds": 3600, "headers": {}}',
 'root.point_type = "electricity_rate"; root.value = this.rate; root.unit = "currency_per_kwh"; root.scope = "global"',
 'platform', 'pending'),

-- Building Occupancy API (template)
('*', 'building_occupancy', 'http_poll',
 '{"url_template": "https://api.example.com/occupancy?building=${building_id}", "interval_seconds": 300, "headers": {}}',
 'root.point_type = "occupancy_count"; root.value = this.count; root.unit = "people"; root.scope = "building"',
 'platform', 'pending');
