# MoQT Implementation Registry

Single source of truth for all implementations, their draft support, Docker images, and entry points.
Machine-readable version: `registry.json`

## Adding an implementation: `cert_aliases` convention

When you add an implementation whose relay uses non-standard certificate
filenames (anything other than `/certs/cert.pem` + `/certs/key.pem`), declare
them under a `cert_aliases` map in `registry.json` — key = the filename the
relay expects, value = which generated file it is a copy of. Example:
moxygen uses `{"certificate.pem": "cert.pem", "certificate.key": "key.pem"}`
and imquic uses `{"priv.key": "key.pem"}`. The harness (`harness/certs.py`)
reads this map so the runner and the probe provision exactly the cert files
each implementation's relay needs. See `found-bugs.md` B6.

---

## moq-rs (Cloudflare)

| Field | Value |
|---|---|
| Source | https://github.com/cloudflare/moq-rs |
| Language | Rust |
| Drafts | 16, 18 |
| Roles | relay, pub, sub |
| Default port | 4443 |

### Docker Images

| Tag | Draft | Branch |
|---|---|---|
| `moq-rs/relay:18` | 18 | `main` |
| `moq-rs/client:18` | 18 | `main` |
| `moq-rs/relay:16` | 16 | `draft-16` |

### Entry Points

- **relay:** `moq-relay-ietf --bind [::]:4443 --tls-cert /certs/cert.pem --tls-key /certs/key.pem`
- **pub:** `moq-pub --server <url> --name <stream> --input <file>`
- **sub:** `moq-sub --server <url> --name <stream> --output <dir>`

---

## moxygen (Meta)

| Field | Value |
|---|---|
| Source | https://github.com/facebookincubator/moxygen |
| Language | C++ (mvfst-based) |
| Drafts | 14, 16, 18 |
| Roles | relay, pub, sub |
| Default port | 9448 |

### Docker Images

| Tag | Draft |
|---|---|
| `moxygen/relay:14`, `moxygen/client:14` | 14 |
| `moxygen/relay:16`, `moxygen/client:16` | 16 |
| `moxygen/relay:18`, `moxygen/client:18` | 18 |

### Entry Points

- **relay:** `moqrelayserver -port <port> -cert /certs/certificate.pem -key /certs/certificate.key -endpoint /moq`
- **pub:** `moqflvstreamerclient --insecure --input_flv_file <flv> --connect_url https://<relay>:<port>/moq --track_namespace <stream>`
- **sub:** `moqflvreceiverclient --insecure --flv_outpath <out>.flv --connect_url https://<relay>:<port>/moq --track_namespace <stream>`

Note: moxygen media is FLV-only (H.264/AAC-LC, MoQMI-encoded). The client image is a source build
(`docker/moxygen/Dockerfile.media`) because official images ship only `moqrelayserver` / `moq_interop_client`.

---

## imquic (Meetecho)

| Field | Value |
|---|---|
| Source | https://github.com/meetecho/imquic |
| Language | C (picoquic-based) |
| Drafts | 16, 17, 18, 19 |
| Roles | relay, pub, sub |
| Default port | 4443 |

> **Why is `pub` clock-only?** imquic's demo `moq-pub` is a *test-data clock
> generator* — its main loop (`moq-pub.c`) emits one timestamp string per
> second and has no media-file input, so it cannot publish a real video for
> media-delivery tests. This is a **feature gap in its demo tool, not a protocol
> incompatibility**: imquic relays/subscribes to real streams produced by other
> implementations (e.g. moq-rs). The `pub` role IS registered in `registry.json`
> for the same-impl clock plan (`testplans/imquic-self.yaml`), which scores
> delivery on received "Incoming object:" lines (`data_check: object_receipt`)
> instead of file integrity.

### Docker Images

| Tag | Draft |
|---|---|
| `imquic/relay:16`, `imquic/cli:16` | 16 |
| `imquic/relay:17`, `imquic/cli:17` | 17 |
| `imquic/relay:18`, `imquic/cli:18` | 18 |
| `imquic/relay:19`, `imquic/cli:19` | 19 |

### Entry Points

- **relay:** `imquic-moq-relay -p 4443 -q -w -c /certs/cert.pem -k /certs/priv.key`
- **pub:** `imquic-moq-pub -r <relay-ip> -R 4443 -M {draft} -q -w -S localhost -c /certs/cert.pem -n / -N <track>`
- **sub:** `imquic-moq-sub -r <relay-ip> -R 4443 -M {draft} -q -w -S localhost -c /certs/cert.pem -n / -N <track> -t hex`

---

## MOQtail (OzU)

| Field | Value |
|---|---|
| Source | https://github.com/moqtail/moqtail |
| Language | Rust + TypeScript |
| Drafts | 16 |
| Roles | relay, pub, sub |
| Default port | 4433 |
| Published image | `ghcr.io/moqtail/relay:latest` |

### Docker Images

| Tag | Draft |
|---|---|
| `moqtail/relay:16` | 16 |
| `moqtail/client:16` | 16 |

### Entry Points

- **relay:** `moqtail-relay --port 4433 --cert-file <cert> --key-file <key>`
- **pub:** `moqtail-client -c publish --server <url> --input <file>`
- **sub:** `moqtail-client -c subscribe --server <url> --output <dir>`

---

## moq-dev (kixelated)

| Field | Value |
|---|---|
| Source | https://github.com/moq-dev/moq |
| Language | Rust (native) + TypeScript (web) |
| Drafts | 14–18 (IETF mode via moq-net) |
| Roles | relay, pub, sub |
| Default port | 4443 |

### Docker Images

| Tag | Role | Draft |
|---|---|---|
| `moq-dev/relay:latest` | relay | 14-18 (IETF mode via MOQ_MODE=ietf) |
| `moq-dev/cli:latest` | pub/sub | 14-18 (IETF mode via MOQ_MODE=ietf) |

### Entry Points

- **relay:** `moq-relay --bind [::]:4443 --tls-cert <cert> --tls-key <key>`
- **pub:** `moq-cli publish <url>/anon/<stream> < <file>` (add `--ietf` flag for IETF mode)
- **sub:** `moq-cli subscribe <url>/anon/<stream>` (add `--ietf` flag for IETF mode)

### Notes

Default released mode is **moq-lite** (`draft-lcurley-moq-lite`). Set env `MOQ_MODE=ietf`
or pass `--ietf` to use full IETF MoQT wire protocol. Both modes are forwards-compatible
but only IETF mode is suitable for cross-implementation interop testing.

---

## quiche-moq (Google)

| Field | Value |
|---|---|
| Source | https://github.com/google/quiche |
| Language | C++ (Bazel) |
| Drafts | 16 |
| Roles | relay, pub, sub |
| Default port | 443 |

### Docker Images

| Tag | Draft |
|---|---|
| `quiche-moq:16` | 16 |

### Entry Points

- **relay:** `moq_relay`
- **pub/sub:** `moq_client --publish|--subscribe <url> <stream>`

### Notes

**Name clarification:** Google's `google/quiche` `moqt` relay is distinct from
Cloudflare's `cloudflare/quiche` library (which has no MoQT support).
The interop-runner registry label "quiche-moq" refers to Google's implementation.
Build via Bazel; optional inclusion in testbed due to heavy build requirements.

---

## Draft ↔ ALPN Mapping

| Draft | ALPN |
|---|---|
| 14 | `moqt-14` |
| 15 | `moqt-15` |
| 16 | `moqt-16` |
| 17 | `moqt-17` |
| 18 | `moqt-18` |
| 19 | `moqt-19` |

## Draft Compatibility Notes

| Break Point | Change | Impact |
|---|---|---|
| d14 → d15 | ALPN-based version negotiation | Wire-incompatible |
| d16 → d17 | Unified SETUP, vi64 varints, stream changes | Wire-incompatible |
| d17 → d18 | Request ID removed, message restructuring | Wire-incompatible |
| d18 → d19 | Minor error code numbering adjustments | Wire-compatible? |

## Implementations Excluded

| Implementation | Reason |
|---|---|
| aiomoqt | Not in scope for thesis (Python impl, limited draft support) |
| moqtransport (TUM) | Draft-13 only, too old |
| floatdrop/moq-go | Low activity, low maturity |
| dineshadhi/moq-go | Draft-4, stale |
| gomoqt (qumo-dev) | moq-lite subset only |
| birneee/quiche_moq | Personal, not production-ready |
