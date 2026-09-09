# 07 — Interop Results, Phase 1 (RQ2, Ch6 §6.2)

All numbers Sep08 batches `20260908_133402` (`n=1` except quick `n=3`). Status ladder `runner.py:1895-1908`: checks-fail→`fail`; coverage<95%→`partial`; full+`mismatch`+`require_integrity`→`fail`; else `pass`. Verdicts `verify.py:288-366`: `exact`=SHA; `good`=mlog==expected AND prefix≥90%; else `mismatch`. `aggregate.py:118-158`: cite `artifact_thr_*` for fanout/restarts; WARN on mlog/artifact>2×.

## 7.1 Quick smoke (only n=3, citable)

`phase1 log:1187,2383,3579`: 8 total | 3 pass | 0 partial | 5 fail ×3 identical.

`interop-quick_agg_20260908_133402.csv:2-9`:

- `moqrs-d18-baseline: pass×3 / mismatch×3, throughput 287288, rtt 11.68 ms, delfrac 5.10, artifact_thr 55712` — pass means full coverage, not verified (mismatch, `require_integrity` off).
- `moqrs-loss1pct/loss5pct`: identical pass/mismatch 287288 — loss 1/5% does not move tiny `sample_1seg` media.
- `imquic-relay-d18-baseline: fail×3 0 bps`; `imquic-sub-d18-baseline: fail×3 734 bps rtt 25.27 delfrac 0.012`; `moqrs-pub-imquic-relay-imquic-sub: fail×3 591 bps`; `moxygen-relay: fail×3 0 bps`; `moxygen-relay-imquic-sub: fail×3 442 bps`.

Write: “Same-impl moq-rs d18 is the only passing MoQ path; every cross-impl cell fails even at 0% loss. Pass here means delivered-full, not byte-verified — all eight rows are `mismatch`.”

## 7.2 Same-impl depth

`moqrs-self_agg:4-6`: `moqrs-self-d18 pass/good 55743 rtt 62.63 delfrac 0.996 artifact 55343`; loss1/5 pass/good; `d14/d16 partial/mismatch 6089/6113 delfrac 0.106`. Draft matters even same-impl; only d18 verifiable.

`interop-built_agg:2-9` (n=1): `moqrs-baseline pass/mismatch 287288`; `moxygen-baseline partial/mismatch 993002 rtt_n 0` (FLV stdout bytes, not MoQ win); `moxygen-pub-imquic-relay-moqrs-sub fail 0`.

`interop-full_agg:2-19` (18 rows: 5 pass 2 partial 11 fail): passes all moq-rs d18 (`baseline + bw5/delay100/loss1/loss5` ~287k); partials `d14/d16 6134/6138 delfrac 0.106`; all `imquic-relay/sub d16/d18 fail 0–587`, all `moxygen-relay d14/d16/d18 fail 0`.

## 7.3 Cross-impl matrix (the headline failure)

`cross-impl_agg:2-29` (28 rows: 3 pass 3 partial 22 fail): only `moqrs-d18-baseline/loss1/loss5 pass`; `moqrs-d14/d16 + moxygen-baseline partial`; every `moqrs-pub-moxygen-relay-*, moxygen-pub-*, moxygen-relay-*, imquic-relay/sub-loss1` fail.

Root causes B43–B45: imquic negotiates `moqt-16` regardless and capsule framing mutually unparsable (`InvalidMessage(33)` vs `No WebTransport protocol`); moxygen needs `client_path /moq` but sub never completes SETUP; B44 pub-log name stranded fast pubs; B45 11-object `sample.mp4` broke archive catch-up (`{init,group9}` only) — mitigated by `sample_1seg.mp4` for moq-rs cells. B5 fixed (statuses sync); remaining `pass/mismatch` by design when integrity off.

Ch6 Table 6.2: tuple matrix (pub/relay/sub) with `pass/partial/fail` + `verdict` + `expect→confusion`. Flag cross-impl partials 0–16% explicitly. Failure taxonomy: (1) ALPN/draft mismatch, (2) WT path/endpoint, (3) FLV vs fMP4 framing, (4) join race (B38), (5) archive/no-backfill.

## 7.4 Controls

`interop-mismatch_agg:2-5`: 4/4 `fail/mismatch 0 bps`. With `expect:fail` → TN (`report.py:227-248`, B41). Cite `3 TN+1 TP` pattern as I1 evidence. `ttfo_n_null==n` everywhere — no TTFO claim.

Cross-phase scale warning: quick 287k vs loss-sweep 14M vs moq-vs-lldash 3k are media/cap artefacts (`sample_1seg` ~20 KB quiesced 3 s vs `107 KB` vs `sample_120s`), not impl rankings. Always state media + `completion_reason` (`delivery quiesced` vs `time limit`, `runner.py:1487-1534`): moq-rs baseline `quiesced 3.03 s 20892/107457`, imquic/moxygen `time limit 15 s 0–1277` (`phase1_122434.log:97,245,394…`).
