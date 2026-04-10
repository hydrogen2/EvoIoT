// Package pgtracer registers a custom Bento tracer that writes span events
// directly to PostgreSQL evoiot.events table. Combined with the forked Bento
// that injects message.content into span attributes, this captures both
// timing and message data for every processor in every pipeline.
package pgtracer

import (
	"github.com/warpstreamlabs/bento/public/service"
	"go.opentelemetry.io/otel/trace"

	tracesdk "go.opentelemetry.io/otel/sdk/trace"
)

func init() {
	spec := service.NewConfigSpec().
		Summary("Writes trace spans with message content directly to PostgreSQL evoiot.events table.").
		Field(service.NewStringField("dsn").
			Description("PostgreSQL connection string.").
			Default("postgres://bento_writer:bento_dev_password@postgres:5432/postgres?sslmode=disable")).
		Field(service.NewStringListField("keep_prefixes").
			Description("Only keep spans with these name prefixes.").
			Default([]any{"input_", "output_"}))

	err := service.RegisterOtelTracerProvider("pg_events", spec,
		func(conf *service.ParsedConfig) (trace.TracerProvider, error) {
			dsn, err := conf.FieldString("dsn")
			if err != nil {
				return nil, err
			}

			prefixes, err := conf.FieldStringList("keep_prefixes")
			if err != nil {
				return nil, err
			}

			exporter, err := newPGExporter(dsn, prefixes)
			if err != nil {
				return nil, err
			}

			return tracesdk.NewTracerProvider(
				tracesdk.WithBatcher(exporter),
			), nil
		})
	if err != nil {
		panic(err)
	}
}
