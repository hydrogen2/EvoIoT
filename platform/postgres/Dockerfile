FROM timescale/timescaledb:latest-pg16

# Install build dependencies for Apache AGE and pg_net
RUN apk add --no-cache --virtual .build-deps \
        git \
        make \
        gcc \
        musl-dev \
        clang19 \
        llvm19-dev \
        flex \
        bison \
        perl \
        curl-dev \
        icu-dev && \
    # Keep runtime libraries
    apk add --no-cache libcurl icu-libs && \
    # Clone and build AGE
    git clone --branch release/PG16/1.5.0 --depth 1 \
        https://github.com/apache/age.git /tmp/age && \
    cd /tmp/age && \
    make USE_PGXS=1 install && \
    cd / && rm -rf /tmp/age && \
    # Clone and build pg_net (main branch for newer GCC compatibility)
    git clone --depth 1 \
        https://github.com/supabase/pg_net.git /tmp/pg_net && \
    cd /tmp/pg_net && \
    make USE_PGXS=1 WERROR_FLAGS= install && \
    cd / && rm -rf /tmp/pg_net && \
    # Cleanup build deps
    apk del .build-deps
