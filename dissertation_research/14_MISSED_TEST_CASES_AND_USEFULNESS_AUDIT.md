# 14 — Usefulness Audit (Genuine vs Cargo-Cult) + Missed Test Cases

> Loop pass 2026-09-08 19:50 UTC. Scope: `dissertation_research/` writes only; everything else read-only. Status: Phase 4 COMPLETED (`moq-vs-lldash_agg_20260908_172709.csv` n=3, 16|12|0|4); Phase 5 RUNNING (BBB smoke, not results).

## A. Was each thing we did genuinely useful, or just because others do it?

PhD rule applied: a mechanism stays iff (i) it changes a citable verdict/number, or (ii) it prevents a silent false claim. Otherwise it is cargo-cult and belongs in future work or appendix.

### A1. H2 + H3 triple (D8) — GENUINE, keep
Others run one baseline (usually H2/nginx or no baseline). Single baseline confounds transport (TCP HOL) with app semantics (segment fetch vs object push). Your triple separates them: H2-vs-H3 isolates transport (both DASH, TCP vs QUIC); MoQ-vs-H3 isolates app (both QUIC). Evidence it mattered: `moq-vs-lldash_agg_20260908_172709.csv` H2-clean 873k vs H3-clean 1195k (+37%) quantifies the transport dividend on identical segments; MoQ-clean 2331k vs H3-clean 1195k then quantifies app bulk-push vs paced-fetch on identical QUIC family. Without H3 you would have misattributed ~1/3 of every gap to MoQ. Cost: 2× baseline rows. Verdict: genuine, load-bearing for Fig 6.7. Cargo-cult version to avoid: adding WebRTC “because others compare to it” — GCC/SFU vs QUIC-CC/cache is non-`TCLink`-comparable (`decisions.md:21`); you correctly deferred it.

### A2. Same source + 2 s GOP/segment alignment (D2/D2.2) — GENUINE, keep
Others reuse whatever clip each stack ships, then rank throughputs. Different inputs explain any gap before protocols are compared. Your `ffmpeg lavfi` single source (`Makefile:219-237`, `g 60` 2 s) + `MP4Box -dash 2000 -frag 2000` makes one MoQ object ≈ one DASH GET, so request concurrency under loss/bw is comparable and late-join miss math is defined (`5 s → ~2 groups`, not 5-vs-2). Evidence it mattered: `sample_1seg` vs `sample.mp4` vs `sample_120s` produce 287k vs 286k vs 2331k for the same impl — media, not impl, sets scale. Without alignment every cross-media ranking in §7–8 would be invalid. Verdict: genuine. Cargo-cult trap you avoided: cinematic BBB “because realistic” — Blender `ftypM4V` non-fragmented crashes `moq-pub` (B22) and 121 MB stalls the relay (B25); realism that breaks the publisher measures nothing.

### A3. Per-device single-wire impairments + `tc_*.log` receipts (D3/D4/B12) — GENUINE, keep
Others apply one `tc` rule “on the link” and report the nominal value. Double-placement (`delay:10ms` on pub + sub) silently doubles RTT and squares loss (`found-bugs.md:286-302`). Your `link_params_for_role()` + `_verify_impairments()` + per-host `tc_{host}.log` makes `delay:10ms` mean 10 ms and fails the run if shaping is absent. Evidence it mattered: pre-fix sweeps never built a chain at all (missing per-run `topology:` silently ran as `basic`); post-fix `devices.relay_a` rows carry `tc_relay_a.log htb+netem` proof. Verdict: genuine — this is the “controlled” in controlled networks. Cargo-cult: `scenarios.yaml` named profiles + `topology.yaml` + `TopologyBuilder/ScenarioApplier` (B8 dead code) — documented profiles nobody runs. Keep the receipt, delete the theatre in Ch5 (say B8 plainly).

### A4. Relay-mlog authority + prefix SHA + exact/good/mismatch (B26/D9/D10) — GENUINE, keep
Others count bytes (`rglob("*")`, B17) or trust stdout size. `moq-sub` interleaves ANSI logs with media on stdout (107% “delivered”, B26) and drops a deterministic 32 B tail; FLV stdout + file double-counts (B18); fanout sums N copies (B17). Your mlog-sum (subscriber `subgroup_object_created`) + `expected_media_bytes()` (init + moof/mdat, excl. mfra/free) + SHA + prefix + `good = mlog==expected AND prefix≥90` is the only chain that killed >100% and 4 KB-pass (B24). Evidence: new headline `moq-clean` 61/61 mlog-complete yet `mismatch` on value — count alone would have passed a wrong byte. Verdict: genuine. Cargo-cult risk: `good_threshold 90.0` / `coverage 0.95` / `quiet 3 s` are unvalidated constants — state them as such with a sensitivity sweep as future work, or they become new folklore.

### A5. STRICT verification, never return claimed (B16/B28) — GENUINE, keep
Others tabulate vendor draft claims. Your probe returns `None` on `boot/unverified` and grades `setup/alpn/tap14` only. Evidence: moxygen `:18` tags are one build retagged (`Makefile:126-131`), WT CH shows only `h3` (B46), raw offers never `moqt-18` — a claim table would print three lies. Current Table 6.1 (moq-rs UNVERIFIED-honest / imquic CONFIRMED-if-pinned / moxygen BOOT-only) is less flattering and more citable than any “support matrix.” Verdict: genuine. Cargo-cult: probing every `(impl,draft)` pair “because matrix looks complete” — imquic `any` negotiates highest-common regardless of row label; unpinned rows are draft-ungraded and must be excluded, not tabulated.

### A6. Fanout + chain topologies — SPLIT: fanout genuine, chain exploratory, shared-bottleneck claim cargo-cult
Fanout genuine: 1→N with per-sub artifacts + worst-sets-verdict + `[full N/M]` (B17 fix) is the scaling claim (R5); mixed-impl `sub3` override + late-join-5s already yielded D6/D14 lessons. Chain exploratory: 2/11 coordinator-gated, `chainfanout` 0/5 — measures the demo coordinator, not relay-to-relay protocol. D12 honesty (independent last-mile vs `devices.relay` shared-egress approximation, true CBQ needs OVS QoS) is what saves this from cargo-cult: you label what you did not build. Kill any sentence calling `devices.sub{i}` rows “shared bottleneck.”

### A7. FAST_IO staging — USEFUL INSURANCE, not a result
Others ignore shared-folder sync effects. Your paired verdict NEUTRAL (staged 98 MB 87.95% ~2.6 Mbps inside unstaged 2–4 Mbps band; shared folder exonerated) is the right shape: keep as cheap insurance for pcaps, never as Fig 6.2 headline. Cargo-cult would be citing staged-vs-unstaged deltas as impl wins.

### A8. Pcaps + qlogs + SSLKEYLOGFILE — SPLIT: qlog RTT genuine, pcap wire RTT cargo-cult (today)
qlog RTT genuine: only transport-observed number you have (`measure.py:164-262`, seconds vs picoquic µs handled). Pcap decrypt for `quic.ack.rtt` on tshark 4.6.4 decisioned OFF (B42: no decryption context, header-only 86B, throttling ~0.77 vs ~31 Mbps) — capturing “because EXECUTION_PLAN says pcaps” without a decrypt path is theatre. Keep capture opt-in + `bbb-smoke-nocap` control; claim packet/byte counts only.

### A9. Sweeps at n=1 — CARGO-CULT if plotted as curves, GENUINE as pilot
`phase2_sweeps.sh` 1× each + `aggregate --min-repeats 1` defeating its own ≥3 rule produces p50==p95 with no variance; `queue-100-fanout` outlier proves it. As Ch6 curves they are fraud; as pilot to size n=3 windows (which impairments move `artifact_thr`, which are flat) they are useful. Current file 08 appendix-only treatment is correct.

## B. Missed interesting test cases (in existing plans’ blind spots)

Priority = (novel mechanism × thesis leverage) / cost. All row sketches assume `require_integrity:true`, explicit per-run `topology:`, `artifact_thr_*` citation, `completion_reason` caption. None require new harness code except where marked [CODE].

### B1. H3-fallback under loss 5% [P0, no code, 3 rows]
Gap: headline tests H3 only at loss1. H3 client falls back `curl --http3-only` → TCP (`client.py:84-129`, `via h3/tcp-fallback` label D13); at loss5 the fallback fraction is the transport story (QUIC giving up vs persisting). Existing `h2-loss1/h3-loss1` cannot see the knee.
Rows: `h3-loss5`, `h2-loss5`, `moq-loss5` on `sample_120s.mp4` 40 s (mirror §10.3). Hypothesis: H3 degrades toward H2 throughput as `fetch_protos` flips to fallback; MoQ (no fallback, subgroup timeouts) diverges. Why interesting: only row that tests the label you built. Cost: ~15 min.

### B2. Late-join 30 s on 120 s media [P0, no code, 2 rows]
Gap: `fanout.yaml` late-join-5s (2+1) on 10 s/120 s proves honest `partial`, but 5 s ≈ 2 groups missed; 30 s ≈ 15 groups missed exercises cache eviction + `FILL`/`FETCH` backfill path (draft-20 relevance) and `skip=floor(30/2)=15` verification. Existing D6/D10 machinery already supports it (`--join-delay`, `verify_lldash_streaming` skip).
Rows: `moq-late-join-30s`, `h3-late-join-30s` fanout N=3 on `sample_120s.mp4`. Hypothesis: MoQ serves from current group onward (suffix `good`), DASH serves DVR window (suffix `good`) — both `partial` overall, verdicts equal, `group_missed_on_join` differs by one group (MoQ group vs DASH segment boundary). Cost: ~15 min.

### B3. imquic `-M any` vs `-M {draft}` paired rows [P0, no code, 2 rows]
Gap: B4/`registry.json:115` warns default `any` negotiates `moqt-19` even on `d18` rows, but no paired measurement proves the row-label threat. This is RQ1’s cheapest experiment.
Rows: `imquic-self-d18-pinned (-M 18)` vs `imquic-self-d18-any` same media/topology, both `require_draft:true`, quote `-- WebTransport (moqt-N)` per row. Hypothesis: identical `object_receipt` counts, different negotiated ALPN — proves tag≠wire without claiming performance. Cost: ~10 min.

### B4. FLV under loss1/bw5 (moxygen parity rows) [P0, no code, 2 rows]
Gap: `moxygen-self.yaml` has 2 clean rows only; every impairment comparison is therefore moq-rs-vs-nothing on FLV path. MoQMI-over-loss behaviour (transmux approximate, no SHA-exact expectation) is unmeasured.
Rows: `moxygen-loss1`, `moxygen-bw5` on `sample.flv` (mirror `moq-loss1/bw5` timing). Expect `good`-at-best (transmux), compare `byte_identical_pct` distributions not verdicts. Cost: ~15 min.

### B5. Queue×loss interaction (bufferbloat under loss) [P1, no code, 4 rows]
Gap: `queue-sweep.yaml` fixes loss 0; `loss-sweep.yaml` fixes queue 1000. Standing queue + loss is the bufferbloat collapse regime (deep queue + RTO vs shallow + drop). Existing I16 signature (`queue:1000` at `bw:5` ≈2 s) never meets loss.
Rows: `bw5 × {queue100, queue1000} × {loss0, loss1}` basic moq-rs on `sample.mp4` 60 s. Hypothesis: q1000+loss1 collapses `artifact_thr` vs q100+loss1 (RTO amplification); q1000+loss0 flat (current null). Cost: ~30 min.

### B6. Inter-relay loss vs sub-leg loss separation [P1, no code, 2 rows]
Gap: chain rows shape `devices.relay_a` OR sub leg, never both in one batch to attribute relay-to-relay vs edge fragility. D12 machinery exists.
Rows: `chain-loss1-inter-relay-only` (`devices.relay_a {loss:1}`, sub CLEAN) vs `chain-loss1-sub-only` (top-level loss1, inter-relay CLEAN) on `sample.mp4`. Hypothesis: inter-relay loss hurts all downstream (shared fate) while sub-leg loss hurts one (isolated) — the only chain comparison that justifies two relays. Cost: ~15 min.

### B7. Datagram vs stream at loss1 (un-quarantine ONE pair) [P1, minimal code, 2 rows]
Gap: `future/datagram-vs-stream.yaml:31-60` quarantined on unwired `mode:` key, yet moq-rs supports both modes — this is MoQ’s HOL answer (QUIC streams vs datagrams, OBJECT timeouts) and your H2/H3 triple’s natural sibling. Full 6-row plan needs wiring; ONE basic pair does not: run same row twice with env/mode flag once `mode` is threaded (single-key wire + unit test + `tc` evidence per re-admission rule).
Rows: `moq-datagram-basic-loss1` vs `moq-stream-basic-loss1`. Hypothesis: datagram loses objects (lower `delfrac`, lower tail latency) while stream stalls (higher `delfrac`, higher completion time) — the deadline-vs-reliability trade your §1.5 promises but never measures. Priority high because no other missed case tests a MoQ-native mechanism.

### B8. 0-RTT / FILL backfill join latency [P2, needs draft-20 pin, 2 rows]
Gap: Table 2.1 (draft-20 `FILL_PARAMETERS` 1-RTT join+backfill) is survey-only; no row measures join cost. With current pin, approximate via `late-join-5s` + `first_object_after_join_ms` per-sub (already logged) at 5 s vs 30 s; with draft-20 pin, add true FILL rows. Defer wire until pin, but add the two timed late-joins now — they cost nothing and bank the baseline.

### B9. Larger-N fanout (N=8) + asymmetric delay (not just bw) [P2, no code, 2 rows]
Gap: fanout varies bw, never delay skew (straggler viewer holding relay state?) and never N>4. One `N=8 CLEAN` + one `N=3 delay {10,50,200}ms` row tests worst-sets-verdict scaling and per-sub RTT spread at constant `artifact_thr`. Cheap, high Ch6 Fig 6.6 leverage.

### B10. What NOT to add (cargo-cult rejections with reasons)
- Full 23-row `cross-impl.yaml` repeats at n=3: cross cells fail by design (B43 framing gaps); repeating 22 fails buys no mechanism. Keep n=1 TN documentation.
- `bbr-cubic-fairness` / `aqm-sweep` full plans: quarantined on unwired `cc_algos/aqm` keys; congestion-control identity is a transport study needing CC instrumentation you do not have (qlog CC fields unparsed). One shared-egress Jain at n=3 (existing `devices.relay` rows) precedes any CC claim.
- `multi-pub-sub` / `track-priority` / `congestion-cascade`: unwired `publishers/tracks/filter/group_order` keys; N-pub cache sharing is a second thesis. Cite as future work, not half-wired rows.
- BBB at n=3 now: Phase 5 smoke in-flight; 121 MB × capture (~150 MB/host) × repeats is GBs/batch with B37/B38 open. Bank video-only + reconstruction validation first.

## C. Loop log
- 19:47Z baseline audit (14 files, 00–13).
- 19:48Z status fix in 05 (Phase 4 COMPLETED, Phase 5 RUNNING, stale `expect:partial` noted).
- 19:50Z this file created (usefulness audit A1–A9 + missed cases B1–B10).
- Remaining loop: hardening passes on 03 (CLEAN box already present — verify), 06 (Table 6.1 caveats), 09 (chain 2/11 wording), 12 (repeat matrix present — verify), then final word-count + timer hold to 10 min.

## D. Built from this file (post-timer request)
- `testplans/missed-p0.yaml` (9 rows, VALID by inspection against `harness/plan_validation.py:17-71`): B1 h3/h2/moq-loss5 on `sample_120s.mp4`; B2 moq/h3-late-join-30s fanout (`late_sub_count:1`, `late_join_delay_s:30`, duration 70 > 30 + delivery); B3 imquic-pin-d18/d16 (`object_receipt`, `require_draft:true`, `require_integrity:false`); B4 moxygen-loss1/bw5 on `sample.flv`. Local `moq-rs/*:18` tags (no B36 re-tag needed); lldash `0hardikpandey/*:latest` (only prefix built by `Makefile:180-200`).
- `testplans/missed-p1.yaml` (8 rows): B5 queue100/1000 × loss0/loss1 on bw5 (`max_queue_size` wired); B6 chain leg pair (`topology: chain` per-run, `devices.relay_a` vs sub-leg, `relay_delay` explicit); B9 fanout N=8 + delay-skew (`sub1:10ms/sub2:50ms/sub3:200ms`, independent-last-mile label per D12). B7 datagram excluded on purpose: run-level `mode` is in `UNWIRED_RUN_KEYS` and fails validation — needs the §B7 single-key threading first.
- `evaluation_tests/phase6_missed.sh`: `ONLY` + `REPEATS` support (default REPEATS=1 appendix-only pilot; REPEATS=3 citable), testdata preflight, VM-side `validate_testplan` gate before any run, per-plan `aggregate.py` + `make report`. Calls `run_testbed.py --plan` directly so no Makefile edits were needed.
- To run on VM: `REPEATS=1 ./evaluation_tests/phase6_missed.sh` (~45 min: P0 ~10 + P1 ~6 + subgroup-drop ~25–30 on 111 MB media) then `REPEATS=3` for citable headline-adjacent rows only.
