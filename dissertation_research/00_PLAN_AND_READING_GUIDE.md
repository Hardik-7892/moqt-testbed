# Dissertation Research Plan — MoQT Testbed Deep Dive

**Folder:** `dissertation_research/` (approved 2026-09-08; user wrote dissertation_report — same folder)
**Scope permission:** Code + reports only (no `dissertation/` drafts read)
**Execution permission:** Read-only analysis only (no Docker, no `make test`, VMs untouched)
**BBB framing:** Future work (B22/B25), not citable results
**Status 2026-09-08 18:26 UTC:** Phase 4 COMPLETED (`phase4_20260908_172709.log` 16|12|0|4, `moq-vs-lldash_agg_20260908_172709.csv` n=3 supersedes old). Phase 5 STARTED (`phase5_20260908_183713.log`, `run_20260908_183715` BBB smoke) — not results.
**Method:** Autonomous synthesis from `registry.json`, `harness/`, `topologies/`, `testplans/`, `evaluation_tests/`, `artifacts/reports/*.csv + phase*.log`, `decisions.md`, `found-bugs.md`, `Makefile`, `IMPLEMENTATION_REGISTRY.md`
**Supervisor critique addressed:** n=1 labelled exploratory (only quick + headline n=3 citable), wire RTT qlog-only (tshark 4.6.4 no `quic.ack.rtt`, header-only pcaps), throughput denominators quiesced vs time-limit (D13_tuple in every caption), CLEAN `base.py:18` vs `scenarios.yaml:5-9` reconciled as runtime-vs-doc, D12 last-mile vs shared-egress, chain queue exclusion, no jitter/reorder, draft tag≠wire (B46), bugs as limits (B25/B37/B38/B35/B36), sleeps/sudo/paths/`workers>1` disclosed, RQs rescoped DASH-only single-relay+last-mile (chain/WebRTC future), 5-experiment Ch6 freeze, IEEE ~20, AI declaration plain.

## What this folder is

PhD-level expert analysis to let you write:

- **Ch5 Implementation** — registry, topology, harness modules, testplans/media, build-time limits, bug stories with evidence chains.
- **Ch6 Evaluation** — verification (RQ1), interop (RQ2), performance sweeps (RQ3–RQ5), chain status, baselines (MoQ vs H2/H3), threats, summary tables.

Total target: ~20+ pages (~9000+ words). This folder delivers ~13 files, ~15000 words (~30 pages).

## File map

| File | Question | Pages | Source of truth |
|------|----------|-------|-----------------|
| `00_PLAN_AND_READING_GUIDE.md` (this) | — | — | — |
| `01_MOQT_PRIMER.md` | What is MoQT at protocol level? | ~2 | `harness/quic_alpn.py`, `harness/probe.py`, `IMPLEMENTATION_REGISTRY.md:198-216`, `harness/verify.py:15-19` |
| `02_REGISTRY_IMPLEMENTATIONS_BUILD_LIMITS.md` | Which impls, which drafts, what builds? | ~2.5 | `registry.json`, `docker/*/Dockerfile*`, `Makefile:98-203`, `found-bugs.md:B4/B6/B9/B14/B15/B36` |
| `03_TOPOLOGY_IMPAIRMENTS.md` | How are controlled networks built? | ~2 | `topologies/*.py`, `harness/runner.py:298-388,1202-1321`, `scenarios.yaml`, `decisions.md:D3/D4/D12` |
| `04_HARNESS_MODULES.md` | How does the harness actually run? | ~3 | `harness/runner.py:120-2354`, `harness/verify.py`, `measure.py`, `report.py`, `probe.py`, `certs.py`, `pcap.py`, `playable.py`, `plan_validation.py` |
| `05_TESTPLANS_MEDIA.md` | What experiments, what media, why fair? | ~2.5 | `testplans/*.yaml`, `Makefile:219-270`, `decisions.md:D2/D8/D9/D10/D11`, `evaluation_tests/*.sh` |
| `06_VERIFICATION_METHOD.md` | How is claimed-vs-negotiated verified? | ~2 | `harness/verify.py:814-861`, `harness/probe.py`, `harness/quic_alpn.py`, `harness/report.py:227-248` |
| `07_INTEROP_RESULTS_PHASE1.md` | RQ2: what interops? | ~2.5 | `artifacts/reports/*_agg_20260908_133402.csv`, `phase1_*.log`, `analysis/aggregate.py` |
| `08_PERFORMANCE_SWEEPS_PHASE2.md` | RQ3–RQ5: loss/latency/bw/queue? | ~2.5 | `*_agg_20260908_150236.csv`, `phase2_*.log` |
| `09_TOPOLOGIES_PHASE3.md` | Fanout/fairness/chain status? | ~2 | `*_agg_20260908_164856.csv`, `phase3_*.log`, B17/B33/B39 |
| `10_BASELINES_PHASE4.md` | MoQ vs LL-DASH H2/H3? COMPLETED n=3, integrity deficit replaces coverage gap | ~3 | `moq-vs-lldash_agg_20260908_172709.csv`, `phase4_*.log`, D8/D13/D14 |
| `11_BBB_FUTURE_WORK_PHASE5.md` | Why BBB is future work? | ~1.5 | `testplans/bbb*.yaml`, B22/B25/B37/B38, FAST_IO |
| `12_THREATS_SUMMARY_MAPPING.md` | Threats + Ch5/Ch6 writing map | ~2 | All + status ladder, D14 |

## Reading order for writing

1. If writing **Ch5 today**: read 01 → 02 → 03 → 04 → 05 → 06 → 12 (mapping §5).
2. If writing **Ch6 today**: read 06 → 07 → 08 → 09 → 10 → 11 → 12 (mapping §6).
3. If supervisor asks **“why this design?”**: cite `decisions.md:D2–D14` via 05 + 10.
4. If examiner asks **“why fail?”**: cite 07 (B43–B46) + 09 (chain 2/11) + 11 (B25 ceiling).

## Method notes (honesty)

- All run numbers Sep08 (`122434/133402/150236/164856/172709/183713`). Repeat matrix: `interop-quick n=3 citable | moq-vs-lldash n=3 citable | all sweeps/topologies/single-baselines n=1 exploratory (p50==p95, jain_n 0, no variance)`. `aggregate.py:102-103,169-170` warns `only N repeat(s), want >=3`; `percentile() :39-52` returns single sample at n=1. No Ch6 curve without n≥3 sequential batches `--workers 1` + `--min-repeats 3`.
- Wire = counts only. `pcap.py:140-146` `decryption_success=False` (tshark 4.6.4 no `quic.ack.rtt`, no secrets for quinn/picoquic); `measure.py:392-398` qlog RTT canonical; `REPORT 2026-08-31:127` header-only 86B; capture throttling ~0.77 vs ~31 Mbps (`bbb-smoke-nocap` control). H2-vs-H3 uses completion + `fetch_protos`, never RTT.
- `throughput_p50` (mlog-derived) vs `artifact_thr_p50` (artifact-derived) diverge routinely (B38 restarts). Cite artifact columns for fanout; report warns on >2× divergence (`analysis/aggregate.py:118-158`).
- `pass` ≠ `exact`. Without `require_integrity:true` (only `moq-vs-lldash.yaml:20`), `pass` means `delivered_full` (coverage ≥95%), not byte-verified. All Phase-1 quick passes are `mismatch` verdicts.
- `TTFO` is null in every Sep08 CSV (`ttfo_n_null==n`). No TTFO claim is citable.
- Row labels `d18` for imquic/moxygen are claims, not wire proof (moxygen BOOT-only B46; imquic `-M any` negotiates moqt-16 regardless).
- No Docker executed, no `artifacts/runs` modified, no VM interference. Phase 4 completed, Phase 5 BBB smoke running (`run_20260908_183715`, OVS 1961 pkts/11978235 B in-flight — not results).
- RQ rescope: DASH-only single-relay + last-mile fanout. Chain (2/11 coordinator-gated) + WebRTC (GCC/SFU non-TCLink-comparable `decisions.md:21`) + shared-queue tails/jitter/burst/trace-replay + BBB → future work up front in Ch3.
- 5-experiment Ch6 freeze (all n=3, p50/p95 plots): E1 verification + TN controls, E2 quick 8-row matrix, E3 loss/latency basic-only, E4 fanout per-sub + late-join, E5 headline triple with D13 bounds. n=1 sweeps → appendix.

## Repro checklist (for Appendix)

- `make build-moq-rs / build-moxygen / build-imquic / build-lldash` (`Makefile:98-203`)
- `REPEATS_QUICK=3 ./evaluation_tests/phase1_interop.sh`, `./phase2_sweeps.sh`, `./phase3_topologies.sh`, `./phase4_baselines.sh` (`evaluation_tests/*.sh`)
- `python3 analysis/aggregate.py <batches> --out <csv> --min-repeats 3` + `make report` (`harness/report.py:552-564`)
- `python3 -m harness.verify` (`Makefile:208-209`, `harness/verify.py:858-861`)
