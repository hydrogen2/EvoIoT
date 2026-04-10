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
    tenant_id       TEXT NOT NULL,              -- '*' = global, or tenant identifier
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

-- Readings (unified time-series data)
CREATE TABLE evoiot.readings (
    id              UUID DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL,              -- tenant identifier
    source_type     TEXT NOT NULL,              -- 'sensor' | 'api' | 'mqtt' | 'file'
    rawtag_id       TEXT,                       -- computed from rawtag_id_template at ingestion
    point_type      TEXT NOT NULL,              -- ontology type or 'unclassified'
    value           DOUBLE PRECISION,
    unit            TEXT,
    raw_payload     JSONB,                      -- immutable original
    observed_at     TIMESTAMPTZ NOT NULL,
    confidence      DOUBLE PRECISION DEFAULT 1.0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, observed_at),
    CONSTRAINT valid_source_type CHECK (source_type IN ('sensor', 'api', 'mqtt', 'file', 'simulation'))
);

-- Convert readings to TimescaleDB hypertable
SELECT create_hypertable('evoiot.readings', 'observed_at');

-- Indexes
CREATE INDEX readings_tenant_time_idx
    ON evoiot.readings (tenant_id, observed_at DESC);

CREATE INDEX readings_rawtag_idx
    ON evoiot.readings (rawtag_id, observed_at DESC)
    WHERE rawtag_id IS NOT NULL;

CREATE INDEX readings_point_type_idx
    ON evoiot.readings (point_type, observed_at DESC);

-- =============================================================================
-- Row Level Security (RLS)
-- =============================================================================
ALTER TABLE evoiot.readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE evoiot.data_sources ENABLE ROW LEVEL SECURITY;

-- RLS Policies: readings
CREATE POLICY readings_select_policy ON evoiot.readings
    FOR SELECT
    USING (
        tenant_id = current_setting('request.jwt.claims', true)::json->>'tenant_id'
        OR tenant_id = '*'
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
        tenant_id = current_setting('request.jwt.claims', true)::json->>'tenant_id'
        OR tenant_id = '*'
        OR current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- =============================================================================
-- Role Permissions
-- =============================================================================

-- bento_writer: INSERT on readings, SELECT on tbox-related, AGE graph access
GRANT SELECT ON ALL TABLES IN SCHEMA evoiot TO bento_writer;
GRANT INSERT ON evoiot.readings TO bento_writer;
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
GRANT USAGE ON ALL SEQUENCES IN SCHEMA evoiot TO workflow_rw;

-- edge_insert: INSERT on readings only
GRANT INSERT ON evoiot.readings TO edge_insert;
GRANT SELECT ON evoiot.data_sources TO edge_insert;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA evoiot TO edge_insert;

-- ai_reader: SELECT all (scoped by RLS)
GRANT SELECT ON ALL TABLES IN SCHEMA evoiot TO ai_reader;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA evoiot TO ai_reader;

-- postgrest_role: SELECT/INSERT per RLS policy
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA evoiot TO postgrest_role;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA evoiot TO postgrest_role;

-- postgrest_anon: limited read access (RLS will filter results)
GRANT SELECT ON evoiot.readings TO postgrest_anon;
GRANT SELECT ON evoiot.data_sources TO postgrest_anon;

-- =============================================================================
-- Functions
-- =============================================================================

-- Function to get readings by ontology type with classification-on-read
CREATE OR REPLACE FUNCTION evoiot.get_readings_by_type(
    p_tbox_type TEXT,
    p_tenant_id TEXT DEFAULT null,
    p_start TIMESTAMPTZ DEFAULT now() - interval '1 hour',
    p_end TIMESTAMPTZ DEFAULT now()
) RETURNS jsonb AS $$
DECLARE
    v_tenant_id TEXT;
    v_has_classification BOOLEAN;
    v_rawtag_ids TEXT[];
    v_result jsonb;
    v_sql TEXT;
BEGIN
    -- Load AGE extension
    EXECUTE 'LOAD ''age''';
    EXECUTE 'SET search_path TO ag_catalog, evoiot, public';

    -- Use provided tenant_id or extract from JWT
    v_tenant_id := COALESCE(p_tenant_id,
        current_setting('request.jwt.claims', true)::json->>'tenant_id',
        'default');

    -- Check if any RawTag has approved IS_TYPE_OF edge to this type
    v_sql := format(
        $sql$SELECT EXISTS (
            SELECT 1 FROM ag_catalog.cypher('platform', $cypher$
                MATCH (r:RawTag)-[e:IS_TYPE_OF {status: 'approved'}]->(p:PropertyDef {name: %L})
                RETURN r.id LIMIT 1
            $cypher$) AS (id agtype)
        )$sql$,
        p_tbox_type
    );
    EXECUTE v_sql INTO v_has_classification;

    -- If no classification, trigger classifier workflow (async via pg_net)
    IF NOT v_has_classification THEN
        PERFORM net.http_post(
            url := 'http://restate:8080/classifier/' ||
                   encode(convert_to(v_tenant_id || ':' || p_tbox_type, 'UTF8'), 'base64') ||
                   '/run',
            body := jsonb_build_object(
                'tenant_id', v_tenant_id,
                'tbox_types', ARRAY[p_tbox_type]
            ),
            headers := '{"Content-Type": "application/json"}'::jsonb
        );

        RETURN jsonb_build_object(
            'status', 'classification_pending',
            'message', 'No approved classification found for ' || p_tbox_type || '. Classifier workflow triggered.',
            'tbox_type', p_tbox_type,
            'tenant_id', v_tenant_id,
            'data', '[]'::jsonb
        );
    END IF;

    -- Get RawTag IDs that are classified to this type
    v_sql := format(
        $sql$SELECT array_agg(id::text) FROM (
            SELECT id FROM ag_catalog.cypher('platform', $cypher$
                MATCH (r:RawTag)-[e:IS_TYPE_OF {status: 'approved'}]->(p:PropertyDef {name: %L})
                RETURN r.id AS id
            $cypher$) AS (id agtype)
        ) sub$sql$,
        p_tbox_type
    );
    EXECUTE v_sql INTO v_rawtag_ids;

    -- Query readings by rawtag_id (handle NULL/empty array)
    IF v_rawtag_ids IS NULL OR array_length(v_rawtag_ids, 1) IS NULL THEN
        v_rawtag_ids := ARRAY[]::TEXT[];
    END IF;

    SELECT jsonb_build_object(
        'status', 'ok',
        'tbox_type', p_tbox_type,
        'tenant_id', v_tenant_id,
        'rawtag_ids', to_jsonb(v_rawtag_ids),
        'data', COALESCE(
            (SELECT jsonb_agg(jsonb_build_object(
                'time', r.observed_at,
                'value', r.value,
                'unit', r.unit,
                'rawtag_id', r.rawtag_id,
                'confidence', r.confidence
            ) ORDER BY r.observed_at DESC)
            FROM evoiot.readings r
            WHERE r.rawtag_id = ANY(v_rawtag_ids)
              AND r.observed_at BETWEEN p_start AND p_end
            ),
            '[]'::jsonb
        )
    ) INTO v_result;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql VOLATILE SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION evoiot.get_readings_by_type TO postgrest_role, postgrest_anon, ai_reader, workflow_rw;

-- Function to compute rawtag_id from template and payload
-- Template uses {field_name} syntax, e.g., "{tenant_id}:{source_id}:{device_id}:{object_type}:{object_instance}"
CREATE OR REPLACE FUNCTION evoiot.compute_rawtag_id(
    p_template TEXT,
    p_payload JSONB
) RETURNS TEXT AS $$
DECLARE
    v_result TEXT;
    v_field TEXT;
    v_value TEXT;
BEGIN
    v_result := p_template;

    -- Replace each {field} with the corresponding value from payload
    FOR v_field IN SELECT (regexp_matches(p_template, '\{([^}]+)\}', 'g'))[1]
    LOOP
        v_value := p_payload ->> v_field;
        IF v_value IS NULL THEN
            v_value := '';
        END IF;
        v_result := regexp_replace(v_result, '\{' || v_field || '\}', v_value, 'g');
    END LOOP;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to get rawtag_id template from data_sources
-- Matches by tenant_id and source_type, falls back to global ('*')
CREATE OR REPLACE FUNCTION evoiot.get_rawtag_template(
    p_tenant_id TEXT,
    p_source_type TEXT
) RETURNS TEXT AS $$
DECLARE
    v_template TEXT;
BEGIN
    -- Try exact match first
    SELECT rawtag_id_template INTO v_template
    FROM evoiot.data_sources
    WHERE tenant_id = p_tenant_id
      AND source_type = p_source_type
      AND rawtag_id_template IS NOT NULL
      AND enabled = TRUE
    LIMIT 1;

    -- Fall back to global template
    IF v_template IS NULL THEN
        SELECT rawtag_id_template INTO v_template
        FROM evoiot.data_sources
        WHERE tenant_id = '*'
          AND source_type = p_source_type
          AND rawtag_id_template IS NOT NULL
          AND enabled = TRUE
        LIMIT 1;
    END IF;

    -- Default template for BACnet if nothing found
    IF v_template IS NULL AND p_source_type = 'bacnet' THEN
        v_template := '{tenant_id}:{source_id}:{device_id}:{object_type}:{object_instance}';
    END IF;

    RETURN v_template;
END;
$$ LANGUAGE plpgsql STABLE;

-- Trigger function to compute rawtag_id on readings INSERT
CREATE OR REPLACE FUNCTION evoiot.compute_rawtag_id_trigger() RETURNS TRIGGER AS $$
DECLARE
    v_template TEXT;
    v_payload JSONB;
    v_protocol TEXT;
BEGIN
    -- Only compute if rawtag_id is not already set
    IF NEW.rawtag_id IS NULL AND NEW.raw_payload IS NOT NULL THEN
        -- Parse raw_payload
        IF jsonb_typeof(NEW.raw_payload) = 'string' THEN
            BEGIN
                v_payload := (NEW.raw_payload #>> '{}')::jsonb;
            EXCEPTION WHEN OTHERS THEN
                v_payload := NEW.raw_payload;
            END;
        ELSE
            v_payload := NEW.raw_payload;
        END IF;

        -- Determine protocol from raw_payload indicators
        -- BACnet: has object_type like 'analog-input', 'analog-output', etc.
        IF v_payload ? 'object_type' AND (v_payload->>'object_type') LIKE '%-%' THEN
            v_protocol := 'bacnet';
        ELSE
            v_protocol := 'bacnet';  -- Default to bacnet for now
        END IF;

        -- Get template based on tenant_id and detected protocol
        v_template := evoiot.get_rawtag_template(NEW.tenant_id, v_protocol);

        IF v_template IS NOT NULL THEN
            -- Add source_id from agent_id if present
            IF v_payload ? 'agent_id' THEN
                v_payload := v_payload || jsonb_build_object('source_id', v_payload->>'agent_id');
            END IF;

            -- Add tenant_id to payload for template resolution
            v_payload := v_payload || jsonb_build_object(
                'tenant_id', NEW.tenant_id
            );

            NEW.rawtag_id := evoiot.compute_rawtag_id(v_template, v_payload);
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger on readings table
DROP TRIGGER IF EXISTS compute_rawtag_id_on_insert ON evoiot.readings;
CREATE TRIGGER compute_rawtag_id_on_insert
    BEFORE INSERT ON evoiot.readings
    FOR EACH ROW
    EXECUTE FUNCTION evoiot.compute_rawtag_id_trigger();

-- Unified function to create or update a RawTag node in the graph
-- Computes rawtag_id from externalized template in data_sources
-- Handles both telemetry and discovery use cases
CREATE OR REPLACE FUNCTION evoiot.upsert_rawtag(
    p_tenant_id TEXT,
    p_source_id TEXT,
    p_device_id TEXT,
    p_object_type TEXT DEFAULT NULL,
    p_object_instance TEXT DEFAULT NULL,
    p_protocol TEXT DEFAULT 'bacnet',
    p_tag_type TEXT DEFAULT 'object',      -- 'device' or 'object'
    p_raw_data TEXT DEFAULT NULL,
    p_discovered_at TEXT DEFAULT NULL,
    p_last_seen_by TEXT DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE
    v_template TEXT;
    v_payload JSONB;
    v_rawtag_id TEXT;
BEGIN
    -- Load AGE extension
    EXECUTE 'LOAD ''age''';
    EXECUTE 'SET search_path TO ag_catalog, evoiot, public';

    -- Compute rawtag_id based on tag type
    IF p_tag_type = 'device' THEN
        v_rawtag_id := p_tenant_id || ':' || p_source_id || ':' || p_device_id;
    ELSE
        -- Object tags: use template from data_sources
        v_template := evoiot.get_rawtag_template(p_tenant_id, p_protocol);
        IF v_template IS NOT NULL THEN
            v_payload := jsonb_build_object(
                'tenant_id', p_tenant_id,
                'source_id', p_source_id,
                'device_id', p_device_id,
                'object_type', COALESCE(p_object_type, ''),
                'object_instance', COALESCE(p_object_instance, '')
            );
            v_rawtag_id := evoiot.compute_rawtag_id(v_template, v_payload);
        ELSE
            -- Fallback to default format
            v_rawtag_id := p_tenant_id || ':' || p_source_id || ':' || p_device_id || ':' || COALESCE(p_object_type, '') || ':' || COALESCE(p_object_instance, '');
        END IF;
    END IF;

    -- MERGE creates if not exists, updates if exists (use EXECUTE for cypher)
    -- Use CASE to preserve existing non-empty values for raw_data, discovered_at, last_seen_by
    EXECUTE format($sql$
        SELECT * FROM ag_catalog.cypher('platform', $cypher$
            MERGE (r:RawTag {id: %L})
            SET r.building_id = %L,
                r.source_id = %L,
                r.device_id = %L,
                r.object_type = %L,
                r.object_instance = %L,
                r.protocol = %L,
                r.tag_type = %L,
                r.raw_data = CASE WHEN %L <> '' THEN %L ELSE COALESCE(r.raw_data, '') END,
                r.discovered_at = CASE WHEN %L <> '' THEN %L ELSE COALESCE(r.discovered_at, '') END,
                r.last_seen_by = CASE WHEN %L <> '' THEN %L ELSE COALESCE(r.last_seen_by, '') END,
                r.updated_at = %L
        $cypher$) AS (r agtype)
    $sql$,
        v_rawtag_id,
        p_tenant_id,
        p_source_id,
        p_device_id,
        COALESCE(p_object_type, ''),
        COALESCE(p_object_instance, ''),
        p_protocol,
        p_tag_type,
        COALESCE(p_raw_data, ''), COALESCE(p_raw_data, ''),
        COALESCE(p_discovered_at, ''), COALESCE(p_discovered_at, ''),
        COALESCE(p_last_seen_by, ''), COALESCE(p_last_seen_by, ''),
        extract(epoch from now())::bigint * 1000
    );

    -- Emit provenance event for graph mutation
    INSERT INTO evoiot.events (component, operation, data_id, actor, payload)
    VALUES (
        'graph',
        'upsert_rawtag',
        v_rawtag_id,
        current_user,
        jsonb_build_object(
            'tenant_id', p_tenant_id,
            'source_id', p_source_id,
            'device_id', p_device_id,
            'object_type', p_object_type,
            'object_instance', p_object_instance,
            'tag_type', p_tag_type,
            'raw_data', p_raw_data
        )
    );

    RETURN v_rawtag_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION evoiot.compute_rawtag_id TO bento_writer, workflow_rw, postgrest_anon;
GRANT EXECUTE ON FUNCTION evoiot.get_rawtag_template TO bento_writer, workflow_rw, postgrest_anon;
GRANT EXECUTE ON FUNCTION evoiot.upsert_rawtag TO bento_writer, workflow_rw;

-- =============================================================================
-- Unified Events Table (provenance / logging / audit)
-- =============================================================================
CREATE TABLE evoiot.events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY,
    event_time  TIMESTAMPTZ NOT NULL DEFAULT now(),  -- when the event actually happened
    component   TEXT NOT NULL,              -- bento, restate.classifier, postgres, graph
    operation   TEXT NOT NULL,              -- input_mqtt, sql_insert, classify, human_approve
    data_id     TEXT,                       -- rawtag_id or reading.id (NULL = pure ops log)
    trace_id    TEXT,                       -- request-level correlation
    actor       TEXT,                       -- bento, doubao-v3, user@company.com
    payload     JSONB,                      -- context, flexible per operation
    PRIMARY KEY (id)
);

-- Indexes for different query patterns
CREATE INDEX events_data_id_idx ON evoiot.events (data_id, event_time) WHERE data_id IS NOT NULL;
CREATE INDEX events_component_idx ON evoiot.events (component, event_time);
CREATE INDEX events_actor_idx ON evoiot.events (actor, event_time) WHERE actor IS NOT NULL;
CREATE INDEX events_trace_id_idx ON evoiot.events (trace_id, event_time) WHERE trace_id IS NOT NULL;

-- Append-only: grant INSERT only, explicitly revoke UPDATE/DELETE
GRANT INSERT ON evoiot.events TO bento_writer, workflow_rw, postgrest_role;
GRANT SELECT ON evoiot.events TO bento_writer, workflow_rw, postgrest_role, postgrest_anon, ai_reader;
GRANT USAGE ON SEQUENCE evoiot.events_id_seq TO bento_writer, workflow_rw, postgrest_role;
REVOKE UPDATE, DELETE ON evoiot.events FROM bento_writer, workflow_rw, postgrest_role;

-- Anonymous read access for development
CREATE POLICY events_anon_select ON evoiot.events
    FOR SELECT TO postgrest_anon USING (true);

-- Trigger function to emit events on relational table changes
-- Uses to_jsonb(NEW) to extract data_id dynamically, handling tables with/without rawtag_id
CREATE OR REPLACE FUNCTION evoiot.emit_event() RETURNS trigger AS $$
DECLARE
    v_new JSONB;
    v_data_id TEXT;
BEGIN
    v_new := to_jsonb(NEW);
    v_data_id := COALESCE(v_new->>'rawtag_id', v_new->>'id');

    INSERT INTO evoiot.events (component, operation, data_id, actor, payload)
    VALUES (
        'postgres',
        TG_OP,
        v_data_id,
        current_user,
        jsonb_build_object('table', TG_TABLE_NAME, 'new', v_new)
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach triggers to relational tables
CREATE TRIGGER emit_event_on_change
    AFTER INSERT OR UPDATE ON evoiot.readings
    FOR EACH ROW EXECUTE FUNCTION evoiot.emit_event();

CREATE TRIGGER emit_event_on_change
    AFTER INSERT OR UPDATE ON evoiot.data_sources
    FOR EACH ROW EXECUTE FUNCTION evoiot.emit_event();

-- =============================================================================
-- Seed Data Sources with RawTag ID Templates
-- =============================================================================
-- Global BACnet template - used as fallback for all tenants
INSERT INTO evoiot.data_sources (tenant_id, name, source_type, rawtag_id_template, registered_by, classification)
VALUES ('*', 'BACnet Default', 'bacnet', '{tenant_id}:{source_id}:{device_id}:{object_type}:{object_instance}', 'platform', 'classified');

-- =============================================================================
-- PostgREST Schema Cache Reload
-- =============================================================================
-- Notify PostgREST to reload schema cache (useful when re-running this script)
NOTIFY pgrst, 'reload schema';
