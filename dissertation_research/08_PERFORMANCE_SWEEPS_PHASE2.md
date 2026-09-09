# 08 — Performance Sweeps, Phase 2 (RQ3–RQ5, Ch6 §6.3.1–§6.3.4) — EXPLORATORY n=1, APPENDIX ONLY

> Supervisor rule: `phase2_sweeps.sh:3,17-22` + `phase3_topologies.sh:3,16-22` run once then `aggregate --min-repeats 1`, defeating default `--min-repeats 3` (`aggregate.py:166,102-103,169-170`). At n=1 `percentile() :39-52` returns the sample (p50==p95), `jain_n` 0 (`:55-64`), `ttfo_n_null==n`. No error bars, no variance, no p95-p50 gap citable. Freeze rule: no Ch6 main-matter curve without ≥3 sequential batches same VM `--workers 1`. What follows stays in appendix until re-run at n=3 (~6 h + ~2 h) or rescoped out.

## 8.1 Loss (`loss_agg:2-24`, 23 total | 12 pass | 3 partial | 8 fail)

- `loss-0/0.1/0.5/1/2/10/20pct-moqrs pass/mismatch 13.9–29.3 Mbps delfrac 0.999967 rtt 7–225 ms` — moq-rs survives 20% loss on bulk media. Scale differs from Phase 1 (large file vs tiny `sample_1seg`).
- `loss-5pct-moqrs partial/mismatch 2529803 vs artifact 140` — 18000× diverge, textbook B38 WARN; do not cite mlog throughput.
- `loss-1/5/10pct-chain pass/mismatch 14.1/14.1/13.9 Mbps` — chain moqrs-moqrs tolerates loss when coordinator works.
- `loss-1pct-fanout-3sub fail`, `5pct-fanout partial 0.188`, `asymmetric partial 0.179` — fanout degrades first.
- `loss-1/5pct-imquic-self pass/mismatch 2653/2725 delfrac 6e-05` (`object_receipt` counting, bytes incomparable); `imquic-relay/sub, moxygen-relay/self` fail 0–183.

Hypothesis→result (for Ch6): “QUIC recovery hides loss on bulk single-sub; fanout is the loss-sensitive topology.” Explanation: per-sub independent shapers + mlog-sum vs artifact divergence; imquic `object_receipt` bytes not comparable to media bytes.

## 8.2 Latency (`latency_agg:2-20`, 19 | 13 pass | 0 partial | 6 fail)

`lat-5/10/20/50/100/200ms-basic pass/good 276–286k delfrac 0.997 artifact ~285k` — flat vs delay, QUIC hides 200 ms on this size; `chain 10/50/100 pass`, `fanout 10/50 pass`; `imquic-self 20/100 pass 2521/2577`; all `moxygen-self fail 0`; `imquic-relay/sub 50 fail`. `rtt_p50` is qlog RTT (7–106 ms), not netem delay — do not read as delay validation.

## 8.3 Bandwidth (`bandwidth_agg:2-23`, 22 | 15 pass | 0 partial | 7 fail)

`bw-1/2/5/10/20/50/100mbps-moqrs pass/good ~281–286k` — flat because media≪cap; `chain 10/20/50 pass/good`; `fanout 20-3sub/asymmetric + 10-4sub-bottleneck pass/mismatch`; `imquic-self 10/50 pass 2570/2665`; all moxygen + relay/sub fail. Lesson: bandwidth sweeps need `sample_120s`/BBB to separate caps; on `sample.mp4` they prove liveness, not shaping.

## 8.4 Queue / bufferbloat (`queue_agg:2-25` 24|21|0|3; `bufferbloat_agg:2-5` 4|4|0|0; `impairments_agg:2-19` 18 conceptual pass)

`queue-10/20/50/100/200/500/1000 + chain + fanout + bw5/50×queue` all pass (moqrs 286k `good`/`mismatch`); only moxygen-self fail. `queue-100-fanout 14323 vs artifact 12872` outlier vs 285k siblings — single-sample noise, needs repeats. `bufferbloat q10/q50/q200/q1000 pass/good 284–286k`. `impairments loss-5pct 42456 vs artifact 17163` vs siblings 255–286k — same B38 divergence.

BDP framing for Ch6 Fig 6.4: `queue-sweep.yaml:10-17` (`5 Mbps/20 ms BDP≈12.5 KB≈8 pkts`; 10 below-BDP `expect:partial` through 1000 extreme). Current data show no bufferbloat curve on small media — honest null, not failure. State validity limit: `max_queue_size` pub/sub only, inter-relay uncontrolled, so chain queue rows are end-to-end.

## 8.5 What to plot (Fig 6.1, 6.4) — appendix until n=3

Fig 6.1 loss/latency/bandwidth curves: x=impairment, y=`artifact_thr_p50` (not mlog throughput) + `delfrac_p50`, split basic/chain/fanout, moq-rs only (cross cells fail by design). Annotate `n=1` + B38 WARN points excluded. Fig 6.4 queue/bufferbloat: x=`max_queue_size` log, y=artifact throughput + qlog RTT; note flat null + BDP line. Both need repeats before thesis claims variance. Main-matter Ch6 E3 replaces these with moq-rs basic-only loss 0–5% + lat 5–100 ms at n=3 (`sample_1seg`, `artifact_thr_p50/p95 + delfrac + rtt_p50/p95` with IQR bars, B38 points excluded).

## 8.6 CLEAN + not-modelled honesty boxes (for Ch4 Table 4.1)

CLEAN: `topologies/base.py:18` runtime `1000M/1ms` for unlisted roles is what runs; `scenarios.yaml:5-9` `clean 100/10ms` + `topology.yaml:5-25` + `harness/topology.py|scenarios.py` are doc/dead code (B8, imports commented `runner.py:36-42`). State which branch ran per row. Not-modelled: allow-list `plan_validation.py:47` is only bw/delay/loss/max_queue_size/relay_delay; `measure.py:40` `jitter_ms=None` always — no jitter/reorder/duplicate/corrupt, no AQM (quarantined `future/`, `Makefile:403-409`), no ECN/BBR-vs-CUBIC. Chain queue rows = end-to-end (`client_roles` pub/sub only `base.py:76-78`, `chain.py:90-91`, inter-relay uncontrolled `decisions.md:152`). D12 labels: `devices.sub{i}` = independent last-mile (top-level bw ignored, relay 1000M/1ms), shared-egress only `devices.relay` with `tc_relay.log htb` evidence; true CBQ needs OVS QoS — future work.
