# 13 — Evidence Index: Where Every Claim Lives

## Run batches (Sep08, cited throughout)

- `run_20260908_122410/122434/133402` → Phase 1 (quick×3, moqrs-self, mismatch, built, full, cross-impl). Logs `artifacts/reports/phase1_*.log` (15441 lines sampled).
- `run_20260908_150236` → Phase 2 (loss/queue/bufferbloat/latency/bandwidth/impairments, 21289-line log).
- `run_20260908_164856` → Phase 3 (fanout/fairness/chain/chainfanout, 7102-line log).
- `run_20260908_172709` → Phase 4 (h2/h3/lldash + headline ×3, 10573-line log). Citable agg `moq-vs-lldash_agg_20260908_172709.csv` (16 rows n=3) supersedes `moq-vs-lldash_agg.csv`.
- `run_20260908_183713/183715` → Phase 5 BBB smoke: `bbb-smoke_agg_20260908_183713.csv` (`moqrs-d18-bbb-smoke` pass/mismatch 5503004, delfrac 0.9986 — full-coverage delivery, value gap persists; pilot).
- `run_20260908_203020/204043` → Phase 6 pilot (missed-p0 9 rows 5|0|4, missed-p1 8 rows 8|0|0). Aggs `missed-p0/p1_agg_20260908_203017.csv` (n=1). First attempt `phase6_20260908_202030.log` KeyboardInterrupted (h3-loss5 ~9.5 min wall — paced retries at loss5; see file 15 §15.6).
- Phase 5 BBB: `bbb-smoke_agg_20260908_183713.csv` — pilot only (see file 15 §15.6, file 16 §16.1-F4).

## CSVs (all in `artifacts/reports/`)

Interop: `interop-quick/moqrs-self/interop-mismatch/interop-built/interop-full/cross-impl_agg_20260908_133402.csv`. Sweeps: `loss/latency/bandwidth/queue/impairments/bufferbloat_agg_20260908_150236.csv`. Topologies: `fanout/fairness/chain/chainfanout_agg_20260908_164856.csv`. Baselines: `lldash-h2/h3/lldash_agg_20260908_172709.csv`, `moq-vs-lldash_agg_20260908_172709.csv` (citable; old un-stamped csv superseded). Phase 6 pilot: `missed-p0/p1_agg_20260908_203017.csv` (n=1). BBB pilot: `bbb-smoke_agg_20260908_183713.csv` (n=1).

## Key code pointers

Registry: `registry.json:8-181` + `IMPLEMENTATION_REGISTRY.md:198-227`. Builds: `Makefile:98-270` + `docker/*/Dockerfile*`. Harness: `harness/runner.py:120-2354`, `verify.py:36-861`, `measure.py:30-399`, `report.py:227-564`, `probe.py:43-471`, `certs.py:99-121`, `pcap.py:13-184`, `playable.py:57-144`, `plan_validation.py:17-143`, `quic_alpn.py:28-253`. Topologies: `topologies/base.py:18-82`, `basic.py:11-25`, `chain.py:14-96`, `fanout.py:14-70`, `chainfanout.py:17-117`. Plans: `testplans/*.yaml` + `evaluation_tests/phase*.sh`. Rules: `decisions.md:D2-D14`. Bugs: `found-bugs.md:B1-B46` (esp. B4/B6/B9/B12/B13/B17/B18/B19/B20/B22/B24/B25/B36/B37/B38/B43-B46).

## Glossary

ALPN, QUIC v1 Initial, WebTransport, mlog/qlog, JSON-SEQ, `subgroup_object_created`, `publish_namespace/subscribe_ok`, `AbsoluteStart`, `completion_coverage 0.95`, `delivered_full`, `exact/good/mismatch`, `TP/TN/FP/FN`, `Jain J=(Σx)²/(nΣx²)`, `TCLink HTB/netem`, `FAST_IO`, `TAP14 setup-only`, `MoQMI`, `fMP4 moof/mdat/mfra`, `MPD SegmentNumber`, `fetch_protos via h3/tcp-fallback`.
