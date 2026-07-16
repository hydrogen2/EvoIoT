# Build the custom Bento binary (forked Bento + pg_events tracer plugin)
# inside Docker so no host Go toolchain is required.
# CGO disabled to match upstream's static release builds.
FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY main.go ./
COPY pgtracer ./pgtracer
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -o /out/bento .

FROM ghcr.io/warpstreamlabs/bento:latest
COPY --from=build /out/bento /bento
ENTRYPOINT ["/bento"]
