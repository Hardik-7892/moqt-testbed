# 02 — Registry, Implementations, and Build-Time Limits (Ch5 §5.1 + §5.6)

## 2.1 Registry as single source of truth

`registry.json` is the machine-readable contract; `IMPLEMENTATION_REGISTRY.md` is the human companion. Every run resolves images, entrypoints, ports, cert aliases, and artifact contracts from it — there is no second source. Docker entrypoint scripts were rewritten to align with it (B9, `found-bugs.md:220-239`).

Per-implementation schema:

- `image{relay,client}` with `{draft}` substitution, `source`, `roles`, `claimed_drafts`, `negotiated_drafts` (null = unverified, B15), `entrypoints{relay,pub,sub}` with `{relay,port,stream,dir,file,draft,path,join_delay}` placeholders filled by `_fill_entrypoint` (`harness/runner.py:1197-1200`), `sub_output{file,stdout_is_data,logs_on_stdout,playable}`, `cert_aliases`, `port`, `client_path` (moxygen only), `notes`.

## 2.2 Enabled implementations

### moq-rs (Cloudflare, Rust quiche+tokio, drafts 14/16/18)

Images: `moq-rs/relay:{14,16,18}` + `moq-rs/client` + `0hardikpandey/moq-rs-{relay,client}:{draft}` via `for d in 14 16 18` (`Makefile:98-110`, `registry.json:8-11,18-22`). Port 4443 (`registry.json:37`).

Entrypoints (`registry.json:26-28`): relay `moq-relay-ietf --bind [::]:4443 --tls-cert /certs/cert.pem --tls-key /certs/key.pem --qlog-dir /qlogs --mlog-dir /qlogs`; pub `moq-pub --name {stream} --tls-disable-verify https://{relay}:{port}{path}`; sub `moq-sub --name {stream} --tls-disable-verify https://{relay}:{port}{path}`.

Build: each draft pins a different commit via `case ${DRAFT}` (`18→52b8a90…`, `16→2d16c9c…`, `14→37e636e…`, `docker/cloudflare-moq-rs/Dockerfile:11-15`); builds `moq-relay-ietf/moq-pub/moq-sub` + optional `moq-test-client` (`Dockerfile:22-30`); ships `iproute2+tcpdump` for TCLink + capture (`Dockerfile:34-38`). Relay writes JSON-SEQ qlog/mlog per connection; pub/sub rely on relay server qlog; honours `SSLKEYLOGFILE` (`registry.json:38`, verified `run_20260818_181221`).

Artifact contract: `file /output/{stream}`, `stdout_is_data true` (no `--output` at old pin; media is stdout), `logs_on_stdout ansi_timestamp`, `playable strip_ansi ext mp4 reconstruct true` (`registry.json:30-35`). Requires fragmented MP4 (`empty_moov+frag_keyframe+separate_moof`); Blender M4V `ftypM4V` fails `hdlr size too small` then `missing moof` (B22). No flow-control knobs, no archive/backfill, no pacing flag at measured pins (`found-bugs.md:703-707,1485-1499`).

History: large-file relay delivery broken at `a6ed4e9` (B25 deferred), fixed by repin to `2d16c9c8` for sample (`99.15% good`), current `18` pin `52b8a90…` (`docker/cloudflare-moq-rs/Dockerfile:12`).

### moxygen (Meta, C++ mvfst/proxygen, drafts 14/16/18 claimed)

Images: `0hardikpandey/moxygen-{client,relay}:latest` source-built then retagged to `:14,:16,:18` identical bits + `moxygen/{client,relay}:{draft}` aliases (`Makefile:112-132`). Pins `MXY_COMMIT 4095b18…` (`Makefile:17`), `MXY_PROXYGEN 3ad19ac…` (`Makefile:21`, fixes `onWebTransportUniStream` UAF `openmoq/moqx#403`). Relay `FROM` fixed client image so server runs fixed proxygen (`docker/moxygen/Dockerfile.relay:18`). Port 9448 + `client_path /moq` (`registry.json:75-76`).

Entrypoints (`registry.json:62-64`): relay `moqrelayserver -port {port} -cert /certs/certificate.pem -key /certs/certificate.key -endpoint /moq`; pub `moqflvstreamerclient --insecure --input_flv_file {file} --connect_url https://{relay}:{port}/moq --track_namespace {stream} --logging DBG1`; sub `moqflvreceiverclient --insecure --flv_outpath {dir}/{stream}.flv --connect_url https://{relay}:{port}/moq --track_namespace {stream} --logging DBG1`.

Build limits: official images ship only `moqrelayserver/moq_interop_client`; FLV clients must be source-built via `docker/moxygen/Dockerfile.media` (`registry.json:77`, `IMPLEMENTATION_REGISTRY.md:69-70`); depth-1 fetch at `MXY_COMMIT` (`Dockerfile.media:80-85`); patches for `BUILD_SAMPLES=OFF`, mvfst timestamp, `drain()` race, `publishLoop` mutex; BuildKit cache mount required (`Makefile:115`). Media FLV `h264/AAC-LC` via MoQMI; byte compare approximate transmux, never exact. `sub_output file /output/{stream}.flv stdout_is_data false playable copy ext flv` (`registry.json:66-70`). Certs `certificate.pem/key` aliases (`registry.json:71-74`).

Draft honesty: claims UNVERIFIED `boot` (`registry.json:77`); WT CH ALPN `h3`, raw never offers `moqt-18`, no `--versions` at pin (B46, `found-bugs.md:1503-1533`). Do not trust `d18` label — most likely 16.

### imquic (Meetecho, C picoquic, drafts 16/17/18/19)

Images: `imquic/relay:{16,17,18,19}` + `imquic/cli` + `0hardikpandey/imquic-{relay,cli}` via loop (`Makefile:134-150`). Port 4443 (`registry.json:114`).

Entrypoints (`registry.json:102-104`): relay `imquic-moq-relay -p 4443 -q -w -c /certs/cert.pem -k /certs/priv.key -Q /qlogs -l quic -s /keys/sslkeys.log`; pub `imquic-moq-pub -r {relay} -R {port} -M {draft} -q -w -S localhost -c /certs/cert.pem -n / -N {stream} -Q /qlogs -l quic -s /keys/sslkeys.log`; sub same + `-t hex`.

Critical nuance — **runtime, not build-time**: all four tags build same commits `picoquic 0dbd19d… + imquic 1f4cbf8…` (`docker/imquic/Dockerfile.relay:13-29`); `ARG DRAFT` only sets `ENV MOQ_DRAFT` consumed as `-M` at runtime (`Dockerfile.relay:33-34`, `scripts/entrypoint-relay.sh:8-33`). B4 reclassified NOT A BUG: no `--enable-moq-version` flag exists; selection is `-M 18` vs `-M any` (default `any` offers all four ALPNs, `found-bugs.md:130-140`).

Runner pins sub/pub via `-M {draft}`; relay deliberately UNPINNED (pinning advertises only `moqt-18` and rejects moq-rs with `close 271`; `any` accepts per-connection, `registry.json:115`, `harness/runner.py:883-888`). With `any`, sub silently negotiates `moqt-19` even on `d18` row — pinning makes the row honest.

Demo `moq-pub` is a timestamp clock generator (1 obj/s, no media ingest, `IMPLEMENTATION_REGISTRY.md:84-86`); excluded from media rows, valid as relay/sub. `-t hex` required (`%02x` per byte); `-t none` gives only `Incoming object:` metadata, `text` truncates at NUL (`found-bugs.md:459-470`). `sub_output file /output/{stream} stdout_is_data true playable hex_decode ext mp4` (`registry.json:106-110`). Cert alias `priv.key→key.pem`. Qlogs `*.server.qlog/*.client.qlog title picoquic`, RTT in µs vs moq-rs/quinn seconds.

### LL-DASH baselines (H2 nginx + H3 caddy, Python client)

`lldash-h2` (`registry.json:118-148`): `0hardikpandey/lldash-origin-h2/client-h2:latest` via `Dockerfile.origin.h2 + Dockerfile.client` (`Makefile:180-189`); relay `nginx -g 'daemon off;'`; pub no-op `cat {file} + sleep 1`; sub `client.py --protocol h2 --join-delay {join_delay}`; port 443; origin `nginx:alpine http2 443` with harness certs; client `httpx[http2]+h2`; 2 s segment = 2 s MoQ group; TTFO via `time_to_first_chunk_ms`.

`lldash-h3` (`registry.json:150-181`): same via `Dockerfile.origin.h3` (`Makefile:191-200`); relay `caddy run --config /etc/caddy/Caddyfile`; origin `caddy:alpine h3 443/udp` + `SSLKEYLOGFILE`; Caddyfile `:443 tls … root * /data file_server`; client `aioquic/httpx fallback`; tries `curl --http3-only` first, then TCP, labelling each segment `via h3 / via tcp-fallback` (D13).

## 2.3 cert_aliases, entrypoint alignment, tag-skew

- **cert_aliases** (`IMPLEMENTATION_REGISTRY.md:6-15`): key = expected filename, value = generated source. moxygen `certificate.pem/key`, imquic `priv.key`. `harness/certs.py:99-121` generates base pair (prefers `cryptography`, falls back to `openssl`) idempotently, then copies aliases. Runner (`setup_dirs` via `_relay_cert_aliases`, `harness/runner.py:218-225`) and probe (`_gen_cert`, `harness/probe.py:18-23`) share it (B6 fix).
- **B9**: Docker scripts rewritten to match registry canonical entrypoints (moq-rs TLS/qlog flags, `--server`→positional URL, imquic proper `-r -R -q -w -S -c -n -N -t hex).
- **B36 tag-skew**: `Makefile || true` removed, `harness/runner.py:591 _verify_image_tags` fails fast on Hub-vs-local ID mismatch, `testplans/bbb.yaml` re-pointed to local `moq-rs/*:18`. Phase-4 script re-tags before headline rows (`evaluation_tests/phase4_baselines.sh:34-37`).

## 2.4 Disabled / excluded (honest scope limits for Ch5 §5.6)

`disabled_implementations` (`registry.json:184-306`): moqtail (d16, `ghcr.io/moqtail/relay:latest`, WebTransport+raw QUIC, d18 milestone unmerged), moq-dev (d18 claimed but default `moq-lite` private protocol, needs `MOQ_MODE=ietf/--ietf`, otherwise invalid), quiche-moq (Google, C++ Bazel, d16, relay-only in practice, heavy build), moq-go (candidate, d18/19, placeholders `moq-go-relay:19`, unbuilt). Gate: `negotiated_drafts null` (B15, `found-bugs.md:344-352`) — unverified, may not build.

Never promoted: `aiomoqt` (Python, out of scope), `moqtransport TUM` (d13 too old), `floatdrop/moq-go` (low maturity), `dineshadhi/moq-go` (d4 stale), `gomoqt` (moq-lite subset), `birneee/quiche_moq` (personal) (`IMPLEMENTATION_REGISTRY.md:218-227`).

Ch5 sentence: “Scope is moq-rs + imquic (relay/sub) + moxygen (FLV relay) at draft-18 pins; four others remain disabled as unverified nulls — not failures, but explicit non-claims.”
