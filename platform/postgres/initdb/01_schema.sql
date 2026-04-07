-- EvoIoT Platform Schema
-- Step 1: Full DDL - tables, hypertable, indexes, RLS, roles, AGE graph

-- =============================================================================
-- Extensions
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS pg_net;
LOAD 'age';

-- =============================================================================
-- Postgres Roles
-- =============================================================================
-- Service account roles (passwords set via environment in production)
CREATE ROLE bento_writer WITH LOGIN PASSWORD 'bento_dev_password';
CREATE ROLE workflow_rw WITH LOGIN PASSWORD 'workflow_dev_password';
CREATE ROLE edge_insert WITH LOGIN PASSWORD 'edge_dev_password';
CREATE ROLE ai_reader WITH LOGIN PASSWORD 'ai_dev_password';
CREATE ROLE postgrest_role WITH LOGIN PASSWORD 'postgrest_dev_password';
CREATE ROLE postgrest_anon NOLOGIN;

-- Grant postgrest_anon to postgrest_role for role switching
GRANT postgrest_anon TO postgrest_role;

-- =============================================================================
-- Schema Setup
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS evoiot;
SET search_path TO evoiot, ag_catalog, public;

-- Grant schema usage
GRANT USAGE ON SCHEMA evoiot TO bento_writer, workflow_rw, edge_insert, ai_reader, postgrest_role, postgrest_anon;

-- =============================================================================
-- Apache AGE Graph
-- =============================================================================
SELECT ag_catalog.create_graph('platform');

-- =============================================================================
-- Core Tables
-- =============================================================================

-- Data Sources Registry
CREATE TABLE evoiot.data_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id     TEXT NOT NULL,              -- '*' or specific uuid
    name            TEXT NOT NULL,
    source_type     TEXT NOT NULL,              -- 'mqtt' | 'http_poll' | 'webhook' | 'file' | 'bacnet' | 'modbus'
    config          JSONB,                      -- connection config (url, interval, headers)
    transform       TEXT,                       -- Bloblang to normalise raw payload
    rawtag_id_template TEXT,                    -- Bloblang to derive RawTag ID from raw_payload
    enabled         BOOLEAN DEFAULT TRUE,
    registered_by   TEXT NOT NULL,              -- 'platform' | 'user' | 'ai'
    classification  TEXT DEFAULT 'pending',     -- 'classified' | 'pending' | 'rejected'
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_source_type CHECK (source_type IN ('mqtt', 'http_poll', 'webhook', 'file', 'bacnet', 'modbus')),
    CONSTRAINT valid_registered_by CHECK (registered_by IN ('platform', 'user', 'ai')),
    CONSTRAINT valid_classification CHECK (classification IN ('classified', 'pending', 'rejected'))
);

-- Readings (unified sensor + context data)
CREATE TABLE evoiot.readings (
    id              UUID DEFAULT gen_random_uuid(),
    building_id     TEXT NOT NULL,              -- uuid or '*'
    source_id       UUID REFERENCES evoiot.data_sources(id),
    source_type     TEXT NOT NULL,              -- 'sensor' | 'api' | 'mqtt' | 'file'
    scope           TEXT NOT NULL,              -- 'device' | 'building' | 'global'
    device_id       TEXT,                       -- null for non-sensor sources
    rawtag_id       TEXT,                       -- computed from rawtag_id_template at ingestion
    point_type      TEXT NOT NULL,              -- TBox type or 'unclassified'
    value           DOUBLE PRECISION,
    unit            TEXT,
    raw_payload     JSONB,                      -- immutable original
    agent_read_at   TIMESTAMPTZ NOT NULL,
    confidence      DOUBLE PRECISION DEFAULT 1.0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, agent_read_at),
    CONSTRAINT valid_source_type CHECK (source_type IN ('sensor', 'api', 'mqtt', 'file', 'simulation')),
    CONSTRAINT valid_scope CHECK (scope IN ('device', 'building', 'global'))
);

-- Convert readings to TimescaleDB hypertable
SELECT create_hypertable('evoiot.readings', 'agent_read_at');

-- Partial indexes for efficient queries
CREATE INDEX readings_device_idx
    ON evoiot.readings (device_id, point_type, agent_read_at DESC)
    WHERE device_id IS NOT NULL;

CREATE INDEX readings_context_idx
    ON evoiot.readings (building_id, point_type, agent_read_at DESC)
    WHERE device_id IS NULL;

CREATE INDEX readings_building_time_idx
    ON evoiot.readings (building_id, agent_read_at DESC);

CREATE INDEX readings_rawtag_idx
    ON evoiot.readings (rawtag_id, agent_read_at DESC)
    WHERE rawtag_id IS NOT NULL;

-- Read Lens Configuration
CREATE TABLE evoiot.read_lens_config (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id       TEXT,
    point_type      TEXT NOT NULL,
    drift_offset    DOUBLE PRECISION DEFAULT 0,
    confidence_factor DOUBLE PRECISION DEFAULT 1.0,
    gap_fill_method TEXT DEFAULT 'interpolate',  -- 'interpolate' | 'locf' | 'null'
    valid_from      TIMESTAMPTZ DEFAULT NOW(),
    valid_to        TIMESTAMPTZ,                  -- null = currently active
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_gap_fill CHECK (gap_fill_method IN ('interpolate', 'locf', 'null'))
);

CREATE INDEX read_lens_config_lookup_idx
    ON evoiot.read_lens_config (device_id, point_type, valid_from DESC);

-- Rules
CREATE TABLE evoiot.rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id     TEXT NOT NULL,              -- '*' = all buildings, uuid = one building
    source          TEXT NOT NULL,              -- 'platform' | 'user'
    name            TEXT NOT NULL,
    description     TEXT,
    point_type      TEXT NOT NULL,              -- TBox property type
    condition       TEXT NOT NULL,              -- "value > threshold"
    threshold       DOUBLE PRECISION,
    severity        TEXT NOT NULL,              -- 'P1' | 'P2' | 'P3'
    device_id       TEXT NOT NULL,              -- '*' = all devices, uuid = one device
    notify_user_ids UUID[],
    enabled         BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_source CHECK (source IN ('platform', 'user')),
    CONSTRAINT valid_severity CHECK (severity IN ('P1', 'P2', 'P3'))
);

CREATE INDEX rules_evaluation_idx
    ON evoiot.rules (building_id, point_type, enabled)
    WHERE enabled = TRUE;

-- Alerts (generated by rules engine)
CREATE TABLE evoiot.alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id     TEXT NOT NULL,
    rule_id         UUID REFERENCES evoiot.rules(id),
    device_id       UUID,
    point_type      TEXT NOT NULL,
    value           DOUBLE PRECISION,
    threshold       DOUBLE PRECISION,
    severity        TEXT NOT NULL,
    status          TEXT DEFAULT 'open',        -- 'open' | 'acknowledged' | 'resolved'
    acknowledged_by UUID,
    acknowledged_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_severity CHECK (severity IN ('P1', 'P2', 'P3')),
    CONSTRAINT valid_status CHECK (status IN ('open', 'acknowledged', 'resolved'))
);

CREATE INDEX alerts_building_status_idx
    ON evoiot.alerts (building_id, status, created_at DESC);

-- Classification Proposals (AI-generated)
CREATE TABLE evoiot.classification_proposals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID REFERENCES evoiot.data_sources(id),
    device_id       UUID,
    raw_name        TEXT,
    proposed_type   TEXT NOT NULL,              -- proposed TBox type
    confidence      DOUBLE PRECISION,
    reasoning       TEXT,
    status          TEXT DEFAULT 'pending',     -- 'pending' | 'approved' | 'rejected'
    reviewed_by     UUID,
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_status CHECK (status IN ('pending', 'approved', 'rejected'))
);

CREATE INDEX classification_proposals_status_idx
    ON evoiot.classification_proposals (status, created_at DESC);

-- Workflow Templates
CREATE TABLE evoiot.workflow_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    handler_name    TEXT NOT NULL,              -- Restate handler name
    parameters      JSONB,                      -- schema for configurable params
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Workflow Configurations (operator-configured instances)
CREATE TABLE evoiot.workflow_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id     TEXT NOT NULL,
    template_id     UUID REFERENCES evoiot.workflow_templates(id),
    name            TEXT NOT NULL,
    config          JSONB NOT NULL,             -- assignee_role, approver_role, sla_hours, etc.
    trigger_conditions JSONB,                   -- when to auto-trigger
    enabled         BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX workflow_configs_building_idx
    ON evoiot.workflow_configs (building_id, enabled);

-- Audit Log (append-only with hash chain)
CREATE TABLE evoiot.audit_log (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ DEFAULT NOW(),
    actor_id        UUID,
    actor_type      TEXT,                       -- 'user' | 'service' | 'system'
    action          TEXT NOT NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT,
    details         JSONB,
    security        BOOLEAN DEFAULT FALSE,      -- true for security-sensitive events
    previous_hash   TEXT,
    hash            TEXT NOT NULL
);

CREATE INDEX audit_log_timestamp_idx ON evoiot.audit_log (timestamp DESC);
CREATE INDEX audit_log_security_idx ON evoiot.audit_log (timestamp DESC) WHERE security = TRUE;
CREATE INDEX audit_log_resource_idx ON evoiot.audit_log (resource_type, resource_id, timestamp DESC);

-- =============================================================================
-- Row Level Security (RLS)
-- =============================================================================
ALTER TABLE evoiot.readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE evoiot.data_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE evoiot.rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE evoiot.alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE evoiot.classification_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE evoiot.workflow_configs ENABLE ROW LEVEL SECURITY;

-- RLS Policies: readings
CREATE POLICY readings_select_policy ON evoiot.readings
    FOR SELECT
    USING (
        building_id = current_setting('request.jwt.claims', true)::json->>'building_id'
        OR building_id = '*'
        OR current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

CREATE POLICY readings_insert_policy ON evoiot.readings
    FOR INSERT
    WITH CHECK (TRUE);  -- Services handle insert validation

-- Anonymous access for development (remove in production)
CREATE POLICY readings_anon_select ON evoiot.readings
    FOR SELECT
    TO postgrest_anon
    USING (true);

-- RLS Policies: data_sources
CREATE POLICY data_sources_select_policy ON evoiot.data_sources
    FOR SELECT
    USING (
        building_id = current_setting('request.jwt.claims', true)::json->>'building_id'
        OR building_id = '*'
        OR current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- RLS Policies: rules (platform rules are read-only for users)
CREATE POLICY rules_select_policy ON evoiot.rules
    FOR SELECT
    USING (
        building_id = current_setting('request.jwt.claims', true)::json->>'building_id'
        OR building_id = '*'
        OR current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

CREATE POLICY rules_insert_policy ON evoiot.rules
    FOR INSERT
    WITH CHECK (
        source = 'user'
        AND building_id = current_setting('request.jwt.claims', true)::json->>'building_id'
    );

CREATE POLICY rules_update_policy ON evoiot.rules
    FOR UPDATE
    USING (
        source = 'user'
        AND building_id = current_setting('request.jwt.claims', true)::json->>'building_id'
    );

-- RLS Policies: alerts
CREATE POLICY alerts_select_policy ON evoiot.alerts
    FOR SELECT
    USING (
        building_id = current_setting('request.jwt.claims', true)::json->>'building_id'
        OR current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- RLS Policies: classification_proposals
CREATE POLICY classification_proposals_select_policy ON evoiot.classification_proposals
    FOR SELECT
    USING (TRUE);  -- Admins only in production (simplified for dev)

-- RLS Policies: workflow_configs
CREATE POLICY workflow_configs_select_policy ON evoiot.workflow_configs
    FOR SELECT
    USING (
        building_id = current_setting('request.jwt.claims', true)::json->>'building_id'
        OR current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- =============================================================================
-- Role Permissions
-- =============================================================================

-- bento_writer: INSERT on readings, SELECT on tbox-related, AGE graph access
GRANT SELECT ON ALL TABLES IN SCHEMA evoiot TO bento_writer;
GRANT INSERT ON evoiot.readings TO bento_writer;
GRANT INSERT ON evoiot.alerts TO bento_writer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA evoiot TO bento_writer;
-- AGE catalog access
GRANT USAGE ON SCHEMA ag_catalog TO bento_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA ag_catalog TO bento_writer;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ag_catalog TO bento_writer;
-- AGE graph schema access (platform graph)
GRANT ALL ON SCHEMA platform TO bento_writer;
GRANT ALL ON ALL TABLES IN SCHEMA platform TO bento_writer;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA platform TO bento_writer;

-- workflow_rw: SELECT on readings + tbox (for validation)
GRANT SELECT ON ALL TABLES IN SCHEMA evoiot TO workflow_rw;
GRANT INSERT, UPDATE ON evoiot.alerts TO workflow_rw;
GRANT INSERT ON evoiot.audit_log TO workflow_rw;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA evoiot TO workflow_rw;

-- edge_insert: INSERT on readings only
GRANT INSERT ON evoiot.readings TO edge_insert;
GRANT SELECT ON evoiot.data_sources TO edge_insert;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA evoiot TO edge_insert;

-- ai_reader: SELECT all (scoped by RLS)
GRANT SELECT ON ALL TABLES IN SCHEMA evoiot TO ai_reader;
GRANT INSERT ON evoiot.classification_proposals TO ai_reader;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA evoiot TO ai_reader;

-- postgrest_role: SELECT/INSERT per RLS policy
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA evoiot TO postgrest_role;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA evoiot TO postgrest_role;

-- postgrest_anon: limited read access (RLS will filter results)
GRANT SELECT ON evoiot.workflow_templates TO postgrest_anon;
GRANT SELECT ON evoiot.readings TO postgrest_anon;
GRANT SELECT ON evoiot.rules TO postgrest_anon;
GRANT SELECT ON evoiot.alerts TO postgrest_anon;
GRANT SELECT ON evoiot.data_sources TO postgrest_anon;

-- Audit log: INSERT only (no UPDATE/DELETE for tamper resistance)
REVOKE UPDATE, DELETE ON evoiot.audit_log FROM PUBLIC;
REVOKE UPDATE, DELETE ON evoiot.audit_log FROM bento_writer, workflow_rw, edge_insert, ai_reader, postgrest_role;

-- =============================================================================
-- Functions
-- =============================================================================

-- Function to get readings with lens applied (gap fill, drift correction)
CREATE OR REPLACE FUNCTION evoiot.get_readings_with_lens(
    p_device_id UUID,
    p_point_type TEXT,
    p_start TIMESTAMPTZ,
    p_end TIMESTAMPTZ,
    p_interval INTERVAL DEFAULT '5 minutes'
)
RETURNS TABLE (
    bucket TIMESTAMPTZ,
    value DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    is_interpolated BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        time_bucket_gapfill(p_interval, r.agent_read_at) AS bucket,
        interpolate(avg(r.value)) + COALESCE(lc.drift_offset, 0) AS value,
        CASE
            WHEN avg(r.value) IS NULL THEN 0.5
            ELSE COALESCE(lc.confidence_factor, 1.0)
        END AS confidence,
        avg(r.value) IS NULL AS is_interpolated
    FROM evoiot.readings r
    LEFT JOIN evoiot.read_lens_config lc
        ON lc.device_id = r.device_id
        AND lc.point_type = r.point_type
        AND lc.valid_from <= r.agent_read_at
        AND (lc.valid_to IS NULL OR lc.valid_to > r.agent_read_at)
    WHERE r.device_id = p_device_id
        AND r.point_type = p_point_type
        AND r.agent_read_at BETWEEN p_start AND p_end
    GROUP BY time_bucket_gapfill(p_interval, r.agent_read_at), lc.drift_offset, lc.confidence_factor
    ORDER BY bucket;
END;
$$ LANGUAGE plpgsql STABLE;

-- Grant execute on functions
GRANT EXECUTE ON FUNCTION evoiot.get_readings_with_lens TO postgrest_role, ai_reader, workflow_rw;

-- Function to get readings by TBox type with classification-on-read
CREATE OR REPLACE FUNCTION evoiot.get_readings_by_type(
    p_tbox_type TEXT,
    p_start TIMESTAMPTZ DEFAULT now() - interval '1 hour',
    p_end TIMESTAMPTZ DEFAULT now()
) RETURNS jsonb AS $$
DECLARE
    v_building_id TEXT;
    v_has_classification BOOLEAN;
    v_rawtag_ids TEXT[];
    v_result jsonb;
    v_sql TEXT;
BEGIN
    -- Load AGE extension
    EXECUTE 'LOAD ''age''';
    EXECUTE 'SET search_path TO ag_catalog, evoiot, public';

    -- For dev/testing: hardcode building_id (Step 7 will use JWT claims)
    -- v_building_id := current_setting('request.jwt.claims', true)::jsonb->>'building_id';
    v_building_id := 'bldg-001';

    -- Check if any RawTag has approved IS_TYPE_OF edge to this TBox type
    -- Use EXECUTE for dynamic cypher query (cypher() requires literal string)
    v_sql := format(
        $sql$SELECT EXISTS (
            SELECT 1 FROM ag_catalog.cypher('platform', $cypher$
                MATCH (r:RawTag {building_id: %L})-[e:IS_TYPE_OF {status: 'approved'}]->(p:PropertyDef {name: %L})
                RETURN r.id LIMIT 1
            $cypher$) AS (id agtype)
        )$sql$,
        v_building_id, p_tbox_type
    );
    EXECUTE v_sql INTO v_has_classification;

    -- If no classification, trigger classifier workflow (async via pg_net)
    IF NOT v_has_classification THEN
        PERFORM net.http_post(
            url := 'http://restate:8080/classifier/' ||
                   encode(convert_to(v_building_id || ':' || p_tbox_type, 'UTF8'), 'base64') ||
                   '/run',
            body := jsonb_build_object(
                'building_id', v_building_id,
                'tbox_types', ARRAY[p_tbox_type]
            ),
            headers := '{"Content-Type": "application/json"}'::jsonb
        );

        RETURN jsonb_build_object(
            'status', 'classification_pending',
            'message', 'No approved classification found for ' || p_tbox_type || '. Classifier workflow triggered.',
            'tbox_type', p_tbox_type,
            'building_id', v_building_id,
            'data', '[]'::jsonb
        );
    END IF;

    -- Get RawTag IDs that are classified to this TBox type
    v_sql := format(
        $sql$SELECT array_agg(r_id) FROM (
            SELECT (id #>> '{}')::TEXT AS r_id
            FROM ag_catalog.cypher('platform', $cypher$
                MATCH (r:RawTag {building_id: %L})-[e:IS_TYPE_OF {status: 'approved'}]->(p:PropertyDef {name: %L})
                RETURN r.id AS id
            $cypher$) AS (id agtype)
        ) sub$sql$,
        v_building_id, p_tbox_type
    );
    EXECUTE v_sql INTO v_rawtag_ids;

    -- Query readings by rawtag_id
    SELECT jsonb_build_object(
        'status', 'ok',
        'tbox_type', p_tbox_type,
        'building_id', v_building_id,
        'rawtag_ids', to_jsonb(v_rawtag_ids),
        'data', COALESCE(
            (SELECT jsonb_agg(jsonb_build_object(
                'time', r.agent_read_at,
                'value', r.value,
                'unit', r.unit,
                'rawtag_id', r.rawtag_id,
                'confidence', r.confidence
            ) ORDER BY r.agent_read_at DESC)
            FROM evoiot.readings r
            WHERE r.rawtag_id = ANY(v_rawtag_ids)
              AND r.agent_read_at BETWEEN p_start AND p_end
            ),
            '[]'::jsonb
        )
    ) INTO v_result;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql VOLATILE SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION evoiot.get_readings_by_type TO postgrest_role, postgrest_anon, ai_reader, workflow_rw;

-- Function to create or update a RawTag node in the graph
-- Called during telemetry ingestion to ensure RawTag exists
CREATE OR REPLACE FUNCTION evoiot.upsert_rawtag(
    p_rawtag_id TEXT,
    p_building_id TEXT,
    p_device_id TEXT,
    p_object_type TEXT,
    p_object_instance TEXT,
    p_object_name TEXT DEFAULT NULL
) RETURNS void AS $$
BEGIN
    -- MERGE creates if not exists, updates if exists
    PERFORM ag_catalog.cypher('platform', format($cypher$
        MERGE (r:RawTag {id: %L})
        SET r.building_id = %L,
            r.device_id = %L,
            r.object_type = %L,
            r.object_instance = %L,
            r.object_name = %L,
            r.updated_at = %L
    $cypher$,
        p_rawtag_id,
        p_building_id,
        p_device_id,
        p_object_type,
        p_object_instance,
        COALESCE(p_object_name, ''),
        extract(epoch from now())::bigint * 1000
    ));
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION evoiot.upsert_rawtag TO bento_writer, workflow_rw;

-- =============================================================================
-- Seed Workflow Templates (platform defaults)
-- =============================================================================
INSERT INTO evoiot.workflow_templates (name, handler_name, description, parameters) VALUES
    ('command_dispatch', 'CommandDispatch', 'Send command to device and await acknowledgement',
     '{"device_id": "uuid", "command": "string", "value": "any", "timeout_seconds": "number"}'),
    ('device_onboarding', 'DeviceOnboarding', 'Onboard a new device with AI classification',
     '{"source_id": "uuid"}'),
    ('alert_lifecycle', 'AlertLifecycle', 'Manage alert from creation to resolution',
     '{"alert_id": "uuid", "assignee_role": "string", "escalation_minutes": "number"}'),
    ('maintenance_task', 'MaintenanceTask', 'Create and track maintenance work order',
     '{"assignee_role": "string", "approver_role": "string", "sla_hours": "number"}'),
    ('repair_order', 'RepairOrder', 'External repair order workflow',
     '{"vendor": "string", "priority": "string", "budget_limit": "number"}'),
    ('inspection_round', 'InspectionRound', 'Scheduled inspection checklist workflow',
     '{"checklist_id": "uuid", "assignee_role": "string", "frequency": "string"}');

-- =============================================================================
-- PostgREST Schema Cache Reload
-- =============================================================================
-- Notify PostgREST to reload schema cache (useful when re-running this script)
NOTIFY pgrst, 'reload schema';
