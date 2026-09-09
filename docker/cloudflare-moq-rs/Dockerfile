ARG DRAFT=18

FROM rust:1.97-slim-bookworm AS builder

ARG DRAFT

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git ca-certificates pkg-config libssl-dev && \
    rm -rf /var/lib/apt/lists/*

RUN case ${DRAFT} in \
        18) COMMIT="52b8a905e4075da5bfa8465b3d39216c66ab8bc2" ;; \
        16) COMMIT="2d16c9c8070ca6d80fed6ed21bd6fa60489a9ced" ;; \
        14) COMMIT="37e636e73d99d54f5d9bc394ead38b6d5fb45415" ;; \
        *) echo "Unsupported draft: ${DRAFT}. Use 14, 16 or 18."; exit 1 ;; \
    esac && \
    git init moq-rs && \
    cd moq-rs && \
    git remote add origin https://github.com/cloudflare/moq-rs.git && \
    git fetch --depth 1 origin ${COMMIT} && \
    git checkout FETCH_HEAD && \
    cargo build --release --bin moq-relay-ietf --bin moq-pub --bin moq-sub && \
    { cargo build --release --bin moq-test-client 2>/dev/null || true; } && \
    mkdir -p /output && \
    cp target/release/moq-relay-ietf /output/ && \
    cp target/release/moq-pub /output/ && \
    cp target/release/moq-sub /output/ && \
    if [ -f target/release/moq-test-client ]; then \
        cp target/release/moq-test-client /output/; \
    fi

FROM debian:bookworm-slim

# iproute2 provides `tc`: Containernet applies link impairments (TCLink
# bw/delay/loss) via tc INSIDE the container, so the image must ship it.
# tcpdump: B3 (see found-bugs.md) — per-container packet capture.
RUN apt update && DEBIAN_FRONTEND=noninteractive apt install -y ca-certificates iproute2 tcpdump && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /output/* /usr/local/bin/

RUN mkdir -p /certs /qlogs /data /output

EXPOSE 4443/udp 4443/tcp

COPY scripts/entrypoint-relay.sh /entrypoint-relay.sh
RUN chmod +x /entrypoint-relay.sh

COPY scripts/entrypoint-client.sh /entrypoint-client.sh
RUN chmod +x /entrypoint-client.sh

ENTRYPOINT ["/entrypoint-relay.sh"]
