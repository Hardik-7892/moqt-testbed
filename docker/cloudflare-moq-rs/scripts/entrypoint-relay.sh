#!/bin/bash
set -e

RELAY_BIND="${MOQ_RELAY_BIND:-[::]:4443}"
TLS_CERT="${MOQ_TLS_CERT:-/certs/cert.pem}"
TLS_KEY="${MOQ_TLS_KEY:-/certs/key.pem}"
QLOG_DIR="${MOQ_QLOG_DIR:-/qlogs}"
MLOG_DIR="${MOQ_MLOG_DIR:-/qlogs}"

# The relay refuses to start if the qlog/mlog directories do not exist.
mkdir -p "${QLOG_DIR}" "${MLOG_DIR}"

# Only fill in a flag when the caller did not already supply it on the
# command line (args appended to the image ENTRYPOINT), so `docker run
# img --mlog-dir /x ...` works without duplicating the option.
has_arg() {
  local flag="$1"
  shift
  for a in "$@"; do
    case "$a" in
      "${flag}"|"${flag}"=*) return 0 ;;
    esac
  done
  return 1
}

ARGS=()
has_arg --bind "$@" || ARGS+=(--bind "${RELAY_BIND}")
has_arg --tls-cert "$@" || ARGS+=(--tls-cert "${TLS_CERT}")
has_arg --tls-key "$@" || ARGS+=(--tls-key "${TLS_KEY}")
has_arg --qlog-dir "$@" || ARGS+=(--qlog-dir "${QLOG_DIR}")
has_arg --mlog-dir "$@" || ARGS+=(--mlog-dir "${MLOG_DIR}")

exec moq-relay-ietf "${ARGS[@]}" "$@"