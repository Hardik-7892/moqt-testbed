# 11 — Large-File BBB as Future Work, Phase 5 (Ch8/Ch9, not Ch6 results)

No `bbb*agg.csv` in Sep08 reports. `bbb.yaml:1-28` defines the deferred measurement: 121 MB real media, `basic capture:true` (~150 MB/host, GBs/batch), 30 s, 7 rows (moqrs-clean/loss1/bw10 + imquic-relay/sub variants, local tags). `bbb-smoke.yaml` (180 s capture), `bbb-smoke-nocap.yaml` (`capture:false` A/B), `bbb-smoke-video.yaml` (single-track 300 s, comparable+playable), `diag-bbb.yaml` (H1/H2 for B25, `devices.pub/sub` throttling), `capture-smoke.yaml` (B3/B11). `phase5_largefile.sh` runs `test-bbb-smoke/imquic-self/moxygen-self` with `FAST_IO=1`.

## 11.1 Why excluded (B22/B25)

B22: Blender `ftypM4V` non-fragmented crashes `moq-pub` (`hdlr size too small`, catalog ~371 B then quiesce, `run_20260818_141942`); fix remux `empty_moov+frag_keyframe+separate_moof` (plain `-c copy` gives `missing moof`); verified 82 MB/121 MB 67.8% (`run_20260818_145813`).

B25: relay at `a6ed4e9` cannot sustain 121 MB — deterministic slow-sub starvation (pub ~4 MB/s, impaired downlink slower, per-track buffer fills, sub gets ~4 KB init, zero errors) + intermittent `track_alias not found ×1055 → STOP_SENDING` race on clean. Re-pin `a6ed4e9→2d16c9c8` restores sample to `99.15% good` but 120 s still stalls ~15 KB partial/40 s, `sample.mp4` ~11 KB/sub; hence fairness + headline MoQ rows honestly `expect:partial`. Old-pin A/B still queued. `REPORT 2026-08-31:124-128` (`bbb 42% pin ceiling, pcaps header-only`).

Ch8 sentence: “BBB was built, remuxed, and driven to 67.8% once (timing fluke); deterministically it stalls at init-only on impaired links and is therefore scoped as future work pending relay fix + video-only remux + reconstruction validation.”

## 11.2 FAST_IO, B37, B38 (must-cite caveats even for sample runs)

FAST_IO: every head shows `staging active → /tmp/moq-stage/<run>` (`phase1_122434.log:5` etc.). `MOQ_FAST_IO=1` stages sub output/qlogs/pcaps VM-local then copies back pre-evaluate (B37 add.4–5; early `sudo -E` unstaged, fixed to `sudo VAR=val` + loud line). Paired verdict NEUTRAL — staged 98 MB mlog 87.95% ~2.6 Mbps inside unstaged 2–4 Mbps band; shared folder exonerated; keep as insurance for pcaps. Without the line a run is unstaged.

B37 (multi-track): relay delivers (mlog init exact + MBs) but serves each track over multiple concurrent subgroup streams; arrival-order capture interleaves, neither byte-compares nor plays (`data_offset` invalidated); single-track escapes only as single tiny object. Shipped: `fetch-bbb-video.sh` video-only, `reconstruct_from_mlog` (slice-by-length + sort `(group,object)`, 79.9 MB rebuild), `_wait_for_pub_ready` first-`segment:` gate, `STOP_DRAIN_S` pub-first drain. Standing: group-skipping (silent drop-to-latest, e.g. 132/194 at 1.08 Mbps, WG-reportable), throughput decay 31→4.3→2.2→1.08 Mbps across pins/env, teardown flush 88%→1.4%, pcaps header-only (935–2329 B despite 15k packets) with capture throttling (~0.77 vs ~31 Mbps) — control `bbb-smoke-nocap.yaml`.

B38 (join race): namespace registered but track lags ~1.5 s; sub SUBSCRIBEs once, dies `Track not found`, never retries; relay STOP_SENDINGs pub. Fix `_supervise_sub_joins` (death sigs + `Not found: trac`, `MAX 2`, `attemptN.log`). Silent variant (no sig, groups 1–4 skipped) remains — only relay log reveals it. Consequence: any `fail 0 bps time-limit` could hide 1.5 s race; any fanout mlog throughput must be checked vs `artifact_thr_*`.

B24 fixed (coverage-gated quiesce + `partial`; 4 KB pass impossible).
