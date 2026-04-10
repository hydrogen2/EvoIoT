# IoT Platform Architecture

## Overview

A small, beautiful, AI-first platform for real-time data and problem-solving. Built from open source components assembled and configured rather than coded. The philosophy throughout: store everything raw, decide meaning later, let AI discover what matters, generate functionality on demand.

The architecture is **domain-agnostic** — a generic data↔AI platform. The v1 instantiation is building monitoring (BACnet/IoT), but the same patterns apply to any domain with real-time data, user questions, and AI-assisted reasoning.

**Question-first, not data-first:**

```
Traditional IoT:                  This platform:
────────────────                  ──────────────
Data sources → Schema → Apps      User asks questions (AI-guided)
                                         ↓
"Here's what we have,             TBox grows to match intent
 figure out what to do"                  ↓
                                  Data gaps identified
                                         ↓
                                  Fetch → Classify → Enable

                                  "What do you want to know?
                                   We'll figure out how to answer it."
```

The platform is:
- **Question-first** — start with what you want to know, not what data exists
- **AI-guided** — domain knowledge helps users ask the right questions
- **Data fetcher** — acquires data needed to answer questions
- **Classifier** — maps raw data to semantic meaning (TBox)
- **Usage enabler** — wires answers into dashboards, rules, control

Minimal seed apps + minimal seed TBox. Users grow the system by asking questions.

**Target scenario (v1):** BACnet buildings, single-building monitor app, one customer deployment.

---

## Core Philosophy

### Immutable raw data
Everything the edge agent observes is stored exactly as received. No filtering, no schema enforcement at ingestion. A reading that arrived is a permanent fact about what was observed — never overwritten, never discarded.

### Schema on read
Meaning is applied after storage, not before. The schema is a lens over data, not a gate. Unknown devices and points are stored as unclassified — not dropped.

### Configuration over coding
Every new device type, property definition, relationship type, and rule is expressed as configuration data (YAML, graph nodes, SQL) — not code. Code handles the engine. Configuration handles the behaviour.

### AI-first, not AI-added
AI changes what the platform can do, not just how you interact with it. Self-configuring (auto-discovery), self-explaining (causal answers), self-learning (anomaly detection), and conversational (NL queries).

### Floor and ceiling
Hardcode only the absolute floor: safety limits, auth, data ingestion, component primitives, audit trail. Let AI own the ceiling: classification, rules, screen assembly, query generation, anomaly detection.

### AI as the learning engine
The platform does not model the domain — it learns the domain. Schema, ontology, thresholds, and baselines are not designed upfront but grown continuously by AI from observation, ratified by humans.

AI is responsible for: extracting intent from user queries, proposing new TBox entries, classifying raw data to TBox types, calibrating rule thresholds from observed variance, learning normal behaviour per context.

Humans are responsible for: approving or rejecting AI proposals, setting intent (what matters, what to act on), providing the floor (safety rules, compliance limits).

The TBox is not a schema designed once — it is an accumulated record of everything the platform has learned. Each new deployment potentially contributes new TBox entries. The platform gets smarter over time.

### TBox as problem-solving ontology
The TBox is a **problem-solving ontology**, not a data inventory.

```
Data inventory ontology:           Problem-solving ontology:
(what we accidentally have)        (what questions matter)
─────────────────────────          ────────────────────────
"We have analog-input:3,           "To solve problems in this domain,
 let's call it something"           you need to reason about X, Y, Z..."

      ↓                                   ↓
Ontology = catalog of              Ontology = domain concepts
existing data sources              that enable reasoning
      ↓                                   ↓
Brittle, grows randomly,           Stable, grows deliberately,
different per installation         shared across deployments
```

This is how real ontologies work:
- **Brick Schema** — building concepts, independent of which sensors exist
- **Schema.org** — web concepts, independent of which sites use them
- **FHIR** — healthcare concepts, independent of which patients exist

The TBox represents **the concepts needed to reason about and act in a domain**. Data sources come and go, but the problem-solving vocabulary is stable and shareable.

This makes the platform **generic** — not tied to buildings or IoT. The v1 instantiation is building monitoring, but the same architecture applies to any domain where:
- Real-time or near-real-time data flows in
- Users need to ask questions, monitor, and act
- AI can help map raw data to meaningful concepts

### Intent-driven TBox
The TBox is driven by **user intent**, not by data availability. This keeps it focused and relevant.

```
TBox = what users WANT to know (demand)
RawTags = what data EXISTS (supply)
Classification = matching supply to demand
```

**TBox grows from intent, not data:**
```
User: "What's the outside temperature?"
         │
         ▼
AI extracts intent → OUTSIDE_TEMP
         │
         ▼
TBox has OUTSIDE_TEMP? ─── NO ───→ Propose new TBox type
         │                                   │
        YES                            Human approves
         │                                   │
         ▼                                   ▼
Search RawTags for matches         TBox now has OUTSIDE_TEMP
         │                                   │
         └──────────────┬───────────────────┘
                        ▼
         Found candidates? ─── NO ───→ "No data. Add source?"
                        │
                       YES
                        ▼
         Propose classification → Human approves → Done
```

This means:
- **TBox stays focused** — only types users actually need
- **Raw data never pollutes TBox** — unclassified RawTags stay dark until needed
- **Unfulfilled needs are visible** — TBox type with no data prompts "add data source"
- **Unused data is fine** — RawTags without classification don't bloat the system

**Seed TBox is entailed by predefined apps:**

Rather than importing a generic ontology (Brick/Haystack), the seed TBox contains exactly the types needed by predefined dashboards, workflows, and rules:

```
Predefined Apps (starter kit)          Seed TBox (entailed)
─────────────────────────────          ────────────────────
Building Monitor Dashboard      →      ZoneTemp, SupplyAirTemp, Occupancy
Energy Dashboard                →      ActivePower, EnergyConsumption
Air Quality View                →      CO2Concentration, Humidity
AHU Fault Workflow              →      AHUStatus, FaultCode
High Temp Alert                 →      ZoneTemp (reused)
```

The seed is minimal, focused, and every type has a use case. The TBox grows organically as users ask new questions.

**AI-guided discovery (helping users ask better questions):**

Users can't ask for what they don't know exists. A dropdown of classified TBox types only shows what's been asked before — it doesn't help users discover what's meaningful.

AI acts as a **domain consultant**, suggesting relevant questions based on building domain knowledge — not limited to existing data:

```
User: "I'm setting up monitoring for AHU-1"

AI (domain expert): "For air handling units, you typically want:
   ✓ Supply Air Temp      [data available]
   ✓ Return Air Temp      [data available]
   ○ Discharge Air Temp   [no data yet]
   ○ Mixed Air Temp       [no data yet]
   ✓ Fan Status           [data available]
   ○ Filter Pressure      [no data yet]
   ○ Cooling Valve Pos    [no data yet]

   ✓ = classified data exists
   ○ = no data source (add sensor? add integration?)"

User selects "Filter Pressure"
  → TBox type added (if missing)
  → No RawTag matches → "Add a filter pressure sensor?"
```

This means:
- **Suggestions draw from domain knowledge**, not just existing data
- **Users learn the right questions** for their equipment type
- **Gaps become visible** — "you should have X but don't"
- **System grows toward completeness**, guided by domain best practices

The AI helps users explore what's *meaningful*, not just what's *available*.

### Open ingestion layer
Sensor data and external API data are unified — they differ only in how they arrive. The platform ships with defaults (MQTT for edge agent sensor data, pre-built pipeline templates for common APIs) but the ingestion layer is fully open: users and AI can register any data source via the `data_sources` registry. Bento dynamically spawns pipelines for new entries. All data flows through the same normalisation and classification loop regardless of origin.

---

## Data Model

### Five layers

```
Physical world
    │  observation
    ▼
Layer 0 — raw immutable store
    Everything as received. Never changes.
    AGE graph for topology.
    One readings table for all data (sensor + context):

      CREATE TABLE readings (
          id            uuid PRIMARY KEY,
          building_id   text,       -- uuid or '*'
          source_id     uuid,       -- references data_sources
          source_type   text,       -- 'sensor'|'api'|'mqtt'|'file'
          scope         text,       -- 'device'|'building'|'global'
          device_id     uuid,       -- null for non-sensor sources
          point_type    text,       -- TBox type or 'unclassified'
          value         float,
          unit          text,
          raw_payload   jsonb,      -- immutable original
          agent_read_at timestamptz,
          confidence    float DEFAULT 1.0
      );

    TimescaleDB hypertable on agent_read_at.
    device_id is nullable — present for sensor data,
    null for context/API data. Partial indexes keep
    queries fast without indexing null rows:

      -- sensor queries: per device + point + time
      CREATE INDEX readings_device_idx
          ON readings (device_id, point_type, agent_read_at DESC)
          WHERE device_id IS NOT NULL;

      -- context queries: per building + point + time
      CREATE INDEX readings_context_idx
          ON readings (building_id, point_type, agent_read_at DESC)
          WHERE device_id IS NULL;
    │
    ▼
Layer 1 — semantic layer (TBox + ABox)
    TBox: device type definitions, property schemas,
          relationship definitions, Brick mappings.
          Loaded from init YAML files at boot.
    ABox: device instances (RawTag), topology, classifications.
          RawTags created at discovery; classifications added lazily
          when user interacts with a tag (classify on read).
    Both live in Apache AGE (graph).
    │
    ▼
Layer R — read lens (config-driven, applied at query time)
    Gap fill, drift correction, confidence scoring,
    simulation overlay, unit normalisation.
    Implemented entirely in SQL — Postgres views and
    functions, TimescaleDB gapfill. Zero application code.
    Config lives in read_lens_config Postgres table
    (seeded from read_lens_config.yaml at boot, then
    maintained live via PostgREST).
    Simulation results stored in TimescaleDB alongside
    sensor readings (source='simulation') — lens prefers
    sensor readings, falls back to simulation for gaps.
    │
    ▼
Layer 2 — application projection
    Typed views over Layer 1 for each app.
    Subset of TBox properties the app cares about.
    Expressed as Postgres views + PostgREST.
    │
    ▼
Applications / AI / Rules
```

### TBox init files (configuration, not code)

```
platform/init/tbox/
  device_types.yaml        AHU, Chiller, VAV, Pump...
  property_defs.yaml       supply_air_temp, power_kw, cop...
  relationship_defs.yaml   serves, located_in, monitors...
  read_lens_config.yaml    gap fill, drift, fusion rules
  brick_mappings.yaml      local types → Brick ontology classes
  rule_definitions.yaml    streaming + scheduled rules
```

Device types, properties, and relationships are data — not Go structs. Adding a new device type means adding a row to the config, not a code change.

### Data source registry

All ingestion sources — platform defaults and user-defined — are registered in the `data_sources` table. Bento watches this table and dynamically spawns pipelines for new enabled entries.

```sql
CREATE TABLE data_sources (
    id              uuid PRIMARY KEY,
    building_id     text,           -- '*' or specific uuid
    name            text,
    source_type     text,           -- 'mqtt' | 'http_poll' | 'webhook'
                                    -- | 'file' | 'bacnet' | 'modbus'
    config          jsonb,          -- connection config (url, interval, headers)
    transform       text,           -- Bloblang to normalise raw payload
    enabled         boolean DEFAULT true,
    registered_by   text,           -- 'platform' | 'user' | 'ai'
    classification  text            -- 'classified' | 'pending' | 'rejected'
);
```

Platform ships with defaults seeded from YAML (`registered_by = 'platform'`):
- Edge agent MQTT connection
- Pre-built HTTP pipeline templates (weather, electricity rates, busyness)

Users and AI register new sources by inserting rows. The platform fetches a sample response and stores it raw. Classification happens lazily when the data is first used — AI proposes a `point_type` and optional TBox entry, human approves, then data becomes semantically queryable. Until then, data is still stored and accessible as unclassified.

Context data property types live in the TBox alongside sensor types, with `source_type: context` to distinguish them. This makes them referenceable in rules, lens queries, and anomaly detection on equal footing with sensor data.

### Read lens implementation

The read lens is implemented entirely in SQL — no application service code. Three mechanisms work together:

**Postgres views (unit normalisation, field aliasing)**
Layer 2 projections are Postgres views that convert raw units and alias fields for each application. Declared once as DDL, served by PostgREST automatically.

**TimescaleDB gapfill + Postgres functions (gap fill, drift correction, confidence)**
A Postgres function `get_reading_with_lens()` wraps `time_bucket_gapfill()` (TimescaleDB built-in) and joins against `read_lens_config` to apply drift offsets and confidence factors at query time. Exposed via PostgREST RPC. Example:
```sql
-- gap fill with drift correction in one SQL function
SELECT time_bucket_gapfill('5 minutes', agent_read_at),
       interpolate(avg(value)) + COALESCE(lc.drift_offset, 0),
       CASE WHEN value IS NULL THEN 0.5 ELSE lc.confidence_factor END
FROM raw_readings r
LEFT JOIN read_lens_config lc ON lc.device_id = r.device_id
    AND lc.point_id = r.point_id
    AND lc.valid_from <= r.agent_read_at
    AND (lc.valid_to IS NULL OR lc.valid_to > r.agent_read_at)
WHERE r.device_id = $1 AND agent_read_at BETWEEN $2 AND $3
GROUP BY 1, lc.drift_offset, lc.confidence_factor;
```

**Simulation as a stored source (simulation overlay)**
Simulation results (EnergyPlus or simpler thermal model) are stored in TimescaleDB alongside sensor readings with `source = 'simulation'`. The lens function prefers `source = 'sensor'` and falls back to `source = 'simulation'` for gaps. No special code path — just a UNION with priority ordering.

**read_lens_config table**
Runtime lens configuration lives in Postgres, not in YAML at runtime. The YAML file is the seed — loaded at boot into the table. Live changes (recalibration, new drift offsets) are made via PostgREST. The table is itself bitemporal (`valid_from`, `valid_to`) so historical queries automatically apply the correct calibration for the time period being queried.

**Classification-on-read (pg_net trigger)**

The read API is by TBox type, not raw tags. Building context comes from JWT claims (set by Zitadel Actions), not API parameters. When an app requests data for a TBox type, the platform checks if any RawTag is classified to that type. If not, it triggers the classifier workflow asynchronously.

```
App: "Get zone_air_temp" (JWT has building_id claim)
              │
              ▼
    PostgREST RPC function
    (extracts building_id from JWT)
              │
   ┌──────────┴──────────┐
   │                     │
   ▼                     ▼
Check: any RawTag     Return data from
with approved         classified RawTags
IS_TYPE_OF edge       (with lens applied)
to this type?
   │
   NO
   │
   ▼
pg_net.http_post() → Restate classifier workflow
(async, fire-and-forget)
```

Implementation uses pg_net extension for async HTTP from PL/pgSQL:

```sql
CREATE FUNCTION get_readings_by_type(
    p_tbox_type text,
    p_start timestamptz DEFAULT now() - interval '1 hour',
    p_end timestamptz DEFAULT now()
) RETURNS jsonb AS $$
DECLARE
    v_building_id text;
    has_classification boolean;
    result jsonb;
BEGIN
    -- Extract building_id from JWT claims (no business params in API)
    v_building_id := current_setting('request.jwt.claims', true)::jsonb->>'building_id';

    -- Check if any RawTag is classified to this TBox type
    SELECT EXISTS (
        SELECT 1 FROM cypher('platform', format($$
            MATCH (r:RawTag {building_id: %L})-[:IS_TYPE_OF {status: 'approved'}]->(p:PropertyDef {name: %L})
            RETURN r LIMIT 1
        $$, v_building_id, p_tbox_type)) AS (r agtype)
    ) INTO has_classification;

    -- Trigger classifier if no classification exists (async, non-blocking)
    IF NOT has_classification THEN
        PERFORM net.http_post(
            url := 'http://restate:8180/classifier/' || v_building_id || '-' || p_tbox_type || '/run',
            body := jsonb_build_object('building_id', v_building_id, 'tbox_types', array[p_tbox_type])
        );
    END IF;

    -- Return data with lens applied (may be empty if no classification yet)
    SELECT jsonb_build_object(
        'data', COALESCE((SELECT jsonb_agg(...) FROM get_readings_with_lens(...)), '[]'::jsonb),
        'classification_pending', NOT has_classification
    ) INTO result;

    RETURN result;
END;
$$ LANGUAGE plpgsql;
```

Apps call one PostgREST endpoint with JWT, get data + classification status. No service layer, no business params in API.

**RawTag ID linking (readings ↔ graph)**

The link between time-series readings and graph RawTag nodes is the `rawtag_id` field. The ID derivation logic is externalized in `data_sources.rawtag_id_template` (Bloblang expression) — defined once per source type, used consistently for both RawTag creation and readings linking.

```
Write path (telemetry ingestion):
  raw_payload → rawtag_id_template → rawtag_id → stored in readings.rawtag_id
                                             → upsert RawTag node in graph

Read path (get_readings_by_type):
  TBox type → query graph for approved RawTag IDs → query readings by rawtag_id
```

Example templates per source type:
```
BACnet:  bacnet:${building_id}:device-${device_id}:${object_type}:${object_instance}
Modbus:  modbus:${building_id}:slave-${slave_id}:reg-${register}
MQTT:    mqtt:${building_id}:${topic_segment_2}:${topic_segment_3}
```

Benefits:
- Single definition of ID format per source type (no duplication)
- rawtag_id cached in readings at write time (no reconstruction at read time)
- Clean join between readings table and graph via rawtag_id

### v1 graph (current topology, no bitemporality)

The graph stores current state of the building topology. Nodes are devices, zones, floors, gateways. Edges are typed relationships (serves, located_in, connected_to, monitors). TBox type nodes are linked to ABox instance nodes via IS_TYPE_OF edges.

Bitemporality (valid_from, valid_to, recorded_at, superseded_at on edges) is deferred to v2. The upgrade path is additive — add four timestamp properties to edges and change the write path to append rather than update.

### Why unified Postgres (AGE + TimescaleDB) over separate graph DB

Both AGE and TimescaleDB are Postgres extensions sharing the same query executor. This means graph traversal results and time-series data can be joined in a single SQL statement — no application-layer join, no second round trip:

```sql
-- One query: graph traversal + time-series join
-- All devices serving zone 3A + their last hour of readings
SELECT
    d.properties->>'raw_name'   AS device,
    dt.properties->>'label'     AS type,
    r.point_type,
    r.value,
    r.agent_read_at
FROM cypher('platform', $$
    MATCH (d:Device)-[:SERVES]->(z:Zone {id: 'zone-3a'})
    MATCH (d)-[:IS_TYPE_OF]->(dt:DeviceType)
    RETURN d, dt
$$) AS (d agtype, dt agtype)
JOIN readings r ON r.device_id = (d->>'id')::uuid
WHERE r.agent_read_at > now() - interval '1 hour';
```

With a separate graph database (Kuzu, Neo4j), this requires two round trips and an application-layer join — the graph query returns device IDs, the application queries TimescaleDB with those IDs, the application merges the results. The Postgres query planner cannot optimise across both sides.

The tradeoff: AGE implements a subset of openCypher and is not as performant as a purpose-built graph engine for deep traversals. For building topology (hundreds of nodes, queries rarely exceeding 3 hops) this is not a practical constraint. The unified query benefit is real and applies to every read operation the platform performs.

---

## System Components

### Bill of Materials (v1)

| Component | Role | License |
|---|---|---|
| Postgres 16 | Relational + audit + platform config | PostgreSQL |
| TimescaleDB | Time-series extension | Apache 2 |
| Apache AGE | Graph extension | Apache 2 |
| pg_net | Async HTTP from PL/pgSQL | Apache 2 |
| PostgREST | Zero-code REST over Postgres | MIT |
| Mosquitto | MQTT broker | EPL/EDL |
| Bento | Stream processing + pipelines | MIT (community fork) |
| BAC0 / BACpypes3 | BACnet/IP discovery + polling (Python) | LGPL |
| Restate | Durable workflow engine | MIT |
| Paho MQTT (inside Restate) | MQTT client library | Apache 2 |
| Zitadel | Identity provider + JWT issuer | Apache 2 |
| LiteLLM | LLM abstraction for AI classifier | MIT |
| Prometheus | Metrics collection | Apache 2 |
| Grafana | Dashboards + alerting | AGPL |
| Loki + Promtail | Log aggregation | Apache 2 |

**Not in v1:** Modbus support, temporal graph (bitemporality), Ollama, MinIO.

---

## Edge Agent

### Philosophy
The edge agent is a syncer. It synchronises ALL devices and readings from the BMS network to the platform. It decides nothing — no filtering, no classification, no interpretation. It is a faithful witness to the physical network.

```
Edge agent decides:    HOW to read (poll interval, batch size, retry)
                       WHEN to read (schedule, discovery timing)

Edge agent never:      WHAT to read (reads everything it finds)
                       WHAT it means (platform classifies)
                       WHETHER to store (always forwards all)
```

### Architecture: Producer → Queue → Consumer

The edge agent uses a decoupled architecture with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────────┐
│                         Edge Agent                              │
│                                                                 │
│  ┌──────────────────┐                                           │
│  │  Python Scripts  │  PRODUCERS                                │
│  │  (supervisord)   │  - discover.py: BACnet Who-Is/I-Am scan   │
│  │                  │  - poller.py: continuous COV/polling      │
│  └────────┬─────────┘                                           │
│           │ INSERT                                              │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │     SQLite       │  QUEUE + BUFFER + CONFIG                  │
│  │   (WAL mode)     │  - devices table: discovered inventory    │
│  │                  │  - readings table: telemetry buffer       │
│  │                  │  - (future) config: poll intervals, etc.  │
│  └────────┬─────────┘                                           │
│           │ SELECT                                              │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │  Bento Streams   │  CONSUMER                                 │
│  │  (single proc)   │  - discovery.yaml: publish device list    │
│  │                  │  - uploader.yaml: publish readings        │
│  └────────┬─────────┘                                           │
│           │ MQTT                                                │
└───────────┼─────────────────────────────────────────────────────┘
            ▼
      Mosquitto → Platform
```

**Why this pattern:**
- **Decoupling**: Protocol libraries (BAC0/BACpypes3) run in Python; streaming/publishing runs in Bento. Neither blocks the other.
- **Resilience**: SQLite buffers readings during network outages. Bento retries from last uploaded row.
- **Simplicity**: No custom queue service. SQLite WAL mode handles concurrent reads/writes.
- **Extensibility**: SQLite can store config data (poll intervals, object filters) that Python reads at runtime.

### Components

```
edge-agent/
  scripts/
    init_db.py         initialise SQLite schema (WAL mode)
    discover.py        BACnet discovery via BAC0 (async)
                       Who-Is broadcast → I-Am responses
                       ReadPropertyMultiple for object lists
                       writes to devices + objects tables
    poller.py          continuous polling via BAC0 (async)
                       reads presentValue from all objects
                       writes to readings table
  config/streams/
    discovery.yaml     Bento stream — SELECT from devices/objects
                       publish JSON to MQTT discovery topic
                       runs on interval (default 60s)
    uploader.yaml      Bento stream — SELECT unuploaded readings
                       publish to MQTT telemetry topic
                       UPDATE uploaded=1 on success
  supervisord.conf     process manager — runs discover, poller, bento
  Dockerfile           Python 3.11 + BAC0 + Bento binary
  docker-compose.yaml
```

### Discovery flow

```
1. discover.py runs BACnet Who-Is broadcast (BAC0 async)
2. Waits for I-Am responses, collects device addresses
3. For each device: ReadPropertyMultiple to enumerate objects
4. Writes device + object metadata to SQLite
5. Bento discovery stream (on interval):
   - SELECT from devices/objects tables
   - Publishes to: buildings/{id}/agents/{id}/discovery (QoS 1)
6. Platform receives payload, creates RawTag nodes in graph
7. poller.py starts polling all discovered objects
```

### Polling
- `poller.py` polls every BACnet object on every discovered device
- No enumeration in config — reads everything found in SQLite
- Poll interval by object type category (analog-input: 60s, binary: 30s, etc.)
- Readings written to SQLite with `uploaded=0`
- Bento uploader stream: SELECT WHERE uploaded=0, publish, UPDATE uploaded=1
- New objects detected on periodic rescan → added to SQLite, polling begins automatically

### SQLite as buffer
- WAL mode enables concurrent read (Bento) + write (Python) without locking
- Survives network outages — readings accumulate until connectivity restored
- Survives process restarts — Bento resumes from last uploaded reading
- Future: config table for runtime-adjustable poll intervals, object filters

### Timestamp provenance
BACnet and Modbus carry no timestamps. The edge agent's read time (`agent_read_at`) is the best available approximation of valid time. Every raw reading includes:
- `agent_read_at` — always present
- `protocol_ts` — present only if protocol provides (OPC-UA)
- `clock_quality` — "ntp_synced" or "local_only"

---

## Platform

### Data paths

**Collection path (all sources → platform)**
```
All data sources converge on Bento ingestion pipeline:

Edge agent (BACnet)    External webhook/push    External HTTP APIs
  │  MQTT publish        │  HTTP POST              │  Bento scheduled pull
  ▼                      ▼                         ▼
Mosquitto            Bento http_server         Bento generate
  │  Bento mqtt          │  input                  │  + http_client
  │  client input        │                         │
  └──────────────────────┴─────────────────────────┘
                 │  User-registered sources
                 │  (data_sources registry →
                 │   dynamic Bento pipelines)
                 ▼
        Bento ingestion pipeline
          ├── Protocol normalisation (Bloblang)
          ├── Fusion / quality scoring
          ├── Outlier detection + confidence tagging
          └── Fan-out:
              ├── TimescaleDB writer (readings table)
              ├── Graph updater (device state in AGE)
              └── Rule evaluator (streaming rules)
```

### Ingestion input types

Bento supports two server-mode inputs and multiple client-mode inputs. MQTT is the one case where Bento cannot act as the server — it is always a client connecting to an external broker. This is the key architectural difference:

```
Input type      Bento role    Implementation      Notes
──────────────  ────────────  ──────────────────  ─────────────────────────
http_server     SERVER        Bento built-in      stateless request-response
                              no external dep     each POST is independent
                                                  natural fit for Bento input

mqtt (client)   CLIENT        Bento built-in      connects to Mosquitto
                              needs Mosquitto     stateful: subscriptions,
                              as external broker  QoS, retained messages,
                                                  per-client ACL — broker
                                                  concerns Bento cannot own

http_poll       CLIENT        Bento generate      Bento pulls on schedule
                              + http_client       no inbound connections

modbus          CLIENT        Bento modbus        Bento polls registers
                              input plugin        no inbound connections

bacnet          CLIENT        Go subprocess       stateful scan subprocess
                              + Bento stdin       Bento reads stdout
```

Mosquitto remains a standalone service rather than being embedded in Bento for three reasons. First, failure isolation — a Bento pipeline crash should not kill the MQTT broker and disconnect all edge agents. Second, retained messages — Mosquitto persists retained discovery payloads to disk; an embedded broker would require explicit persistence management. Third, maturity — Mosquitto has a production-grade JWT ACL plugin; reimplementing this in a custom plugin adds risk with no benefit.

### Uniform data_sources despite non-uniform implementation

The `data_sources` registry achieves uniformity at the interface level. Each `source_type` maps to a Bento input configuration — the fact that `mqtt` uses an external broker while `http_server` is embedded is an implementation detail invisible to the registry:

```
source_type       data_sources registry    Bento implementation
────────────────  ──────────────────────   ──────────────────────────────
mqtt              { port: 1883,            Bento mqtt client input
                    topics: [...] }          → Mosquitto (standalone)

http_server       { port: 4195,            Bento http_server input
                    path: /ingest }          (embedded, no broker)

http_poll         { url: "...",            Bento generate input
                    interval: "15m" }        + http_client processor

modbus            { address: "...",        Bento modbus input plugin
                    registers: [...] }

bacnet            { network: "...",        bacnet-discover subprocess
                    poll_interval: "60s" }   + Bento stdin input
```

From the `data_sources` table and the app UI, all source types look identical — a row with a `source_type` and a `config` JSONB blob. Bento's dynamic pipeline spawner translates each `source_type` into the correct input configuration. The MQTT/non-MQTT distinction is encapsulated inside the spawner, not exposed to users or operators.

**Control path (downward: platform → BMS)**
```
App / Rule engine / AI
    │  HTTP POST to Restate ingress
    ▼
Restate CommandObject (virtual object per device_id)
    │  1. Validate against TBox + safety limits (Postgres)
    │  2. Publish command via Paho → Mosquitto
    │  3. Park awaiting ack (Restate awakeable, 30s timeout)
    │  4. Record outcome in AGE graph
    ▼
Mosquitto broker
    │  MQTT subscribe
    ▼
Edge agent (Bento command pipeline)
    │  Routes to BACnet write subprocess
    ▼
BACnet WriteProperty → physical device
    │  Ack published: buildings/{id}/agents/{id}/commands/ack
    ▼
Bento ack pipeline
    │  HTTP POST to Restate AckReceived handler
    ▼
Restate resolves awakeable → workflow completes
```

### Processing layers

**Streaming rules (Bento, before TSDB write)**
Per-message, stateless, immediate. Safety limits, outlier isolation, unit conversion, CO2→damper direct response. Fires in milliseconds. These are platform-defined and operator-configured — facilities managers never write streaming rules.

**Scheduled soft rules (Bento timer pipelines)**
Queries TimescaleDB continuous aggregates every 1-5 minutes. Trend detection, sustained threshold violations, peer sensor drift. Covers ~80% of soft rule needs. Bento evaluates `rule_instances` rows from Postgres — adding a new user alert requires only inserting a row, no redeployment.

**CEP correlation window (in-process Go)**
~300 lines. Ring buffer of recent events per device. For the ~5% of patterns needing sub-minute multi-event correlation: cascade detection, rapid fault sequences, suppression patterns.

**AI anomaly detection (continuous)**
Model-based, learns normal per device per context (weekday/weekend, occupied/unoccupied, seasonal). Catches unknown unknowns. Replaces most explicit CEP needs.

**Workflows (Restate)**
Stateful, human-in-loop, long-running. Command dispatch, alert lifecycle, device onboarding, OTA updates, maintenance orders. Human-initiated or AI-proposed actions that need durability.

### Rule routing principle

```
Program-generated data   → stream processing / scheduled pipelines
Human-initiated tasks    → workflow engine
```

### Rule extensibility

All rules — platform defaults and user-added custom rules — live in one `rules` table. A `source` column distinguishes ownership. A `'*'` wildcard on `building_id` and `device_id` means "applies to all":

```sql
CREATE TABLE rules (
    id              uuid PRIMARY KEY,
    building_id     text,     -- '*' = all buildings, uuid = one building
    source          text,     -- 'platform' | 'user'
    name            text,
    point_type      text,     -- TBox property type
    condition       text,     -- "value > threshold"
    threshold       float,
    severity        text,     -- 'P1' | 'P2' | 'P3'
    device_id       text,     -- '*' = all devices of point_type, uuid = one device
    notify_user_ids uuid[],
    enabled         boolean DEFAULT true
);
```

```
source='platform'   platform defaults, always-on
building_id='*'     seeded from rules.yaml at boot
device_id='*'       operator-managed, read-only to users
                    examples: equipment_fault, sensor_offline,
                              co2_high, energy_spike

source='user'       user-added building-specific rules
building_id=uuid    created via app UI → PostgREST INSERT
device_id=uuid      facilities manager owns these
                    example: server room > 25°C on specific sensor
```

Platform defaults fire for every building with no configuration. User rules add the "I specifically want to know about this" layer on top. Bento evaluates all enabled rows for the building in one query. RLS ensures `source='platform'` rows are read-only to users.

### Workflow extensibility

Building operations has a small, knowable set of workflow patterns. Rather than a general flow designer, the platform provides a **workflow template library** — fixed Go/Restate patterns parameterised via configuration:

```
workflow_templates      platform pattern library (developer-defined)
                        fixed Go + Restate handler code
                        v1 templates:
                          command_dispatch
                          device_onboarding
                          alert_lifecycle
                          ota_update
                          maintenance_task       ← configurable
                          repair_order           ← configurable
                          inspection_round       ← configurable

workflow_configs        operator-configured instances of templates
                        created via app UI → PostgREST INSERT
                        picks a template, sets parameters:
                          assignee_role, approver_role,
                          sla_hours, escalation_chain,
                          trigger conditions
                        example:
                          template: maintenance_task
                          trigger: equipment_fault on chillers
                          assignee: hvac_technician
                          approver: facility_manager
                          sla_hours: 4

workflow_instances      Restate runtime (per execution)
                        created when trigger condition fires
                        tracks state in Restate embedded store
```

Platform developers write the template code once. Building operators configure workflow behaviours through the app. Facilities managers interact with running instances (acknowledge, approve, sign off). Nobody writes flow diagrams or custom code to add a maintenance order workflow — they configure a `maintenance_task` template instance.

New workflow *patterns* that don't fit any template require a developer to write a new Restate handler. This is the hard floor — logic that varies per execution step cannot be expressed as configuration alone.

---

## API Surface

No traditional API layer. Two surfaces cover everything:

**PostgREST (zero code — all data access)**
Auto-generated REST from Postgres schema + RLS. Frontend queries directly. JWT claims become Postgres session variables. RLS policies enforce building isolation automatically. Postgres functions expose graph (Cypher) queries as RPC endpoints.

**Restate HTTP ingress (zero code — all workflow triggers)**
Command dispatch, device scan trigger, alert acknowledgement, OTA initiation. Restate's built-in HTTP ingress routes to named workflow handlers. No custom endpoint code.



---

## Auth

### Architecture
One auth provider (Zitadel) translates all identity protocols into JWT. Platform components only speak JWT. Never touch LDAP/Kerberos/SAML directly.

```
Corporate LDAP/AD  ──→
Google / GitHub    ──→  Zitadel  ──→  JWT with claims:
SAML enterprise    ──→  (single       { sub, roles,
Kerberos (via AD)  ──→   place)         building_id,
Username/password  ──→                  org_id, exp }
```

### JWT custom claims
Zitadel Actions inject `building_id` and `org_id` into every token at issuance. These flow through to:
- **Postgres RLS** — session variables set by PostgREST, enforced per row
- **MQTT ACL** — Mosquitto JWT plugin scopes topics to building
- **Restate** — middleware validates + extracts claims before workflow dispatch

### Machine identity
Service accounts in Zitadel for: Bento (bento_writer role), Restate workflows (workflow_rw role), edge agents (edge_insert role + X.509 cert for MQTT). Issued during onboarding workflow.

### Postgres roles
```
bento_writer       INSERT on readings, SELECT on tbox
workflow_rw        SELECT on readings + tbox (for validation in workflow steps)
edge_insert        INSERT on raw_readings only
ai_reader          SELECT all (scoped by RLS)
postgrest_role     SELECT/INSERT per RLS policy
```

---

## Deployment Modes

### Mode 1 — Public cloud SaaS
Multi-tenant shared platform. One edge agent per customer building. Platform in cloud. Edge agents in customer buildings. Transport: MQTT over TLS. Isolation: Zitadel org per customer + Postgres RLS per building.

### Mode 2 — Private cloud / on-prem server
Single-tenant platform per customer. One edge agent per building. Platform on customer's server. Transport: MQTT over local network. Simpler isolation — single tenant.

### Mode 3 — All-in-one on-prem
Platform + edge agent on same host. Single building. Transport: MQTT on localhost (Mosquitto still used — same codebase, <1ms overhead, 5MB RAM). Air-gapped deployment possible. No internet required.

**Multi-building:** Each building gets its own edge agent (and its own SQLite cache). All agents connect to one shared platform. Building isolation enforced via JWT claims + RLS.

---

## Security

### Audit log
Handled by the unified events table (see **Unified Events** section below). Application roles have INSERT only — UPDATE and DELETE revoked. Covers all operational audit (who commanded what, when, outcome). Security-sensitive events are tagged in the payload for compliance queries.

### Data backup
**Two backup targets: Postgres + Restate volume.**

Postgres contains:
- TimescaleDB hypertable (telemetry)
- AGE graph (topology, TBox, ABox)
- Audit log
- Config tables (rules, lens config, notifiers)
- Zitadel identity data (shares Postgres instance)

Restate contains:
- Workflow state (durable execution journal)
- In-flight command lifecycle
- Awakeable state
- Stored in embedded RocksDB (Docker volume)
- Back up as a volume snapshot alongside Postgres

Strategy: continuous WAL archiving (point-in-time recovery) + daily pg_dump + weekly volume snapshot.

Everything else (Mosquitto retained messages, Prometheus metrics, Loki logs, Bento state) is ephemeral — loss is tolerable, reconstructable, or operationally irrelevant.

---

## Observability

Pure configuration — zero custom code beyond three lines of `promhttp.Handler()` in the Go API binary.

```
Prometheus          scrapes: Postgres exporter, Bento /metrics,
                    Restate /metrics, Mosquitto exporter,
                    platform API /metrics (Go runtime)

Grafana             community dashboards imported by ID
                    custom platform dashboard exported as JSON
                    provisioned at boot from config files

Loki + Promtail     auto-discovers all Docker containers
                    ships logs by container name label
                    30-day retention
```

---

## Unified Events

### The insight

Logging, tracing, provenance, and auditing are the same operation — recording what happened — viewed from different perspectives:

```
Filter by component/level    → ops logging      (for engineers)
Filter by trace_id           → distributed trace (for debugging)
Filter by data_id            → data provenance   (for customers)
Filter by actor              → audit trail       (for compliance)
```

One event stream, one table, different query patterns. Design for the strictest requirements (audit: append-only, 100% capture, long retention) and the others come for free.

```
Logging  ⊂  Provenance  ⊂  Audit
(weakest)   (middle)       (strictest)
```

### Data model

```sql
CREATE TABLE evoiot.events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY,
    timestamp   TIMESTAMPTZ DEFAULT now(),
    component   TEXT NOT NULL,     -- bento.telemetry, restate.classifier, postgres
    operation   TEXT NOT NULL,     -- mqtt_receive, sql_insert, llm_classify, human_approve
    data_id     TEXT,              -- rawtag_id or reading.id (NULL = pure ops log)
    trace_id    TEXT,              -- request-level correlation
    actor       TEXT,              -- bento, doubao-v3, user@company.com
    payload     JSONB,             -- context, flexible per operation
    PRIMARY KEY (id)
);
```

- **Append-only**: application roles granted INSERT only — no UPDATE, no DELETE
- **data_id** is the key: if present, the event is provenance; if absent, it's a pure ops log
- **No rigid event type enum**: operation is free-text, not a controlled vocabulary — avoids brittleness when adding new pipeline steps

### Four chokepoints

Inspired by NiFi's `ProcessSession` — a single root class that makes provenance emission unavoidable. Each layer of the platform has one chokepoint where all data must pass, ensuring no event goes unrecorded.

**1. Bento — custom `pg_events` tracer plugin (global config)**

A custom Bento binary wraps the standard Bento with a `pg_events` tracer plugin. The plugin implements the OTel `SpanExporter` interface and writes spans directly to `evoiot.events` via SQL — no protobuf, no bridge stream, no OTel Collector.

```yaml
# global.yaml — applies to ALL streams automatically
tracer:
  pg_events:
    dsn: "postgres://bento_writer:...@postgres:5432/postgres"
    keep_prefixes:
      - "input_"
      - "output_"
```

The tracer is built into the Bento binary via the official plugin API (`service.RegisterOtelTracerProvider`). Bento is imported as a Go dependency, not forked — upgrading is just a version bump in `go.mod`. Adding new streams automatically gets traced with zero per-stream configuration.

The `keep_prefixes` filter ensures only input/output boundary events are recorded (not internal processor noise). The plugin can be extended to extract `data_id` from span attributes set via Bento's `meta` mechanism.

**2. Restate — `traced_run` wrapper**

Restate's `ctx.run()` is the single function all workflow steps must call. A thin wrapper makes event emission automatic:

```python
async def traced_run(ctx, name, fn):
    result = await ctx.run(name, fn)
    logger.info("step_completed", extra={
        "workflow_id": ctx.key(),
        "step": name,
        "result_summary": _summarize(result),
    })
    return result
```

Replace `await ctx.run(...)` with `await traced_run(ctx, ...)` throughout workflows. Every step — LLM classification, proposal creation, human review — is logged with its workflow ID (which encodes the data correlation key). New workflow steps automatically get logged. No way to skip it.

**3. PostgreSQL relational — `emit_event()` trigger function**

One generic trigger function, attached to every relational table that matters:

```sql
CREATE FUNCTION evoiot.emit_event() RETURNS trigger AS $$
BEGIN
    INSERT INTO evoiot.events (component, operation, data_id, actor, payload)
    VALUES (
        'postgres',
        TG_OP,
        COALESCE(NEW.rawtag_id, NEW.id::text),
        current_user,
        jsonb_build_object('table', TG_TABLE_NAME, 'new', to_jsonb(NEW))
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

Attached to relational tables (readings, data_sources). Standard PostgreSQL triggers work here.

**4. PostgreSQL graph — `execute_cypher()` wrapper**

AGE bypasses the standard PostgreSQL executor for Cypher mutations (CREATE, MERGE, SET) — it writes directly to the heap via its C extension, so **standard PostgreSQL triggers do not fire** for Cypher operations. Instead, the chokepoint is `execute_cypher()` in `graph.py` — the single Python function through which all graph mutations flow:

```python
def execute_cypher(query: str) -> list[dict]:
    """Execute a Cypher query, emit event, return results."""
    # ... execute query ...
    _emit_event(component="graph", operation=_classify_op(query),
                data_id=_extract_id(query), payload={"cypher": query})
    return results
```

Every graph operation — `create_is_type_of_edge`, `update_is_type_of_status`, `get_rawtags_for_context` — goes through this function. New graph operations automatically get logged.

### Event flow architecture

```
Bento (branch+sql_raw) ──┐
Restate (traced_run) ─────┤──→ evoiot.events table
PG triggers (relational) ─┤          │
PG functions (graph) ─────┘          │
                          ┌──────────┼──────────┐
                          ▼          ▼          ▼
                      Grafana    Provenance    Alerts
                     (ops logs)  (customer)   (quality)
```

### Provenance from the data's perspective

For any data point, a customer can see its full story by querying `WHERE data_id = 'rawtag-xxx' ORDER BY timestamp`:

```
1. Source  — device 9001, protocol BACnet, object analog-value:10, received at T₁
2. Raw     — {"object_name": "floor1_zone_air_temperature", "unit": "degrees-celsius"}
3. Classify — LLM proposed zone_air_temp, confidence 92%, model doubao-v3, at T₂
4. Review  — approved by user@company.com at T₃
5. Serve   — reading 22.5°C included in zone_air_temp query at T₄
```

Every step has a who, what, when, and why. No gaps.

---

## Resource Requirements

| Component | Image | RAM (idle) |
|---|---|---|
| Postgres + TimescaleDB + AGE | ~500 MB | ~300 MB |
| PostgREST | 5 MB | 30–50 MB |
| Mosquitto | 5 MB | 5–15 MB |
| Bento | 40 MB | 50–100 MB |
| Restate | 60 MB | 80–150 MB |
| Zitadel | 60 MB | 100–150 MB |
| LiteLLM | 500 MB | 200–300 MB |
| Prometheus + Grafana + Loki | ~560 MB | ~400 MB |
| Platform binaries (Go) | ~20 MB | ~50 MB |
| **Total** | **~1.8 GB pull** | **~1.4–2.0 GB idle** |

**Recommended host:** 4 GB RAM, 2 vCPUs, 50 GB SSD (one building, one year).

**Disk growth:** ~40–65 MB/day compressed telemetry (150 devices × 30 points × 60s polling, TimescaleDB 10–20× compression).

---

## Development Sequence

Always runnable from day one. Each step adds features without breaking what exists.

**Step 1 — Postgres schema + docker-compose skeleton**
All services in docker-compose, none doing anything meaningful yet. Postgres initialises with full DDL — all tables, RLS policies, Postgres roles, AGE graph labels and edge types, TimescaleDB hypertable, partial indexes. Zitadel, PostgREST, Mosquitto, Bento, Restate, Prometheus, Grafana, Loki all start.

```
postgres/initdb/
  01_schema.sql       all table DDL, hypertable, indexes, RLS, roles
  03_rules_seed.sql   platform default rules (source='platform')
  04_data_sources.sql platform default data source registrations

Verifiable: docker compose up → all services healthy
            PostgREST /readings returns empty array
            AGE graph exists with labels defined
```

**Step 2 — TBox seed data**
Seed TBox contains exactly the types entailed by predefined apps — not a generic ontology import. A single SQL migration file with Cypher INSERT statements. Postgres runs it automatically at boot.

```
postgres/initdb/
  02_tbox_seed.sql    Cypher INSERTs for TBox nodes and edges

                      Entailed by Building Monitor Dashboard:
                        ZoneTemp, SupplyAirTemp, ReturnAirTemp, Occupancy
                      Entailed by Energy Dashboard:
                        ActivePower, EnergyConsumption, DemandPeak
                      Entailed by Air Quality View:
                        CO2Concentration, Humidity, OutsideAirTemp
                      Entailed by predefined rules/workflows:
                        AHUStatus, FaultCode, DamperPosition

                      DeviceType nodes: AHU, VAV, Chiller...
                      RelationshipDef: serves, located_in...
                      HAS_PROPERTY edges linking types to properties

Verifiable: SELECT * FROM cypher('platform', $$
              MATCH (p:PropertyDef) RETURN p.id
            $$) AS (id agtype);
            → returns ZoneTemp, SupplyAirTemp, CO2Concentration...
```

**Step 3 — Edge agent skeleton with synthetic data**
Edge agent docker-compose. Bento telemetry pipeline publishes synthetic fake readings to Mosquitto. Platform ingestion pipeline subscribes and writes to `readings` table. First end-to-end data flow.

```
Verifiable: SELECT COUNT(*) FROM readings > 0
            PostgREST /readings returns data
```

**Step 4 — Real BACnet data**
Edge agent with Python BACnet scripts (BAC0/BACpypes3), SQLite queue, Bento streams. Discovery publishes device+object payload to MQTT. Platform creates RawTag nodes in AGE graph via Cypher MERGE. Telemetry flows to TimescaleDB readings table as `point_type = 'unclassified'`.

```
Verifiable: unclassified readings flowing from real BMS
            RawTag nodes visible in AGE graph
            SELECT * FROM cypher('platform', $$
              MATCH (t:RawTag) RETURN count(t)
            $$) AS (count agtype);
```

**Step 5 — AI classifier (workflow subsystem)**
Classification requires human-in-the-loop (propose → review → rework → approve). Implemented as Restate workflow.

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────┐
│                    Workflow Subsystem                           │
│                                                                 │
│  Restate Server (Rust)       Workflows Service (Python)         │
│  ┌──────────────────┐        ┌────────────────────────────────┐ │
│  │ • Orchestration  │  HTTP  │ classifier/                    │ │
│  │ • State/Journal  │◄──────►│   workflow.py                  │ │
│  │ • Replay         │        │   prompts.py                   │ │
│  │ • Awakeables     │        │ notifications/ (future)        │ │
│  │                  │        │ shared/                        │ │
│  │ "The brain"      │        │   llm.py (LiteLLM)             │ │
│  └──────────────────┘        │   graph.py (Cypher)            │ │
│                              │                                │ │
│                              │ "The hands"                    │ │
│                              └────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Classify API (stateless, called by workflow):**
```python
async def classify(
    rawtags: list[RawTag],
    tbox_types: list[str],      # batch: ["SupplyAirTemp", "ReturnAirTemp", "FanStatus"]
    context: dict,
    feedback: str | None = None  # human comment for rework
) -> dict[str, list[ScoredCandidate]]:
    """
    Match multiple TBox types against RawTags in one LLM call.
    Feedback included when reworking after rejection.
    Returns ranked candidates per type.
    """
```

**Workflow flow:**
```
propose()
  └─► classify(rawtags, tbox_types, context, feedback=None)
        └─► create IS_TYPE_OF edges (status='proposed')

await_review()
  └─► human approves some, rejects others with comment

rework()  (for rejected ones)
  └─► classify(..., feedback="This is return air, not supply")
        └─► LLM adjusts based on feedback
              └─► update proposals

finalize()
  └─► approved edges: status='approved'
      rejected edges: deleted or status='rejected'
```

**IS_TYPE_OF edges in graph (no separate proposals table):**
```cypher
(r:RawTag)-[:IS_TYPE_OF {
    status: "proposed",       -- or "approved" / "rejected"
    confidence: 0.85,
    reason: "objectName contains 'SAT'",
    proposed_at: timestamp,
    approved_at: null,
    approved_by: null,
    feedback: null            -- human comment if reworked
}]->(p:PropertyDef)
```

**Benefits of batch classify:**
- One LLM call for all dashboard types (fewer calls)
- LLM reasons about all types together (avoids duplicate assignments)
- Better disambiguation ("3 temp sensors, 3 temp types" matched as set)

```
Verifiable: Trigger workflow for device with 3 required types
            → 3 IS_TYPE_OF edges created (status='proposed')
            → Human approves 2, rejects 1 with feedback
            → Rework re-classifies rejected one
            → All approved → dashboard shows data
```

**Step 6 — Read data API with classification-on-read (pg_net)**
PostgREST exposes a PL/pgSQL function that returns readings by TBox type. Building context comes from JWT claims (injected by Zitadel Actions), not API parameters. On access, automatically triggers classification if no RawTag is classified to the requested type.

```sql
-- Enable pg_net extension for async HTTP
CREATE EXTENSION IF NOT EXISTS pg_net;

-- Read data API function (exposed via PostgREST)
CREATE OR REPLACE FUNCTION get_readings_by_type(
    p_tbox_type text,
    p_start timestamptz DEFAULT now() - interval '1 hour',
    p_end timestamptz DEFAULT now()
) RETURNS jsonb AS $
DECLARE
    v_building_id text;
    has_classification boolean;
    rawtag_ids text[];
BEGIN
    -- Extract building_id from JWT claims (set by PostgREST from Authorization header)
    v_building_id := current_setting('request.jwt.claims', true)::jsonb->>'building_id';

    -- Check if any RawTag is classified to this TBox type (approved)
    SELECT EXISTS (
        SELECT 1 FROM cypher('platform', $$
            MATCH (r:RawTag)-[e:IS_TYPE_OF]->(p:PropertyDef)
            WHERE r.building_id = '$$ || v_building_id || $$'
              AND p.name = '$$ || p_tbox_type || $$'
              AND e.status = 'approved'
            RETURN r.id
        $$) AS (id agtype)
    ) INTO has_classification;

    -- Trigger classifier if no classification exists (async, non-blocking)
    IF NOT has_classification THEN
        PERFORM net.http_post(
            url := 'http://restate:8180/classifier/' ||
                   encode(v_building_id || ':' || p_tbox_type, 'base64') || '/run',
            body := jsonb_build_object(
                'building_id', v_building_id,
                'tbox_types', ARRAY[p_tbox_type]
            ),
            headers := '{"Content-Type": "application/json"}'::jsonb
        );

        RETURN jsonb_build_object(
            'status', 'classification_pending',
            'message', 'No classification found for ' || p_tbox_type || '. Classifier triggered.',
            'data', '[]'::jsonb
        );
    END IF;

    -- Get classified RawTag IDs
    SELECT array_agg(id::text) INTO rawtag_ids
    FROM cypher('platform', $$
        MATCH (r:RawTag)-[e:IS_TYPE_OF]->(p:PropertyDef)
        WHERE r.building_id = '$$ || v_building_id || $$'
          AND p.name = '$$ || p_tbox_type || $$'
          AND e.status = 'approved'
        RETURN r.id
    $$) AS (id agtype);

    -- Return readings from TimescaleDB
    RETURN jsonb_build_object(
        'status', 'ok',
        'tbox_type', p_tbox_type,
        'data', (
            SELECT jsonb_agg(jsonb_build_object(
                'time', time,
                'value', value,
                'rawtag_id', rawtag_id
            ))
            FROM readings
            WHERE rawtag_id = ANY(rawtag_ids)
              AND time BETWEEN p_start AND p_end
            ORDER BY time DESC
        )
    );
END;
$ LANGUAGE plpgsql;
```

Flow:
1. Client calls `GET /rpc/get_readings_by_type?p_tbox_type=SupplyAirTemp` with JWT in Authorization header
2. Function extracts building_id from JWT claims (no business params in API)
3. Checks: any RawTag classified to SupplyAirTemp for this building?
4. If no → pg_net fires async POST to Restate classifier → returns `classification_pending`
5. Human approves proposals → next call returns actual readings

```
Verifiable: Call PostgREST RPC for unconfigured type (with valid JWT)
            → Returns {"status": "classification_pending"}
            → Classifier workflow started (check Restate UI)
            → Approve proposals
            → Call again → Returns readings data
```

**Step 7 — Unified events (provenance / logging / audit)**
Four chokepoints emit events into a single `evoiot.events` table. E2E test seeds data via MQTT (not direct DB insert) so the full Bento → Postgres → Restate → Postgres chain is exercised and every step is recorded.

```
Implementation:
  1. events table + emit_event() trigger on relational tables (readings, data_sources)
  2. upsert_rawtag() emits graph mutation events
  3. execute_cypher() wrapper emits graph mutation events
  4. traced_run() wrapper for Restate ctx.run()
  5. Bento branch+sql_raw processor emits mqtt_receive events
  6. E2E test: seed via MQTT, verify provenance chain in events table

Verifiable: run classification-on-read e2e test
            → query events WHERE data_id = rawtag_id ORDER BY timestamp
            → full chain: mqtt_receive → rawtag_upsert → reading_insert
              → workflow_start → llm_classify → proposal_create
              → human_approve → status_update
            → no gaps
```

**Step 8 — Auth**
JWT flow wired. PostgREST validates tokens. RLS enforces building isolation. Zitadel Actions inject building_id claim. MQTT ACL enabled.

```
Verifiable: login required
            user from building A cannot see building B data
```

**Step 9 — Read lens**
Postgres functions for gap fill, drift correction, confidence scoring. `read_lens_config` seeded with defaults. PostgREST exposes lens functions as RPC. App switches from raw to lens-filtered readings.

```
Verifiable: sensor gap shows interpolated values with lower confidence
            drift offset applied transparently
```

**Step 10 — Rules engine**
Platform default rules seeded. Bento scheduled pipeline evaluates `rules` table every 5 minutes against TimescaleDB. Alerts written to `alerts` table. App shows alert list.

```
Verifiable: set sensor above threshold → alert appears in UI
```

**Step 11 — Command dispatch**
Restate CommandObject workflow. Paho publishes to edge agent via Mosquitto. Edge agent executes BACnet WriteProperty. Ack returns via Bento → Restate awakeable. App sends setpoint command.

```
Verifiable: UI sends command → physical device changes → ack recorded
```

**Step 12 — Workflow templates**
`workflow_templates` and `workflow_configs` seeded. Alert lifecycle workflow in Restate — alert fires → maintenance task → assigned → sign-off → resolved. App shows workflow inbox.

```
Verifiable: alert triggers maintenance task, operator signs off
            full lifecycle recorded in audit log
```

**Step 13 — External context data**
Bento HTTP pipeline templates for weather, electricity rates. Platform default `data_sources` seeded. Context readings flowing into `readings` table (device_id=null, scope='global'/'building').

```
Verifiable: outdoor_temperature visible alongside sensor data
            electricity rate referenceable in rules
```

**Step 14 — User-defined data sources**
App UI to register a new HTTP data source. Bento watcher dynamically spawns pipeline. Data flows immediately as unclassified. When user adds data to dashboard or queries it, AI classification triggers. Human approves. Custom data becomes semantically queryable.

```
Verifiable: user registers API → data flows (unclassified)
            user adds to dashboard → AI proposes classification → approved
```

**Step 15 — User-defined rules**
App UI to add custom rule — pick point type, threshold, device, notify. PostgREST INSERT into rules (source='user'). Bento evaluates on next cycle.

```
Verifiable: user rule fires independently of platform defaults
```

**Step 16 — Multi-building**
Second building, second edge agent, same platform. Building isolation verified. Deployment Mode 2 docker-compose variant written.

```
Verifiable: two buildings fully isolated
            each building's users see only their own data
```
