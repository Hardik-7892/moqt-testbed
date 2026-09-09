# Fair-Comparison Decisions — MoQ (moq-rs / imquic / moxygen) + LL-DASH Baseline

> **Purpose.** Single place documenting *how* and *why* the testbed compares its three MoQ implementations and the LL-DASH baseline fairly. Chapters 2/3/6 cite this file for reproducibility; new decisions are appended as `D#` entries — never edited retroactively.
>
> **Status vocabulary.** `decided` — choice locked and implemented or queued. `proposed` — under discussion. `superseded` — replaced by newer `D#` (link). Each `D#` has `Decision / Why / How enforced / What would break fairness if violated`.

**Related files:** `registry.json` (impl pins + `sub_output` contract), `harness/verify.py` (integrity), `harness/measure.py` (metrics), `harness/runner.py` (orchestration), `topologies/{basic,fanout,chain}.py` (wiring), `scenarios.yaml` (impairment profiles), `Makefile` (media generation), `testdata/` (source media).

---

## 1. Implementation scope — `D1`

| Role | Implementation | Language / stack | Draft | Image prefix `registry.json:8` | Provides |
|---|---|---|---|---|---|
| MoQ | **moq-rs** Cloudflare | Rust, `quiche`+`tokio` | `18` (`main` pin `2d16c9c`) | `0hardikpandey/moq-rs-{relay,client}:18` | `relay, pub, sub` `registry.json:13` |
| MoQ | **moxygen** Meta | C++ `mvfst/proxygen` | `18` (`MXY_COMMIT 4095b18` + `MXY_PROXYGEN 3ad19ac` `Makefile:9`) | `0hardikpandey/moxygen-{relay,client}:18` | `relay, pub, sub` (FLV only) `registry.json:49` |
| MoQ | **imquic** Meetecho | C `picoquic` | `16-19` runtime `-M` | `0hardikpandey/imquic-{relay,cli}:18` | `relay, sub` only — demo `moq-pub` is timestamp clock generator `registry.json:87` `IMPLEMENTATION_REGISTRY.md:84` |
| Baseline | **LL-DASH H2** | `nginx:alpine` origin + Python `httpx[http2]` client | `CMAF` `MPEG-DASH` over `H2` (`TCP+TLS`) | `0hardikpandey/lldash-origin-h2:latest` / `lldash-client-h2:latest` | `origin, client` |
| Baseline | **LL-DASH H3** | `nginx-quic` / `caddy:alpine` origin + Python `aioquic`+`httpx` client | `CMAF` `MPEG-DASH` over `H3` (`QUIC+TLS`) | `0hardikpandey/lldash-origin-h3:latest` / `lldash-client-h3:latest` | `origin, client` |

`WebRTC` (`Pion/Janus`) stays **Future Work** `Ch8/9` `chapter_subchapter_grading_map.md:109` — different failure mode (`GCC` vs QUIC CC) and SFU compute contention not `TCLink` `bw` comparable. No scaffold yet.

Disabled: `moqtail / moq-dev / quiche-moq / moq-go` remain `disabled_implementations` `registry.json:115` (unverified, `negotiated_drafts null` `found-bugs.md:342` `B15`).

---

## 2. Media alignment — `D2` (why `sample_120s.mp4` 120→0, 2 s GOP)

### D2.1 — Same source bytes for every stack

*   **Decision.** One canonical source generates every artefact:
    *   `testdata/sample.mp4` `320×240 r=30 d=10 120→10` old baseline `Makefile:195` — kept for `test-all-sample` `~95 runs`.
    *   `testdata/sample_120s.mp4` `320×240 r=30 d=120 120→0` new sustained media — `ffmpeg lavfi color=c=red:s=320x240:r=30:d=120, drawtext text='%{eif\:120-t\:d} seconds' ... drawtext text='%{eif\:(120-t)*1000-1000*trunc(120-t)\:d} milliseconds' :fontcolor=white:fontsize=28:x=(w-text_w)/2:y=...:box=1` `Makefile:188` clone with `d=120`, `g 60`, `force_key_frames expr:gte(t,n_forced*2)`, `-movflags empty_moov+frag_keyframe+separate_moof -t 120`. `120→0` so a late joiner that skips `15s` shows a visibly gapped countdown `120→0` in the rendered capture — debug readable.
    *   Derivatives: `sample_120s.flv` `Makefile:201` `ffmpeg -i sample_120s.mp4 -c copy`, `sample_120s.mpd + chunks/` `MP4Box -dash 2000 -frag 2000 -profile live` (`2 s` segment = `2 s` fragment).
*   **Why.** `harness/verify.py:214` `expected_objects()` splits any `fMP4` into `init + one object per moof/mdat`; trailing `mfra/free` excluded `harness/verify.py:239` `expected_media_bytes()`. Using one `fMP4` makes `expected_bytes`, `sha256_expected`, `per_object_match` comparable byte-for-byte across MoQ and LL-DASH. `BBB` `121 MB` `M4V` `brand ftypM4V` already broke `moq-pub` `hdlr size too small` `found-bugs.md:605` `B22` and throughput-regression `B25`; `sample_120s` avoids that while still stressing `bw:5 queue:1000` bufferbloat `I16`.
*   **How enforced.** `harness/runner.py:843` `media_path = /data/{media_file}` bind-mounts `TESTDATA_DIR` read-only into every container; `registry.json:28` `sub_output.file` `/output/{stream}` vs `/output/{stream}.flv` isolates per-impl artefact path so summing never double-counts `found-bugs.md:394` `B17` `rglob("*")`. `make testdata/sample_120s.mp4` is prerequisite for `make build-lldash` / `test-lldash-baseline`.

### D2.2 — Group / segment duration aligned to `2 s`

| Stack | Unit | Why `2 s` | How |
|---|---|---|---|
| MoQ `moq-rs` | `group` = `1 GOP`, `object` = `1 moof/mdat` `harness/verify.py:231` | `1 s` GOP (`g 30`) would give `120` groups for `120 s` vs `LL-DASH` `60` segments `2 s` → unfair request count and late-join miss math (`5 s` → `5` vs `2` groups). | `g 60` at `r=30` `force_key_frames gte(t,2)` → `~60` groups, each `~2 s`. `moxygen` FLV inherits same `2 s` keyframe via `ffmpeg -c copy` copy. `imquic` relay forwards same groups when it is `relay/sub`. |
| `LL-DASH` `H2+H3` | `segment` `=2 s` (`-dash 2000`), `fragment/chunk` `=2 s` (`-frag 2000`) | One HTTP `GET` per `2 s` ≈ one MoQ `object` per `moof`. Keeps `impairment pressure` (`loss 1%`, `bw:5`) comparable request concurrency for both `H2/TCP` and `H3/QUIC`. | `MP4Box -dash 2000 -frag 2000 -profile live` — one chunk per segment; `client.py` fetches sequentially next `SegmentNumber` with `httpx[http2]` `h2c` or `aioquic` `h3` per `protocol` flag. See `D8`. |

If violated: re-introduce `g 30` → MoQ would appear `2×` more fragile under `loss:1%` purely due to doubled request count, not protocol difference.

---

## 2.3 Transport split — `D8` (LL-DASH `H2` vs `H3`, both tested)

*   **Decision.** `LL-DASH` baseline runs **twice per topology/impairment**: `protocol: h2` and `protocol: h3` `registry.json:4` `lldash-h2` + `lldash-h3`. 
    *   `H2` `TCP+TLS (HTTP/2)` via `nginx:alpine` `http2` `docker/lldash/Dockerfile.origin.h2` port `443` with `harness/certs.py` certs (`cert_aliases` for `nginx` `cert.pem/key.pem`). Mirrors `Moq H2`-like `TCP` path but with HTTP semantics.
    *   `H3` `QUIC+TLS (HTTP/3)` via `caddy:alpine` (or `nginx-quic`) `QUIC` `docker/lldash/Dockerfile.origin.h3` `udp 443` same certs + `SSLKEYLOGFILE` for `wireshark` decrypt `harness/pcap.py`. Mirrors `MoQ QUIC` path — isolates **app semantics** (`DASH` chunks vs `MoQ` objects) from **transport** (`QUIC`).
    *   Client image `lldash-client` (`docker/lldash/Dockerfile.client`) bundles `httpx[http2]` + `aioquic` + `h2` and exposes `--protocol h2|h3` mapped from `registry entrypoints` `registry.json:30` `lldash-h2.sub` / `lldash-h3.sub`. `Makefile:92` `build-lldash` builds both `h2`+`h3` tags; `testplans/lldash-baseline.yaml` interleaves `h2` and `h3` rows so `moq-vs-lldash` has `MoQ vs H2 vs H3` triple.
*   **Why.** Two reasons thesis needs both: (1) `H2` vs `H3` isolates transport HOL — `HTTP/2` still `TCP HOL` per `chapter2-survey.txt:5` vs `HTTP/3` `QUIC` multiplex `eliminate HOL` `chapter2-survey.txt:7`. Without `H3`, `LL-DASH` would unfairly lose under `loss 1-5%` purely due to `TCP` not `DASH`. (2) `MoQ vs H2` isolates `HTTP + TCP` vs `QUIC`; `MoQ vs H3` isolates only app layer (both `QUIC`) — together they prove whether MoQ win is transport or object model. `bbr-cubic-fairness.yaml`/`aqm-sweep.yaml` reuse same split.
*   **How enforced.** `registry.json:8` two impls `lldash-h2` (`port 443`) + `lldash-h3` (`port 443/udp`); `harness/runner.py:1134` `_create_network` port binding per `relay_port` respects per-impl `port`. `client.py` logs `protocol` + negotiated `ALPN h2/h3` `harness/measure.py:60` `time_to_first_object_ms`; `report.py` `Fig 6.7` overlays `MoQ / H2 / H3`.
*   **If violated:** testing only `H2` makes `MoQ` look better under loss due to transport alone; testing only `H3` hides `TCP` CDN reality. Need both for honest `Ch6` `Outcome 40%` `chapter_grading_map.md:29`.

## 3. Topology alignment — `D3` (same wiring, same impairment placement)

*   **Decision.** `LL-DASH` reuses the three `Topology` descriptors `topologies/base.py:21` verbatim — no new network code:
    *   `basic` `topologies/basic.py:14` `pub,relay,sub` `s1` → `origin,edge?,client` `s1` (edge optional). Baseline `Fig 6.7`.
    *   `fanout` `topologies/fanout.py:11` `pub,relay,sub1..N,late_sub*` `s1` `fanout_sub_links()` `fanout.py:38` → `origin→N clients`. `late_sub*` `fanout.py:18` for late-join `§4`. Per-sub impaired `fanout.py:48` `default_impaired_roles()`.
    *   `chain` `topologies/chain.py:11` `pub,relay_a,relay_b,sub` `s1,s2` `__inter_relay__` `chain.py:28` `relay_delay` `chain.py:43` → `origin→edge cache→client` CDN hierarchy (`relay_a` `origin nginx`, `relay_b` `edge nginx proxy_cache`). Same `inter_relay_link_params()` `chain.py:42` → comparable cache-miss fill over `s2`.
    *   Custom topologies: add `topologies/custom.py` subclassing `Topology` with `roles()/links()/config_keys()` `base.py:21` → registered in `topologies/__init__.py` `TOPOLOGIES` → `harness/runner.py:194` dispatches generically. Documented as Future Work `PLAN_revive_topologies.md`.
*   **Why.** `Fig 2.1` canonical `pub→relay→sub` on shaped `TCLink` `EXECUTION_PLAN.md:9` is the thesis claim `Ch2` `gap: no custom controlled networks` `chapter2-survey.txt:36`. Using same `TCLink` `bw/delay/loss/max_queue_size` `scenarios.yaml:5` per role `base.py:54` `link_params_for_role()` isolates protocol difference. `chain` tests relay/edge cache coherence; `fanout` tests `I14` Jain `J=(Σx)²/(n·Σx²)` `improvements.md:276` fairness.
*   **How enforced.** `harness/runner.py:664` `_create_network()` + `_fix_ovs_switching()` `found-bugs.md:494` `B19` + `_verify_impairments()` `harness/runner.py:340` (probes `htb/tbf/netem` `tc qdisc` presence) already generic; `LL-DASH` `origin` uses `relay` impaired set so never double-applies `found-bugs.md:294` `B12` `per-device`. `B7` host lookup `topologies/fanout.py:14` chain `__inter_relay__→relay_a` `found-bugs.md:32` `B33` reused.
*   **If violated:** using different `delay` placement per stack (e.g. impairing both `pub+sub` for MoQ but only `sub` for `LL-DASH`) would double `RTT` `5`→`10 ms` for MoQ silently `found-bugs.md:288` `B12` `delay:10ms → ~20ms` — thesis numbers incomparable.

---

## 4. Network impairment alignment — `D4` (per-device, single-wire)

*   **Decision.** Single-wire impairment: without `network.devices`, only subscriber wires impaired (`fanout: every sub{i}`) `topologies/base.py:47`; with `devices`, `network.devices: {sub1:{bw:3}, sub2:{bw:3}}` `improvements.md:291` `I7` merges top-level `bw/delay/loss` `base.py:63` `link_params_for_role()`. `max_queue_size` applied via `client_roles()` `base.py:76` `pub/sub` only (relays never queued). Sweeps reuse same values across stacks:
    *   `latency 5→200 ms` `testplans/latency-sweep.yaml`
    *   `bandwidth 1→100 Mbps` `testplans/bandwidth-sweep.yaml`
    *   `loss 0→20%` `testplans/loss-sweep.yaml`
    *   `queue 10→1000` `testplans/queue-sweep.yaml` bufferbloat `I16` `improvements.md:326`.
*   **Why.** Real `TTFO` vs standing queue `queue:1000` at `bw:5 Mbps` `~2 s` late `I16` signature must be comparable. Double-placement `B12` `found-bugs.md:288` would inflate MoQ `wire_rtt` vs `LL-DASH` `TTFB`.
*   **How enforced.** `_impaired_host_names()` `harness/runner.py:327` scopes `tc` verify to actually impaired hosts; chain `__inter_relay__` maps to `relay_a` `harness/runner.py:332`; logs `tc_{host}.log` `harness/runner.py:365` auditable per run.

---

## 5. Metric alignment — `D5` (same clocks, same thresholds)

| MoQ `harness/measure.py:34` | `LL-DASH` analogue | Shared rule |
|---|---|---|
| `time_to_first_object_ms` `measure.py:99` `_ttfo_from_mlog` `first_object_ts - pub_start_time` per-sup | `first_chunk_arrival_ms` `GET MPD` → `GET SegmentN` `first_chunk_ts - origin_start` (join-relative `first_chunk_after_join_ms` for late `late_sub`) `testplans/join-leave-dynamics.yaml:122` | Join-relative for late subscribers `§6`; early subs use `pub/origin_start` |
| `throughput_bps` `measure.py:72` `delivered_bytes*8/run_duration_s` | Same `bytesReceived*8/duration` | `run_duration_s` `measure.py:70` from `_wait_for_completion` `found-bugs.md:314` `B13` `delivery quiesced` vs `time limit reached` `found-bugs.md:324` `B24` `completion_coverage 0.95` |
| `object_loss_rate` `measure.py:57` `subgroup_object_created vs published` | `stall_ratio / chunk_miss` (missing `SegmentNumber`) | Both under `bw:5 queue:100` `aqm-sweep.yaml` |
| `rtt_estimate_ms` `measure.py:216` qlog → `wire_rtt_*` `measure.py:268` tshark `tshark_available()` `harness/pcap.py` | `TCP RTT` / `TTFB` from `aiohttp` timing | Validates `tc qdisc` vs actual `REPORT_testbed_status_2026-08-31.md:128` `pcaps header-only 86 B B37` honest null |
| `delivered_fraction / coverage_pct` `measure.py:75` `delivered/original` | Same | Uses same `expected_media_bytes` `verify.py:239` |
| `Jain J` `I14` `improvements.md:276` | Same per-client `bytes` | `fanout` `N=3` `late_sub_count=1` etc. |
| `integrity` `harness/verify.py:283` `exact/good/mismatch` `good_threshold 90.0` `verify.py:283` | Same `byte_identical_pct` `verify.py:342` prefix + `sha256` `harness/measure.py:70` | `media_bytes()` ANSI strip `verify.py:257` `MLOG_STDOUT_SIG` only for `logs_on_stdout ansi_timestamp` `registry.json:33` — `lldash` `logs_on_stdout:false`. Per-sub `verify_groups()` `verify.py:413` worst-tier `mismatch` for fanout; `SUM` over subscriber mlogs not best-single `found-bugs.md:415` `B17` |

*If violated:* differing `completion_coverage` would let `LL-DASH` `quiesce` at `80%` while MoQ waits to `95%` → incomparable `run_duration_s`.

---

## 6. Late-join semantics — `D6` (honest `partial`, not `fail`)

*   **Decision.** `fanout.py:18` `late_sub{i}` + `harness/runner.py:948` `late_join_delay_s / late_sub_count` (now reads `network.*` fallback to `config.*` `B39a`) + optional `late_joins: [{sub:late_sub1,delay:5s}]` `join-leave-dynamics.yaml:34` `B39b` + `chain.py:14` extended `late_sub` `B39c` + per-join `late_join_wallclock` `B39d` for `first_object_after_join_ms`.
*   **Why.** Real live `2-3 h` stream `late join at 5/30 s` `join-leave-dynamics.yaml:22` `5 s late` → `~2` `2 s` groups missed `§2` `g 60`; `30 s` → `15` missed. Media `120→0` timer `§1` makes skip visually auditable: late `late_sub1` capture should start `e.g. 115` not `120`. `testplans/join-leave-dynamics.yaml:121` metrics `join_latency_ms / cache_warmup_time_ms / group_missed_on_join / group_divergence_after_join` capture it.
*   **Expected per-stack (both correct, both `partial` is honest):**
    *   **MoQ** `relay` serves `late_sub` from **current `group_id/object_id` onward** via cache; if still resident, hit else `FETCH_ERROR`/`SUBSCRIBE_ERROR` `features/draft-18.json:32` `FETCH/FETCH_OK/FETCH_ERROR` or `SUBSCRIBE_ERROR`. `chain` late `relay_b` miss fetches via `relay_a` coordinator `harness/runner.py:497`.
    *   **LL-DASH** `edge` serves from **current `SegmentNumber` in DVR window** (`availabilityWindow`). Miss before join is correct `delivered_fraction <1` — not counted as `fail`. `nginx proxy_cache_valid` hit if origin→edge still cached.
    *   `leave_rejoin` `join-leave-dynamics.yaml:61` `leave 20s rejoin 30s` — MoQ `UNSUBSCRIBE`+`SUBSCRIBE` stateful eviction vs `LL-DASH` stateless `MPD` refetch `GO_AWAY` etc. `features/draft-18.json:32` advanced.
*   **How enforced.** `per_sub` `verify.py:498` never concatenates `N` captures `found-bugs.md:415` `B17`; `aggregate delivered = SUM` over subscriber mlogs `verify.py:496`; `byte_identical_pct = min` `verify.py:511` so worst late sub dominates `verdict`. `late_sub` `partial` remains `partial` `found-bugs.md:324` `B24` not `fail` — same as `bbr-cubic-fairness` `partial 10%` honest `REPORT_testbed_status_2026-08-31.md:112`.
*   **If violated:** treating late `late_sub` `75%` as `fail` would invert scoreboard `found-bugs.md:67` `B5` style; concatenating `N` captures would yield bogus `N×100%` `found-bugs.md:424`.

---

## 7. Implementation-specific shims — `D7` (FLV / hex / ANSI)

*   `moxygen` FLV only — `sample_120s.flv` copy keeps `FLV` `h264/AAC-LC` `registry.json:48` `MoQMI`; byte compare approximate `verify.py` `transmux` note, `sub_output.playable copy` `registry.json:68`.
*   `imquic` demo `moq-pub` clock generator `registry.json:87` — excluded from `pub` rows; still `relay/sub` for `chain-imquic-moqrs` `chain.yaml:32` honesty `chain.yaml:28` note. `hex` mode required `verify.py:106` `hex_decode` `found-bugs.md:458` `B18`.
*   `moq-rs` stdout `ANSI` logs `verify.py:257` `MLOG_STDOUT_SIG` `(?:\x1b\[[0-9;]*m)+` double-escape `found-bugs.md:32` `B34` stripped only when `logs_on_stdout ansi_timestamp` `registry.json:33`; `lldash` variants `stdout_is_data:false` never strip.

---

## 8. Strict byte-value enforcement — `D9` (value, not count, for ALL)

*   **Decision.** The testbed checks the **value of bytes** (`harness/verify.py:283` `sha256_expected vs sha256_delivered` + `byte_identical_pct` prefix + `per_object_match`), not just the count (`coverage_pct` `delivered/original`). `count 100%` with `00001111` vs `01101110` is `mismatch`, not `good`. Enforced for **all** impls including `lldash-h2/h3` baseline — no lenient override.
*   **Why.** Count alone (`907397/904457 100.33%`) hid `dash init 834 + 60×m4s` re-assembly (`sidx` vs `moov`) scoring `0.0%` identical but `good (playable)` in `run_20260905_163640`. `run_20260905_173031` proved the gap: `H2` strict single-file `903269 exact 100.0%` vs `H3` concat `907397 mismatch 0.0%` — same count, different value. `require_integrity: true` (`testplans/lldash-*.yaml:9` top-level) now propagates to per-run (`harness/runner.py:1797` `TestbedRunner.require_integrity` → `worker()` injection) so `mismatch` → `fail` (`harness/runner.py:1670`), not silent `pass`.
*   **How enforced.**
    *   `docker/lldash/client.py:64` single-file `GET /sample_120s.mp4` via `H2` (`httpx http2`) / `H3` (`curl --http3-only` first, then `httpx` TCP fallback) + `_truncate_to_expected()` (mirrors `harness/verify.py:239` `last mdat`, `mfra/free` excluded) → `903269 B` `sha 8ed2...` `exact`. `H3` QUIC attempt logged `proto=h3`; TCP fallback logged honest.
    *   No local `/data` copy for media bytes — MPD may load locally (control plane `1.2 KB`), but `init/segments/single-mp4` **must** come via HTTP to exercise the shaped `TCLink` (`run_20260905_173031 H3` copied `61×` locally after `Connection refused` → fake throughput, now removed).
    *   `docker/lldash/Dockerfile.origin.h3` Caddyfile simplified to `:443 { tls …; root * /data; file_server }` (previous `servers { protocols }` global + multi-line `handle` broke `caddy adapt` → `Connection refused` for all H3 HTTP).
*   **If violated:** restoring local fallback or dash-concat re-introduces `0% good` false passes and fake `6-7 Mbps` local-copy throughput; restoring the old Caddyfile re-breaks all H3 fetches.

## 9. Streaming baseline, segment-level value — `D10` (supersedes `D9` single-file)

*   **Decision.** `LL-DASH` is **streaming** (`docker/lldash/client.py` MPD + sequential segment `GET`, no single-file fetch): early subs fetch `init + all 60×2s segments`; late subs (`--join-delay`, passed by `harness/runner.py` from `late_join_delay_s` / `late_joins[]`) skip `floor(join_delay / seg_dur)` aired segments, so output length depends on join time (`5s` → `58/60`, `120→0` Timer visibly starts at `~115`). Whole-file SHA vs the source mp4 is **skipped** for lldash (a correct late capture can never match it — even 1 byte difference would read `mismatch`). Instead the client writes a sidecar `<stream>.segments.json` manifest (per-segment `bytes` + `sha256` + `join_delay_s` + `skipped`), and `harness/verify.py:verify_lldash_streaming()` checks per-segment VALUE against the origin chunk files in `testdata/` plus the join-adjusted expectation. Verdicts: `exact` (full stream, all bytes identical), `good` (late suffix correct), `mismatch` (wrong set or any byte differs). `MoQ` impls keep the `exact/good/mismatch` whole-file SHA path untouched.
*   **Why.** Single-file `GET /sample_120s.mp4` was file transfer: every sub got `903269 exact` regardless of join time, so `late_sub1` length told nothing about streaming. Segment re-assembly (`init 834 + 60×m4s`) is playable but never byte-identical to the fragmented mp4 (`sidx` vs `moov`), so strict SHA always read `mismatch 0.0%`. Per-segment SHA gives the requested value check (`00001111` vs `01101110` fails its segment) while remaining join-honest.
*   **How enforced.** `registry.json:133/169` sub entrypoints carry `--join-delay {join_delay}` (`0` early, actual delay late); `client.py` fetches `init` + `segments[skip:]` via HTTP only (no local media fallback — copying `/data` bypasses `tc`); `harness/runner.py:evaluate` merges streaming verdicts; `require_integrity: true` (`testplans/lldash-*.yaml`, propagated `harness/runner.py:1797`) fails `mismatch`; reports show `streaming F/E segs` + per-sub `fetched/expected (join +Ns)` (`harness/report.py`).
*   **If violated:** restoring single-file fetch re-hides late-join behavior; restoring local fallback re-fakes throughput; restoring whole-file SHA for lldash re-marks every correct late capture `mismatch`.

## 10. Short-media rows — `D11` (10 s `sample.mp4` alongside 120 s)

*   **Decision.** `testplans/moq-vs-lldash.yaml` gains 4 short rows on `sample.mp4` (`10 s`, `5×2 s` segs, `test_duration 20`): `moq-clean-10s` / `h2-clean-10s` / `h3-clean-10s` (head-to-head triple) + `moq-fanout-10s` (`N=3` moq sanity). Existing 12×120 s rows untouched (16 total). Media is per-run (`media: sample.mp4`, `harness/runner.py` `run_config.get("media")`); lldash MPD resolves per media (`sample.mpd`, `docker/lldash/client.py:mpd_name`, `harness/verify.py:verify_lldash_streaming(mpd_name=…)`).
*   **Why.** Isolates large-file effects (`B25` relay ceiling: moq `120 s` stalls at `~15 KB partial` in `40 s`) from protocol behavior — if moq passes `10 s` but stays `partial` on `120 s`, the gap is scale, not interop. Keeps the suite fast (short rows `~20 s`).
*   **How enforced.** `testdata/sample.mpd` + `sample10-init.m4s` + `sample10-chunk-00001…00005.m4s` (`Makefile:testdata/sample.mpd`, `ffmpeg -f dash` with prefixed seg names so the `120 s` set `chunk-stream0-*` never collides). `join-delay`/`require_integrity`/streaming verify apply unchanged (`skip=0` at `delay 0`).
*   **If violated:** reusing one MPD/segment namespace for both medias would mix `5`-seg and `60`-seg sets in verification.

## 11. Extending this file

Append `D12…` with same `Decision / Why / How enforced / If violated` rows. Bump `Scope` table when adding an impl (e.g. enabling `moq-go` `registry.json:206` from `disabled`). Reference this file from `Ch4 Methodology` `Table 4.1` + `Ch6` `Fig 6.7` caption for reproducibility. Do not retro-edit `D#` — add `superseded` note and new `D#`.

---

## 12. Bottleneck placement honesty — `D12` (Phase 2, P0-1/P0-2)

*   **Decision.** Chain sweep rows constrain the **inter-relay link** via `network.devices.relay_a` (`topologies/chain.py:84-86`); the sub wire stays `CLEAN` to isolate the relay-to-relay hop. `relay_delay` is omitted wherever `devices.relay_a` is present (inert by `chain.py:84`). Fanout `devices.sub{i}` rows are labelled **independent per-subscriber last-mile shapers, not a shared bottleneck** (`topologies/base.py:68-71` — top-level `bw` is ignored when `devices` lists subs; relay stays `1000M/1ms`). The shared-bottleneck approximation is `devices.relay` (shapes `relay→s1`, `topologies/fanout.py:35`, traversed by every sub's traffic) in `fairness-3sub-shared-egress-10m/5m`. `max_queue_size` applies to pub/sub wires only (`harness/runner.py:1277` — `__inter_relay__` not in `client_roles()`), so queue-sweep chain rows measure end-to-end bufferbloat, not inter-relay queue.
*   **Why.** Pre-Phase-2 chain rows set top-level `bw/loss/delay` (hits sub only) while `__inter_relay__` stayed clean — any "relay-to-relay bottleneck" sentence was false. Pre-Phase-2 fanout "shared bottleneck" wording measured N independent shapers — Jain numbers from those rows cannot support shared-queue claims. True single-queue CBQ needs OVS QoS (future work, `2_weeks/01-future-work-quarantine.md`).
*   **How enforced.** `tests/test_sweep_wiring.py` asserts every chain row in bandwidth/latency/loss sweeps (+ `chain-loss1pct`) carries `devices.relay_a`; VM evidence is `tc_relay_a.log` (`htb`+`netem` on `ra→s2`) and `tc_relay.log` (`htb 10M/5M`) for shared-egress rows. Additionally, every nominal chain/fanout row in the sweeps carries an explicit per-run `topology: chain/fanout`: the runner resolves topology purely from `run['topology']` (plan default when absent, `harness/runner.py:138,194`), so without it a "chain" row silently runs as `basic` with `relay_a/relay_b` ignored (found during Phase 2 — the pre-fix sweeps never built a chain at all). `harness/plan_validation.py` fails fast on `relay_a` without `topology: chain` and on `network.num_subscribers` without `topology: fanout`.
*   **If violated:** removing `devices.relay_a` silently reverts chain rows to sub-only shaping; calling `devices.sub{i}` rows "shared bottleneck" re-introduces the P0-2 false claim.

## 13. MoQ-vs-DASH comparability bounds — `D13` (Phase 3, P0-4)

*   **Decision.** The `MoQ vs H2 vs H3` triple (`testplans/moq-vs-lldash.yaml`) is citable with these declared bounds, not as a fully isolated comparison:
    *   **Stacks differ by design:** MoQ `moq-rs` on `4443/QUIC (quinn)` vs `lldash-h2` on `443/TCP (nginx)` vs `lldash-h3` on `443/QUIC (caddy)` (`registry.json` ports). `H2-vs-H3` isolates transport (TCP HOL vs QUIC); `MoQ-vs-H3` isolates app semantics (both QUIC); `MoQ-vs-H2` mixes both. Read Fig 6.7 with that lens.
    *   **H3 fallback is labelled, not hidden:** the client tries `curl --http3-only` first, then TCP (`docker/lldash/client.py:84-129`). Every segment's actual transport lands in the sidecar `fetch_protos` manifest, propagates through `verify_lldash_streaming` → per-sub stats → `report.html` (`via h3` vs `via tcp-fallback`, `harness/report.py:_transport_label`). An H3-attempted-over-TCP row reads as fallback, never as QUIC.
    *   **MPD is control plane:** the MPD may load from the local `/data` mount (`~1 KB`); `init + segments` must come via HTTP only (no local media fallback — copying `/data` would bypass `tc` and fake throughput).
    *   **Workload asymmetry is declared:** MoQ bulk-push-until-quiesce vs DASH paced-sequential with `skip=floor(join/seg_dur)`; throughput `delivered*8/duration` mixes the two denominators. Every MoQ-vs-DASH table therefore shows `completion_reason` (`quiesced` vs `time-limit`, `runner.py:1402-1466`). Live-paced MoQ publishing (parity) is future work.
*   **Why.** `D8`'s intent (isolate app vs transport) is right but the wiring cannot fully deliver it in `<2w`: different ports/CC stacks and different publish pacing are structural, not bugs to patch overnight. Declaring the bounds keeps the headline defensible.
*   **How enforced.** `tests/test_lldash_streaming.py::test_streaming_propagates_transport_label` + `tests/test_report.py::test_streaming_badge_shows_transport`; VM evidence is the `via …` suffix in `report.html` streaming cells.
*   **If violated:** dropping the `via` label re-introduces silent H3-over-TCP false comparisons; comparing throughput without `completion_reason` re-mixes the denominators.

## 14. Status-ladder reading rule for mismatch rows — `D14` (repeats review)

*   **Decision.** Under `require_integrity: true`, the status ladder (`harness/runner.py:1838-1849`) reads: checks-fail → `fail`; coverage<95% → `partial`; delivered-full + `mismatch` → `fail`. Consequence: a high-coverage mismatch reads `fail` while the same verdict at low coverage reads `partial` (batch `run_20260907_001749`: `moq-fanout-10s` at 128% mlog coverage → `fail`; at 64% → `partial`, per-sub artifacts identical at 11241×3). For MoQ fanout rows, **cite per-sub artifact bytes + verdict, never status or mlog-derived throughput**: mlog-sum inflates 2-4x across repeats (B38 sub restarts add mlog connections; `analysis/aggregate.py` warns on >2x divergence), while artifacts are repeat-stable. Citable fanout throughput is `artifact_thr_p50/p95` in the `_agg.csv`, not `throughput_p50`.
*   **Why.** Without this rule the same physical outcome (identical captures, identical verdict) cites as two different statuses across repeats — an examiner will spot the inconsistency before you can explain it.
*   **How enforced.** `analysis/aggregate.py` divergence WARN + artifact columns; `tests/test_aggregate.py::test_aggregate_artifact_throughput_restart_proof`.
*   **If violated:** quoting `throughput_p50` for MoQ fanout rows cites restart-inflated numbers (3x demonstrated); quoting status without verdict inverts "more bytes → worse status".

---

*Last updated: 2026-09-07 — `D14` status-ladder reading rule (artifact columns for MoQ fanout); `D13` bounds, `D12` honesty still hold; `D11` short rows, `D10` streaming still hold.*
