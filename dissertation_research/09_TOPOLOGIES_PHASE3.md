# 09 — Topologies Phase 3: Fanout, Fairness, Chain Status (Ch6 §6.3.3/§6.3.6 + §6.4)

`phase3_20260908_164856.log:1816` fanout 8|5|0|3; `:3225` fairness 6|6|0|0; `:4463` chain 6|2|0|4; `:5914` chainfanout 5|0|0|5. All n=1.

## 9.1 Fanout (Fig 6.6)

`fanout_agg:2-9`: `moqrs-2sub/3sub/3sub-loss1pct/late-join-5s pass/mismatch 286333`; `imquic-3sub pass/mismatch 7685 delfrac 0.18 jain 1.0/1.0/1 artifact 7685` — only fanout row with Jain populated; `mixed-moqrs-imquic fail 42964 vs artifact 551` (78× diverge, B38); `moxygen-3sub/late-join fail 0`.

Per-sub honesty from `verify_groups (verify.py:416-535)`: SUM mlogs, MIN prefix, worst-tier verdict, never concat; `report.py:339-399` per-sub table + `[full N/M]` replaces N×100% (B17 FIXED). Cite per-sub artifact bytes + verdict, never mlog throughput for fanout (D14; B38 restarts add connections, `aggregate.py` WARN >2×).

Late-join 5 s (2+1, D6): honest `partial`, not fail — correct live semantics (missed groups never backfilled). `moq-fanout-10s` in Phase 4 shows the ladder nuance: same artifacts cite as `fail` at 128% mlog coverage vs `partial` at 64% (D14). Always pair status with verdict + artifact bytes.

## 9.2 Fairness (Fig 6.3 — liveness, not fairness yet)

`fairness_agg:2-7`: all 6 `pass/mismatch 283–286k` (asymmetric/symmetric/unconstrained/shared-egress-10m/5m/4sub-bottleneck) but `jain_min/p50 empty jain_n 0` — aggregator found <2 positive per-sub bytes (`aggregate.py:55-64`), so no Jain citable. Contrast new headline `moq-vs-lldash_agg_20260908_172709.csv` where `h2/h3-fanout-3 n=3 jain 1.0/1.0/3` remains the only valid fairness number (MoQ fanout `jain_n=1` — one repeat ≥2 positives — not citable).

D12 placement: `devices.sub{i}` = independent last-mile, not shared bottleneck; shared-egress approximation is `devices.relay` (`relay→s1`, `fanout.py:35`). True single-queue CBQ needs OVS QoS — future work. Ch6 Fig 6.3 therefore shows MoQ liveness under asymmetric shapers + H2/H3 Jain 1.0 as baseline; MoQ Jain needs repeats with ≥2 positive per-sub captures.

## 9.3 Chain status (§6.4 — scope note, not results)

`chain_agg:2-7`: `moqrs-moqrs pass/good 286333 rtt 61.14`, `loss1pct pass/good 286333`; `imquic-imquic fail 414`, `imquic-moqrs/moxygen-moqrs/moxygen-moxygen fail 0`. `chainfanout_agg:2-6`: 0/5 (`moqrs-3sub/late-join 0`, `imquic-3sub 1255 Jain 1.0`, `mixed 553`, `moxygen 0`).

History: `REPORT 2026-08-26:166-169` Chain 0/9, hypothesis shared coordinator per-container + unreachable `[::]:4443`. B39 fix (shared `run_dir/coordinator→/moq-coordinator`, `--coordinator-file/--node https://10.250.0.10:4443/ --tls-disable-verify`, `src` fix, `CAP_NET_ADMIN`) verified 2/4 (`REPORT 2026-08-31:97`). Current Sep08: chain 2/6 + chainfanout 0/5 = 2/11. Cross-impl chain rows fail by design (never register into moq-rs coordinator). Chainfanout has no passing config.

Ch6 §6.4 sentence: “Relay chaining is exploratory: same-impl moq-rs chains pass (2/6); cross-impl and chain-fanout remain 0/5 — coordinator-gated, not network-gated. We scope chain as future work and report the coordinator hypothesis with `tc_relay_a.log` evidence.” Cite B33 (inter-relay `relay_delay` verified) + B39 + D12 (`devices.relay_a` + explicit `topology: chain` per-run, else silent `basic` fallback).
