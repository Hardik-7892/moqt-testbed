# 12 — Threats, Summary, and Ch5/Ch6 Writing Map (PhD-hardened post-Phase-4)

## 12.1 Threats to validity (Ch6 §6.5 + Ch8) — each with fix

- **Repeats:** matrix `quick n=3 citable | headline n=3 citable | sweeps/topologies/single-baselines n=1 non-citable (p50==p95, jain_n 0, no variance)`. `aggregate.py:39-52,55-64,102-103,169-170`; freeze: no Ch6 number without n/throughput_n/rtt_n/artifact_thr_n + WARN disposition. n=1 stays in appendix.
- **Wire:** counts only. `pcap.py:140-146` decrypt False (tshark 4.6.4 no `quic.ack.rtt`); `measure.py:392-398` qlog canonical; header-only 86B; throttling control `bbb-smoke-nocap`. H2-vs-H3 uses completion + `fetch_protos`, never RTT.
- **Throughput denominator:** `measure.py:69-72` delivered×8/duration where duration is quiesced (MoQ bulk-push) vs time-limit (DASH paced `skip=floor(join/seg_dur)`). Every cell shows `media + completion_reason + denominator + integrity gate` (D13). `0.95/90/3s` (`runner.py:1518,1523,1865`, `verify.py:287`) unvalidated — future sensitivity sweep `{0.90,0.95,0.99}×{2,3,5}s` reporting status-flip rate.
- **Verdict vs status:** `pass/mismatch` dominates pre-headline; headline with `require_integrity:true` (`moq-vs-lldash.yaml:20`) maps full+mismatch→`fail` (D14). New headline MoQ `fail-or-flaky-pass/mismatch-or-good` (not `partial` TP) — `expect:partial` stale, maps to `?/FN` (`runner.py:1911-1922`). Fanout cite `artifact_thr + per-sub + verdict`, never mlog `throughput_p50` (6×/12× B38 inflation, `aggregate.py:112-137` WARN >2×).
- **Drafts:** moq-rs UNVERIFIED-honest (mlog-silent ALPN-only) / imquic CONFIRMED-conditional on `-M {draft}` (`any`→`moqt-19/16` regardless; relay unpinned or rejects moq-rs 271) / moxygen BOOT-only (WT CH `h3`, raw offers `moqt-16/14/moq-00` never 18, B46; `:14/:16/:18` identical bits `Makefile:126-131`). Row labels claims; tag≠wire. Disabled nulls non-claims (B15).
- **Media dependence:** `sample_1seg` ~20 KB quiesced 3 s vs `sample.mp4` 107 KB vs `sample_120s` (OLD MoQ partial 0.017 vs H2/H3 exact — SUPERSEDED; NEW MoQ 0.998 fail-or-good vs H2/H3 exact, integrity deficit replaces coverage gap) vs BBB 121 MB smoke-only (`run_20260908_183715` in-flight, not results). Cross-phase throughput not rankable. Always state media + `completion_reason`.
- **Env + hacks disclosed:** single Ubuntu VM shared folder, sequential `--workers 1` (fails fast `runner.py:2107-2111`, B10), OVS `tc` warnings every head, tag-skew history (B36 + re-tag `phase4_baselines.sh:34-37`), chainfanout 0/5, cross expected-fail. Sleeps `runner.py:93,105,467,505,568,601,773,931,1041,1069,1098,1128,1146,1149,1168,1465,1495` + `probe.py`; sudo `Makefile:101,106-200,276-308`; paths `runner.py:20-34` + `pcap.py:52-55`. Testbed-relative, not Internet-generalisable. Time-decay 31→4.3→1.08 Mbps confounded (sequential hours).

## 12.2 Chain status + summary numbers (for abstract/Ch9)

- Verification: moq-rs UNVERIFIED-honest / imquic CONFIRMED (TAP14, pinned) / moxygen BOOT-only.
- Interop: quick 3/8 pass (all moq-rs d18, all mismatch); full 5/18 pass + 2 partial + 11 fail; cross 3/28 pass + 3 partial + 22 fail; mismatch 0/4 fail (4 TN controls).
- Sweeps: moq-rs survives 0–20% loss bulk (13–29 Mbps) + 5–200 ms flat + 1–100 Mbps flat (small media) + queue 10–1000 flat (null bufferbloat curve, BDP-annotated); fanout degrades first; imquic receipt 2.5–2.7k object units; moxygen fails throughout (FLV path).
- Topologies: fanout moqrs 4/4 pass (mismatch), imquic 1/1 + Jain 1.0, mixed fail (78× diverge), moxygen 0/2; fairness 6/6 liveness, Jain 0/6 (no citable fairness); chain 2/6 (moqrs-moqrs + loss1 `good`), chainfanout 0/5. Chain = exploratory, coordinator-gated.
- Baselines (COMPLETED n=3): H2/H3 `exact` (0.87–4.1 Mbps, fanout 3.009× Jain 1.0/1.0/3, late-join `good`); headline MoQ OLD 200–300× below SUPERSEDED — NEW MoQ 2.2–2.35 Mbps delfrac 0.998 (2–3× ABOVE H2/H3 on throughput/coverage) but 4/6 `fail/mismatch` integrity deficit (only loss1×3 + clean-r2 `good`); 10 s `pass/good`; fanout WARNs, `jain_n=1` no citable MoQ Jain. `expect:partial` stale.
- BBB: smoke running (`phase5_183713`, `run_20260908_183715`), future work (B22 remuxed, B25 superseded for 120 s but BBB open, B37/B38 caveats, FAST_IO neutral, capture throttling control).

## 12.3 Ch5 writing map (2–3 pp.)

- §5.1 Registry: schema + pins + `cert_aliases` + B9 alignment + B36 skew guard. Fig: registry schema.
- §5.2 Topologies: basic end-to-end; chain/fanout by delta; late_sub; `topology: chain/fanout` per-run requirement. Fig: class/wiring delta.
- §5.3 Harness: flow diagram + one-sentence modules + startup/supervision/completion/ladder. Fig: module flow.
- §5.4 Plans/media: profiles table + plan taxonomy + 2 s GOP fMP4 + FLV/MPD derivatives + D2–D14 fairness. Table: profiles.
- §5.5 Bug stories (grade-bearing): B35 silent fallback (if in scope) / B36 tag skew / B37 4 addenda (permutation→reconstructor, join gate, pub-first drain, FAST_IO) / B38 supervision / B19 OVS dead wire / B20 order / B24 coverage gate + `partial` / B26 mlog authority. Each: symptom → evidence (`run_*`, `*.log`) → fix (`file:line`) → verification run.
- §5.6 Limits: chain 0/9→2/11, cross partials 0–16%, pcap header-only, stdout tail, disabled nulls, n=1 sweeps.

Every decision needs “because” + `found-bugs.md` ID + `decisions.md` D#.

## 12.4 Ch6 writing map (4–5 pp.)

- §6.1 Verification (RQ1): Table 6.1 evidence + confusion matrix (3 TN+1 TP) + STRICT vocabulary. One para per impl + “tag ≠ wire”.
- §6.2 Interop (RQ2): Table 6.2 tuple matrix + failure taxonomy (ALPN/WT/FLV/race/archive) + B43–B45 + media/completion caveat.
- §6.3 Performance (RQ3–RQ5) 5-experiment freeze (all n=3, p50/p95 plots): E1 verification + TN, E2 quick 8-row matrix, E3 loss/latency basic-only, E4 fanout per-sub + late-join (`artifact_thr`, Jain iff ≥2 positives), E5 headline triple + D13 bounds + D14 status-vs-verdict split. Sweeps n=1 → appendix. Each Hypothesis→Why→Result→Explanation. Old 7-fig plan (6.1–6.7 incl. FAST_IO/group-skipping) collapses to 5; FAST_IO neutral + group-skipping WG gap → Ch8.
- §6.4 Chain status: 2/11 + coordinator hypothesis + `tc_relay_a.log`; scope as future work.
- §6.5 Threats + summary: n=1/TTFO/RTT/denominator/verdict/draft/media/env (above) → link to Ch8.

Cross-cutting: IEEE sequential citations (~20: draft-ietf-moq-transport frozen, QUIC RFC 9000/9001, WebTransport/HTTP/3, DASH/CMAF, Mininet/Containernet, OVS, tc/netem/HTB, tshark, qlog, nginx/caddy, httpx/aioquic, MP4Box/ffmpeg + Gurel/Nguyen/Kuo); every Ch4–Ch6 claim has figure/table/evidence ref; hypothesis frame per experiment; Ch8 WG gaps (permutation, group-skipping, join no-retry, flush loss, cross partials); Ch9 one-sentence RQ answers (RQs rescoped DASH-only single-relay+last-mile; chain/WebRTC/BBB future); AI declaration plain (language + log synthesis only, no AI measurements/figures/refs, author-checked, author-responsible); ≤30 pp. excl. appendices.
