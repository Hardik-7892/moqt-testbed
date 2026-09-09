# 10 — Baselines Phase 4 COMPLETED: MoQ vs LL-DASH H2/H3 (Ch6 §6.3.7, Fig 6.7)

> Status 2026-09-08 18:26 UTC: Phase 4 DONE. `phase4_20260908_172709.log:10349-10366` RESULTS 16|12|0|4 (repeat3), repeat1 12|0|4, repeat2 13|0|3. Citable aggregate `moq-vs-lldash_agg_20260908_172709.csv` (16 rows, all n=3) supersedes `moq-vs-lldash_agg.csv` for headline claims. Phase 5 (`phase5_20260908_183713.log`, `run_20260908_183715`) in progress — BBB smoke only, not results.

## 10.1 Why two baselines (D8) and bounds (D13)

H2 (`nginx:alpine` TCP+TLS 443) vs H3 (`caddy` QUIC+TLS udp 443) with same certs + 2 s segments (`MP4Box -dash 2000 -frag 2000`, one GET/2 s ≈ one MoQ object). H2-vs-H3 isolates transport (TCP HOL vs QUIC); MoQ-vs-H3 isolates app (both QUIC); MoQ-vs-H2 mixes both. Client tries `curl --http3-only` first, then TCP, labelling each segment `via h3 / via tcp-fallback` (`report.py:156-167,170-196`, `verify.py:678-683`, sidecar `segments.json`). MPD may load locally (~1 KB control plane); init+segments must come via HTTP (no local fallback — would bypass `tc` and fake throughput, D9/D10). Workload asymmetry declared: MoQ bulk-push-until-quiesce vs DASH paced-sequential `skip=floor(join/seg_dur)`; throughput mixes denominators — always show `completion_reason` (`quiesced` vs `time-limit`, `runner.py:1402-1466`).

`phase4_172709.log:422` h2 3/3/0/0; `:855` h3 3/3/0/0; `:2443` lldash 8/8/0/0; headline repeats `:5086` 16|12|0|4, `:7722` 16|13|0|3, `:10349` 16|12|0|4 — zero `partial` in all three repeats is itself the signal (old file had 6/6 MoQ `partial`). B36 re-tag before headline rows (`phase4_baselines.sh:34-37`) else all MoQ fail on tag skew. Plan `testplans/moq-vs-lldash.yaml:20` sets `require_integrity:true`; ladder `harness/runner.py:1895-1908` maps full+mismatch→`fail`, so honest expectation for 120 s bulk is now fail-or-flaky-pass, not `expect:partial` (`:26,41,59,77` stale).

## 10.2 Single-protocol baselines (n=1, liveness)

`lldash-h2_agg:2-4`: `h2-clean/bw5/loss1 pass/exact 1034070/1034070/998511 rtt_n 0 delfrac 1.003 artifact identical` — `exact` = per-segment value (`verify.py:606-785`), not whole-file SHA. `h3_agg`: `clean 1120243 bw5 931858 loss1 1190028 exact`. `lldash_agg:2-9`: `h2/h3-basic-clean/chain/fanout-3 pass/exact 0.95–3.39 Mbps fanout delfrac 3.009 (3×) Jain 1.0`; `late-join-5s pass/good 7.03/7.10 Mbps delfrac 2.976 Jain 0.9998` — correct late partial is `good`.

`rtt_n 0` throughout — qlog RTT MoQ-only; H2/H3 transport comparison uses segment completion + `fetch_protos`, never RTT (wire RTT decisioned off, B42). `WARNING: no publisher namespace marker` for lldash expected (no MoQ namespace; completion is manifest-based).

## 10.3 Headline triple (n=3, citable — SUPERSEDES old 200–300× gap)

Old `moq-vs-lldash_agg.csv:12-17` (MoQ 3k/delfrac 0.017 `partial/mismatch`) is superseded by `moq-vs-lldash_agg_20260908_172709.csv:12-17` (MoQ ~2.3M/delfrac 0.998 `fail-or-pass/mismatch-or-good`). Do not cite the old gap.

New (all n=3, `rtt_n=3` MoQ qlog-only, `rtt_n=0` H2/H3 by design, `ttfo_n_null=3` everywhere — no TTFO claim):

- H2/H3 all `pass×3/exact×3`: `h2-clean 873547/988493 h2-bw5 904006/1005422 h2-loss1 722306/749954 h3-clean 1195910/1199467 h3-bw5 890696/981590 h3-loss1 1180353/1192584 h2-10s 271752/274066 h3-10s 288906/288906`; `h2-fanout-3 3050073/3073337 h3-fanout-3 4101229/4150537 delfrac 3.009752 Jain 1.0/1.0/3` (sum over 3 subs, no WARN, `artifact_thr==throughput` <0.1% — measurement stable). `delfrac` invariant 1.003251 (120 s basic) / 1.006761 (10 s) / 3.009752 (fanout) = per-segment value `exact` (`verify.py:606-785`, D10), not whole-file SHA. Deltas vs old +12–46% are repeat noise (`tc htb quantum big`), not behaviour change.
- MoQ bulk 120 s now delivers full: `moq-clean 2331016/2344639 delfrac 0.998687 artifact 2330864 fail+pass+fail/mismatch+good+mismatch (61/61 903210 B r1/r2, 60/61 887997 B missing [10] r3)`; `moq-bw5 2223431/2340758 delfrac 0.998687 fail×3/mismatch×3 (60/61 missing [7], 59/61 missing [7,59] 872837 B)`; `moq-loss1 2316074/2350022 delfrac 0.998687 pass×3/good×3 (61/61 903210 B ×3)`; `moq-fanout-3 2353795/4458454 delfrac 1.997373 fail/mismatch artifact 2309776 (WARN mlog 1806538 vs artifact 889264 repeat2, B38 restart 2.03×)`; `moq-fanout-10s 561474/816615 delfrac 1.995591 fail/mismatch artifact 283714 (WARN 215466 vs 107457 repeat2)`. Throughput `delivered×8/duration` (`measure.py:69-72`): ~900 kB×8/3.1 s quiesced (`phase4 log:2563,2617,3468,5254,7890,10416`) vs old ~3 kB×8/40 s time-limit — 720–755× flip is delivery (B25 repin `a6ed4e9→2d16c9c8` + B37 segment gate + B38 supervision + FAST_IO staging), not rescaling.
- MoQ 10 s control: `moq-clean-10s 286333/286333 delfrac 0.997796 pass/good (11/11 107457 B ×3)` — small media both fast and byte-correct. D11 premise inverts: scale no longer blocks coverage, it blocks exactness (1 missing group in 61 fails SHA under `require_integrity:true`).

Ratios invert the headline: `moq-clean 2331016` vs `h2-clean 873547` = 2.67× above H2, vs `h3-clean 1195910` = 1.95× above; `moq-loss1` 3.21×/1.96× above; `moq-bw5` 2.46×/2.50× above (artifact columns agree). The 200–300× deficit is gone as throughput/coverage. What remains is an integrity deficit: 120 s bulk 4/6 `fail` on `mismatch` at 0.998 coverage (only `moq-loss1×3 good` + `moq-clean r2 good` clear `mlog==expected AND prefix≥90%`, `verify.py:358-365`); clean fails while loss1 passes — flake/race, not HOL. `moq-clean fail+pass+fail` on 61/61→61/61→60/61 is B26 tail/ANSI value flake (r1/r2 identical bytes diverge on value). Fanout cite `artifact_thr_*` only (D14, `aggregate.py:131-137` WARNs); `jain_n=1` for new MoQ fanout (only one repeat ≥2 positives) vs H2/H3 `jain 1.0/1.0/3` — no citable MoQ Jain.

Fig 6.7 must split `status` vs `verdict` columns, show `media + completion_reason quiesced vs time-limit + denominator + integrity gate` per D13 (`decisions.md:158-167`), append `via h3/tcp-fallback` (`report.py:156-196`), and caption D14 (high-coverage mismatch `fail` vs low-coverage `partial`). Otherwise 12|0|4 with 0 partial reads as regression when it is progress in delivery with stricter value check. `expect:partial` (`moq-vs-lldash.yaml:26,41,59,77`) now maps to confusion `?/FN` (`runner.py:1911-1922`), not TP — update expectation to fail-or-flaky-pass (120 s) / pass (10 s, loss1).

Fig 6.7: overlay MoQ/H2/H3 artifact throughput + `completion_reason` + `via` label + D13 bounds caption. State denominators differ; live-paced MoQ publishing (parity) is future work. Loss5 extension lives in pilot file 15 §§15.1–15.2 (`missed-p0_agg_20260908_203017.csv` n=1: H3 425508 vs H2 473218 — H3 advantage gone at loss5, duration-driven per sidecar `{h3:61}` zero-fallback; MoQ-loss5 fail/mismatch at 0.998687 as D14 predicted) — promote only at REPEATS=3.

## 10.4 Short-media control (D11)

`moq-vs-lldash.yaml:96-125` 4× `sample.mp4` 10 s 20 s (`moq/h2/h3-clean-10s` + `moq-fanout-10s`, 5×2 s segs, per-media MPD `sample10-*` so 60-seg set never collides). If MoQ passes 10 s but stays partial on 120 s, gap is scale (B25), not protocol. Keep 12×120 s rows untouched (16 total).

## 10.5 Second campaign Sep09 (n=2) + n=5 merge procedure

`moq-vs-lldash_agg_20260909_010139.csv` (batches `run_20260909_011359` + `run_20260909_012801`, invocation `phase4_20260909_010139.log`): H2 rows stable-ish (clean 873k→1122k, loss1 722k→753k, bw5 904k→1035k, all exact), H3 rows down (clean 1196k→922k, loss1 1180k→691k, fanout 4.1M→2.7M, all still exact), MoQ mixed (clean pass+fail 2.36M consistent; loss1 pass+fail 1.26M vs 2.32M halved; fanouts delfrac 1.50 vs 2.00; bw5 0-byte stall both repeats). Between-campaign drift is real on H3/MoQ, negligible on H2 — do not pool Sep08 with Sep09 silently.

**n=5 merge (your call 1.a, VM-side — no python3 on this host):**
```bash
python3 analysis/aggregate.py \
  artifacts/runs/run_20260908_172710 artifacts/runs/run_20260908_172915 \
  artifacts/runs/run_20260908_173116 artifacts/runs/run_20260909_011359 \
  artifacts/runs/run_20260909_012801 \
  --out artifacts/reports/moq-vs-lldash_agg_n5_$(date +%Y%m%d_%H%M%S).csv --min-repeats 3
```
Report three columns per row: Sep08-only (n=3), Sep09-only (n=2), pooled (n=5) — campaign as documented covariate. MW on pooled n=5 is valid only where campaign drift is small vs effect (H2 rows: yes; H3/MoQ rows: report U with the drift caveat, or restrict inference to within-campaign n=3). moq-bw5 pooled spans regimes (2.2M delivery vs 0-byte stall) — exclude from pooled inference, cite as bimodal exhibit (§15.9) instead.

**moq-bw5 root cause (investigated, file 15 §15.9):** B38 silent-variant track race (`track_alias=2 not found` storm at `subscriber.rs:1878`), not B25 starvation — bytes reached the relay (RX 963 KB), the sub died serving. Timing kills under bw5 shaping, not bandwidth. `expect` left for Ch6 discussion per your call; never a throughput point.
