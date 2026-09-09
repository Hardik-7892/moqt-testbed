# 01 — MoQT Primer (PhD-Level Protocol Grounding for Ch2/Ch4)

This chapter gives you the precise protocol story your implementation and evaluation chapters presuppose. It is grounded in what the testbed actually observes on the wire, not in RFC prose alone.

## 1.1 Where MoQT sits: why not DASH, why not WebRTC

DASH/HLS (TCP, segmented, CDN-cached) optimises for scalability at the cost of seconds of latency: MPD manifest + sequential segment GETs, one RTT per segment, TCP head-of-line (HOL) blocking across segments on one connection. WebRTC (RTP/RTCP, peer/SFU mesh) optimises for sub-second latency at the cost of SFU fan-out state and GCC congestion coupling unsuitable for CDN reuse.

MoQT (IETF `draft-ietf-moq-transport`) is the QUIC-native middle: publish/subscribe of named objects over QUIC (raw `moqt://` or WebTransport `https://`), relay-mediated, CDN-compatible, with application objects decoupled from transport streams so loss on one track need not stall another — provided implementations actually isolate them (they often do not; see §1.5 and Ch6).

Your testbed encodes this thesis directly: same media over MoQ (`4443/QUIC`) vs LL-DASH H2 (`443/TCP/nginx`) vs LL-DASH H3 (`443/QUIC/caddy`) (`registry.json:37,147,180`, `decisions.md:50-54`). H2-vs-H3 isolates transport (TCP HOL vs QUIC); MoQ-vs-H3 isolates app semantics (both QUIC); MoQ-vs-H2 mixes both. That triple is the only honest way to claim a “MoQ win” (D8/D13, `decisions.md:50-58,160-167`).

## 1.2 Roles: relay, publisher, subscriber

The testbed models three roles per implementation (`registry.json:13-17,49-53,88-92`):

- **Relay** — QUIC server, namespace router, cache, inter-relay peer. Every run starts it first and waits 2 s gaps between multiple relays (`harness/runner.py:872-931`).
- **Publisher** — announces a namespace, pushes groups/objects. Started second; the runner gates subscriber join on namespace marker *plus*, for moq-rs, first `segment:` log line, because namespace registration races ahead of servable groups by ~1.5 s (B37/B38, `harness/runner.py:431-507`).
- **Subscriber** — subscribes (typically `AbsoluteStart`), receives objects. Started last; supervised for 15 s with bounded relaunch (`MAX_SUB_RESTARTS=2`) on `Track not found / media error / error subscribing / Closed(16)` (`harness/runner.py:107-118,544-608`).

Chain adds `relay_a / relay_b`; fanout adds `sub1..subN`; chainfanout combines both (`harness/runner.py:872-878,951-956`). LL-DASH reuses the same role slots as `origin / client` (`decisions.md:18-19`) so topology wiring is identical (D3).

Startup order matters: relay → pub → sub. Sub-before-pub causes moq-rs sub to exit immediately on `Track not found` without retry (B20, `found-bugs.md:537-568`). The supervisor exists because the protocol has no defined “wait for track” — a conformance gap you report as RQ6 (see `12_THREATS_SUMMARY_MAPPING.md`).

## 1.3 Object model: namespace / track / group / object / subgroup

The testbed’s content model (`harness/verify.py:15-19,217-253`) is the examinable definition:

- Source fragmented MP4 is split into **init** (everything before first `moof`) + **one object per `moof/mdat` run**, trailing `mfra/free` excluded. Non-fragmented/non-MP4 falls back to single whole object.
- Relay `mlog` is authoritative: sum of `subgroup_object_created` payload lengths on the subscriber connection = bytes handed to subscriber, independent of client stdout quirks (`harness/verify.py:8-13`).
- Role classification is from control messages, not CID: explicit `publish_namespace` marks publisher; `subscribe_ok` alone does not, because at the draft-18 pin the relay subscribes back on the publisher connection (`harness/verify.py:67-77`, `found-bugs.md:423-426`).
- Single-track `sample.mp4` (`ffmpeg -an`, `Makefile:226`) avoids multi-track interleave where moq-rs writes tracks in arrival order, invalidating linear compare and `data_offset` playback (`found-bugs.md:1048-1062`). At the re-pinned relay, a track is served over multiple concurrent subgroup streams; arrival-order capture is an object-level permutation requiring `reconstruct_from_mlog` (slice by mlog lengths, sort by `(group,object)`, `harness/playable.py:57-109`, `found-bugs.md:1084-1121`).
- moq-rs subscribes with `filter AbsoluteStart, start: None`; if subscribe lands after a publish burst, the relay answers `subscribe_ok [["9","[09 00]"]]` (latest group 9) and serves only the tail — no archive/backfill at `2d16c9c8` (`found-bugs.md:1485-1492`). This is why late-join semantics must be honest `partial`, not `fail` (D6, `decisions.md:100-109`).
- moxygen FLV publishes via MoQMI to `video0/audio0` under the namespace; the sub demuxes MoQMI and transmuxes to FLV (`docker/moxygen/scripts/entrypoint.sh:17-23`). Byte comparison is therefore approximate transmux, never exact (`registry.json:77`).
- imquic uses namespace `/` + track `-n / -N {stream}` (`registry.json:103-104`); moq-dev uses URL path `/anon/{stream}` (`registry.json:238-239`).

For Ch4, state this model once, then cite `harness/verify.py:217-253` as the operationalisation. Every coverage/integrity number in Ch6 derives from it.

## 1.4 Transport: QUIC, WebTransport, TLS, keys

- MoQT runs over QUIC, either raw QUIC (`moqt://`) or WebTransport over HTTP/3 (`https://`) (`harness/quic_alpn.py:3-9`, `harness/probe.py:237-241`).
- moq-rs probe uses `moqt://` so the client offers a draft-specific ALPN literal; relay/sub entrypoints use `https://` WebTransport URLs (`registry.json:27-28`, `harness/probe.py:237-241`).
- moxygen media clients ride proxygen WebTransport/H3 whose TLS ALPN is literally `h3`; the MoQ draft negotiates inside the encrypted session, invisible in the Initial (`found-bugs.md:1509-1515`). This is why moxygen draft claims are BOOT-only UNVERIFIED (B46).
- imquic passes `-q -w` (QUIC + WebTransport, `registry.json:102-104`); its relay logs `-- WebTransport (moqt-16)` then `-- draft-ietf-moq-transport-16` (`found-bugs.md:1418-1420`).
- Cross-stack framing is not uniform: moq-rs cannot parse imquic WT session/SETUP (`InvalidMessage(33)`) and closes imquic with `No WebTransport protocol (271)` (`found-bugs.md:1420-1426`). Pinning imquic relay to `-M 18` advertises only `moqt-18` and rejects moq-rs; unpinned `any` accepts per-connection (`registry.json:115`). Interop therefore requires the unpinned relay — a finding, not a config accident.
- moxygen relay serves WebTransport CONNECT only at `-endpoint /moq`; bare `https://:{port}` returns `404` (`found-bugs.md:1397-1407`). Fixed via `client_path: /moq` (`registry.json:76`, `harness/runner.py:840-848`).
- `SSLKEYLOGFILE=/keys/sslkeys.log` is set on all containers (`harness/runner.py:1237-1239`); verified for moq-rs with real NSS lines in `run_20260818_181221` (`found-bugs.md:271-280`). imquic needs explicit `-s` (`registry.json:102-104`, `found-bugs.md:1366-1368`). Wire RTT via tshark was decisioned OFF: tshark 4.6.4 reports decryption-context failure and lacks `quic.ack.rtt` even with correct logs; qlog RTT stays canonical (`found-bugs.md:1375-1393`).

For Ch5, this justifies why pcaps are header-only evidence and qlogs are the RTT source.

## 1.5 ALPN negotiation and draft churn

Draft ↔ ALPN (`IMPLEMENTATION_REGISTRY.md:198-207`): `14→moqt-14`, `15→moqt-15`, `16→moqt-16`, `17→moqt-17`, `18→moqt-18`, `19→moqt-19`. Probe mapping is narrower (`moq-00→14`, `moqt-16→16`, `moqt-18→18`, `harness/quic_alpn.py:25-28`).

Break points (`IMPLEMENTATION_REGISTRY.md:209-216`):

| Break | Change | Impact |
|-------|--------|--------|
| d14→d15 | ALPN-based version negotiation | wire-incompatible |
| d16→d17 | Unified SETUP, vi64 varints, stream changes | wire-incompatible |
| d17→d18 | Request ID removed, message restructuring | wire-incompatible |
| d18→d19 | Minor error-code renumbering | wire-compatible? |

Three testbed-visible consequences:

1. **Tag ≠ wire.** Stale Hub `:18` at `a6ed4e9` vs local `:18` at `2d16c9c8` are wire-incompatible draft-18-dev revisions; handshake dies with `no mutually supported version` (B36, `found-bugs.md:1013-1028`). Always cite commit pins, not tags.
2. **Default `any` lies.** imquic default offers all four ALPNs and negotiates highest common; with `any` the sub silently negotiates `moqt-19` even on a `d18` row (`registry.json:115`, `found-bugs.md:130-136`). The runner pins sub/pub via `-M {draft}`; the relay stays unpinned for interop (see Ch02 §3).
3. **ALPN is encrypted.** The probe decrypts QUIC v1 Initials via RFC 9000/9001 keys from DCID, strips header protection, GCM-decrypts, parses ClientHello ALPN (`harness/quic_alpn.py:44-57,81-111`, validated against RFC vectors + live moq-rs 14/16/18 captures). moq-rs mlog 16/18 does not log negotiated draft; ALPN is the only wire evidence (`harness/probe.py:118-120`). Draft-14 mlog does log `selected_version: DRAFT_14` (`harness/probe.py:135-144`).

Evidence vocabulary (STRICT): `setup/alpn/tap14` = CONFIRMED; `boot/unverified` = not confirmed; `failed` = could not run; never return claimed as negotiated (`harness/probe.py:43-58`, `harness/verify.py:797-804`). `DraftVerifier.verify_all()` probes every `(impl,claimed_draft)` after `{draft}` substitution (`harness/verify.py:814-835`); `make verify` runs it (`Makefile:208-209`).

Current verdicts: moq-rs UNVERIFIED-honest (mlog lacks draft), imquic CONFIRMED via TAP14 (`setup-only`), moxygen BOOT-only (B46: raw client offers `moqt-16/14/moq-00`, never `18`; WT `h3` hides draft; keep `claimed 14/16/18 → boot UNVERIFIED`, `registry.json:77`, `found-bugs.md:1516-1533`).

Write this as Table 2.1 + one paragraph on “how the testbed detects” — exactly what the grading map asks for Ch2.
