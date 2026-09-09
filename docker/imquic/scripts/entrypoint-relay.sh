#!/bin/bash
set -euo pipefail

PORT="${MOQ_RELAY_PORT:-4443}"
CERT="${MOQ_CERT:-/certs/cert.pem}"
KEY="${MOQ_KEY:-/certs/priv.key}"
MLOG_DIR="${MOQ_MLOG_DIR:-/mlog}"
DRAFT="${MOQ_DRAFT:-any}"

echo "Starting imquic-moq-relay on port $PORT"
echo "  Cert: $CERT"
echo "  Key:  $KEY"
echo "  Draft: $DRAFT"

if [ ! -f "$CERT" ]; then
    echo "ERROR: Certificate not found at $CERT" >&2
    exit 1
fi
if [ ! -f "$KEY" ]; then
    echo "ERROR: Private key not found at $KEY" >&2
    exit 1
fi

mkdir -p "$MLOG_DIR"

ldd /usr/local/bin/imquic-moq-relay 2>&1 || true
echo "---"

imquic-moq-relay \
    -p "$PORT" -q -w \
    -c "$CERT" \
    -k "$KEY" \
    -M "$DRAFT" 2>&1

exit_code=$?
echo "Relay exited with code: $exit_code" >&2
exit $exit_code