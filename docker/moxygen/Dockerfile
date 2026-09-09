ARG MXY_TAG=latest-amd64
ARG BASE_IMAGE=ghcr.io/facebookexperimental/moqrelay

FROM ${BASE_IMAGE}:${MXY_TAG}

# iproute2 provides tc for Containernet link impairments (applied via docker
# exec). The upstream moqrelay image is Ubuntu-based, so apt works here.
# tcpdump: B3 (see found-bugs.md) — per-container packet capture.
RUN apt-get update && apt-get install -y iproute2 tcpdump && rm -rf /var/lib/apt/lists/*

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
