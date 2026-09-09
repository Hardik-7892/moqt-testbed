#!/bin/bash
set -e

ROLE="${MOQ_ROLE:-relay}"
RELAY_URL="${MOQ_RELAY_URL:-https://[::]:9448/moq}"
STREAM_NAME="${MOQ_STREAM_NAME:-test-stream}"
CONTENT_FILE="${MOQ_CONTENT_FILE:-/data/sample.flv}"
OUTPUT_DIR="${MOQ_OUTPUT_DIR:-/output}"

if [ "$ROLE" = "relay" ]; then
    ARGS=""
    if [ -n "${MOQ_VERSIONS:-}" ]; then
        ARGS="$ARGS --versions $MOQ_VERSIONS"
    fi
    exec moqrelayserver -port "${MOQ_PORT:-9448}" -cert "${CERT_FILE:-/certs/certificate.pem}" -key "${KEY_FILE:-/certs/certificate.key}" -endpoint "${MOQ_ENDPOINT:-/moq}" --logging "${MOQ_LOG_LEVEL:-DBG1}" $ARGS
elif [ "$ROLE" = "pub" ]; then
    # MoQFlvStreamerClient: publish an FLV (h264/AAC-LC) via MoQMI to tracks
    # video0/audio0 under the given namespace.
    exec moqflvstreamerclient --insecure --input_flv_file "${CONTENT_FILE}" --connect_url "${RELAY_URL}" --track_namespace "${STREAM_NAME}" --logging "${MOQ_LOG_LEVEL:-DBG1}"
elif [ "$ROLE" = "sub" ]; then
    # MoQFlvReceiverClient: subscribe to video0/audio0 under the namespace,
    # demux MoQMI and transmux to an FLV file.
    exec moqflvreceiverclient --insecure --flv_outpath "${OUTPUT_DIR}/${STREAM_NAME}.flv" --connect_url "${RELAY_URL}" --track_namespace "${STREAM_NAME}" --logging "${MOQ_LOG_LEVEL:-DBG1}"
else
    echo "Unknown role: $ROLE"
    exit 1
fi
