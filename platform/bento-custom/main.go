package main

import (
	"context"

	_ "github.com/warpstreamlabs/bento/public/components/all"

	// Register our custom emit_event processor plugin
	_ "evoiot-bento/pgtracer"

	"github.com/warpstreamlabs/bento/public/service"
)

func main() {
	service.RunCLI(context.Background())
}
