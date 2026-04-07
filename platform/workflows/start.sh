#!/bin/sh
set -e

RESTATE_ADMIN_URL="${RESTATE_ADMIN_URL:-http://restate:9070}"
SERVICE_URL="${SERVICE_URL:-http://workflows:9080}"

# Start hypercorn in background
python -m hypercorn main:app --bind 0.0.0.0:9080 &
PID=$!

# Wait for service to be ready
echo "Waiting for workflow service to start..."
for i in $(seq 1 30); do
    if curl -s http://localhost:9080/health > /dev/null 2>&1 || curl -s http://localhost:9080 > /dev/null 2>&1; then
        echo "Workflow service is ready"
        break
    fi
    sleep 1
done

# Register with Restate
echo "Registering with Restate at $RESTATE_ADMIN_URL..."
for i in $(seq 1 10); do
    RESPONSE=$(curl -s -X POST "$RESTATE_ADMIN_URL/deployments" \
        -H "Content-Type: application/json" \
        -d "{\"uri\":\"$SERVICE_URL\"}" 2>&1) || true

    if echo "$RESPONSE" | grep -q '"id"'; then
        echo "Successfully registered with Restate"
        break
    elif echo "$RESPONSE" | grep -q 'already exists'; then
        echo "Already registered with Restate"
        break
    else
        echo "Registration attempt $i failed: $RESPONSE"
        sleep 2
    fi
done

# Keep the main process in foreground
wait $PID
