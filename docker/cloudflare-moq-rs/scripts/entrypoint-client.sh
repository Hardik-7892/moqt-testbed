#!/bin/bash
set -e

ROLE="${MOQ_ROLE:-pub}"
RELAY_HOST="${MOQ_RELAY_HOST:?MOQ_RELAY_HOST is required}"
RELAY_PORT="${MOQ_RELAY_PORT:-4443}"
STREAM_NAME="${MOQ_STREAM_NAME:-test-stream}"

if [ "$ROLE" = "pub" ]; then
    exec moq-pub --name "${STREAM_NAME}" --tls-disable-verify "https://${RELAY_HOST}:${RELAY_PORT}"
elif [ "$ROLE" = "sub" ]; then
    exec moq-sub --name "${STREAM_NAME}" --tls-disable-verify "https://${RELAY_HOST}:${RELAY_PORT}"
else
    echo "Unknown role: $ROLE"
    exit 1
fi
