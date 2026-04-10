package pgtracer

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"strings"

	_ "github.com/lib/pq"
	tracesdk "go.opentelemetry.io/otel/sdk/trace"
)

// pgExporter implements tracesdk.SpanExporter, writing spans to evoiot.events.
type pgExporter struct {
	db       *sql.DB
	prefixes []string
}

func newPGExporter(dsn string, prefixes []string) (*pgExporter, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("pg_events tracer: %w", err)
	}
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("pg_events tracer ping: %w", err)
	}
	return &pgExporter{db: db, prefixes: prefixes}, nil
}

func (e *pgExporter) ExportSpans(ctx context.Context, spans []tracesdk.ReadOnlySpan) error {
	for _, s := range spans {
		name := s.Name()

		// Filter: only keep spans matching configured prefixes
		if !e.matchPrefix(name) {
			continue
		}

		// Extract data_id and message content from span attributes
		var dataID *string
		var messageContent string
		attrs := map[string]string{}
		for _, attr := range s.Attributes() {
			key := string(attr.Key)
			val := attr.Value.AsString()
			switch key {
			case "data_id":
				dataID = &val
			case "message.content":
				messageContent = val
			default:
				attrs[key] = val
			}
		}

		// Build payload
		payload := map[string]any{
			"duration_ms": float64(s.EndTime().Sub(s.StartTime()).Microseconds()) / 1000.0,
		}
		if messageContent != "" {
			// Try to parse as JSON for structured storage
			var structured any
			if err := json.Unmarshal([]byte(messageContent), &structured); err == nil {
				payload["data"] = structured
			} else {
				payload["data"] = messageContent
			}
		}
		if len(attrs) > 0 {
			payload["attributes"] = attrs
		}

		payloadJSON, _ := json.Marshal(payload)
		traceID := s.SpanContext().TraceID().String()
		eventTime := s.StartTime()

		_, err := e.db.ExecContext(ctx,
			`INSERT INTO evoiot.events (event_time, component, operation, data_id, trace_id, actor, payload)
			 VALUES ($1, 'bento', $2, $3, $4, 'bento', $5)`,
			eventTime, name, dataID, traceID, string(payloadJSON),
		)
		if err != nil {
			fmt.Printf("pg_events tracer: insert error: %v\n", err)
		}
	}
	return nil
}

func (e *pgExporter) Shutdown(ctx context.Context) error {
	return e.db.Close()
}

func (e *pgExporter) matchPrefix(name string) bool {
	for _, p := range e.prefixes {
		if strings.HasPrefix(name, p) {
			return true
		}
	}
	return false
}
