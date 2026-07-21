# Pinned: the latest-pg16 tag moves and has repeatedly broken rebuilds
# (clang version drift, surprise multi-GB pulls). Matches the deployed stack.
FROM timescale/timescaledb:2.28.2-pg16

# Install build dependencies for Apache AGE and pg_net
# with_llvm=no skips LLVM JIT bitcode generation, which would require the exact
# clang version the base image's Postgres was built with (a moving target on
# the :latest-pg16 tag)
RUN apk add --no-cache --virtual .build-deps \
        git \
        make \
        gcc \
        musl-dev \
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
    make USE_PGXS=1 with_llvm=no install && \
    cd / && rm -rf /tmp/age && \
    # Clone and build pg_net (main branch for newer GCC compatibility)
    git clone --depth 1 \
        https://github.com/supabase/pg_net.git /tmp/pg_net && \
    cd /tmp/pg_net && \
    make USE_PGXS=1 WERROR_FLAGS= with_llvm=no install && \
    cd / && rm -rf /tmp/pg_net && \
    # Cleanup build deps
    apk del .build-deps
