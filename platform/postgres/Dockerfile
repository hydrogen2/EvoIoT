FROM timescale/timescaledb:latest-pg16

# Install build dependencies for Apache AGE
RUN apk add --no-cache --virtual .build-deps \
        git \
        make \
        gcc \
        musl-dev \
        clang19 \
        llvm19-dev \
        flex \
        bison \
        perl && \
    # Clone and build AGE
    git clone --branch release/PG16/1.5.0 --depth 1 \
        https://github.com/apache/age.git /tmp/age && \
    cd /tmp/age && \
    make USE_PGXS=1 install && \
    # Cleanup
    rm -rf /tmp/age && \
    apk del .build-deps
