#!/bin/bash
set -uo pipefail

ROLE="${MOQ_ROLE:-pub}"
RELAY_HOST="${MOQ_RELAY_HOST:?MOQ_RELAY_HOST is required}"
RELAY_PORT="${MOQ_RELAY_PORT:-4443}"
STREAM_NAME="${MOQ_STREAM_NAME:-test-stream}"
DRAFT="${MOQ_DRAFT:-any}"

if [ "$ROLE" = "pub" ]; then
    exec imquic-moq-pub \
        -r "${RELAY_HOST}" -R "${RELAY_PORT}" \
        -q -w -S localhost \
        -c /certs/cert.pem \
        -n / -N "${STREAM_NAME}" \
        -M "${DRAFT}"
elif [ "$ROLE" = "sub" ]; then
    exec imquic-moq-sub \
        -r "${RELAY_HOST}" -R "${RELAY_PORT}" \
        -q -w -S localhost \
        -c /certs/cert.pem \
        -n / -N "${STREAM_NAME}" \
        -t hex \
        -M "${DRAFT}"
else
    echo "Unknown role: $ROLE"
    exit 1
fi