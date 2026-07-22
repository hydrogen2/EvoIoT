#!/bin/sh
set -e

RESTATE_ADMIN_URL="${RESTATE_ADMIN_URL:-http://restate:9070}"
SERVICE_URL="${SERVICE_URL:-http://workflows:9080}"

# Collector SSH transport: bind-mounted key has host ownership/perms that ssh
# rejects; copy it into place owned by this user with 600.
if [ -f /etc/collector/id_ed25519 ]; then
    mkdir -p /root/.ssh && chmod 700 /root/.ssh
    cp /etc/collector/id_ed25519 /root/.ssh/id_ed25519 && chmod 600 /root/.ssh/id_ed25519
    [ -f /etc/collector/ssh_config ] && cp /etc/collector/ssh_config /root/.ssh/config
    touch /root/.ssh/known_hosts && chmod 644 /root/.ssh/known_hosts
    echo "Collector SSH key installed"
fi

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
