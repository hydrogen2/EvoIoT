#!/bin/bash
# Register workflows service with Restate
# Run this after docker-compose up

set -e

RESTATE_ADMIN_URL=${RESTATE_ADMIN_URL:-http://localhost:9070}
WORKFLOWS_URL=${WORKFLOWS_URL:-http://workflows:9080}

echo "Waiting for Restate admin to be ready..."
until curl -sf "${RESTATE_ADMIN_URL}/health" > /dev/null 2>&1; do
    sleep 1
done

echo "Registering workflows service with Restate..."
curl -X POST "${RESTATE_ADMIN_URL}/deployments" \
    -H "Content-Type: application/json" \
    -d "{\"uri\": \"${WORKFLOWS_URL}\"}"

echo ""
echo "Done! Workflows service registered."
echo ""
echo "To verify, run:"
echo "  curl ${RESTATE_ADMIN_URL}/deployments"
