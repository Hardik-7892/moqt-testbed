# 04 — Harness Modules: How the Testbed Actually Runs (Ch5 §5.3 + §5.5)

## 4.1 End-to-end flow

`run_testbed.py:1-6 → harness/runner.py:main() (2322-2354)`. CLI `--plan --workers --verify`. `--verify` runs `DraftVerifier.verify_all()` before any network work (`runner.py:2336-2340`).

`TestbedRunner.__init__ (2044-2070)`: `load_testplan()` (`61-63`), `validate_testplan()` (`plan_validation.py:74-144`, fail-fast on unwired/misplaced keys), cache `network_defaults, test_duration=15, media=sample.mp4, require_integrity, integrity_threshold=90.0, data_check, min_objects, require_draft`.

`TestbedRunner.run() (2099-2183)`: reject duplicate run-ids (`2088-2097`, exit 2); reject `--workers>1` (`2107-2111`, parallel threads remain but unreachable — B10 now fails fast); batch dir `artifacts/runs/run_YYYYMMDD_HHMMSS[_N]` + `.latest` (`2072-2086`); per-run `worker()` injects plan defaults (`topology basic`, integrity, data_check, `2119-2135`), constructs `MoQTestRun(...)`, then `run() → evaluate() → result[status/metrics]=evaluation[status/metrics] (2141-2148)` — B5 fix (statuses can no longer disagree); `_save_summary()` → `summary.json + summary.txt` (`2185-2296`), `_print_summary()` console, `ReportGenerator.save_report()` → `report.html + report_legacy.html` (`report.py:552-564`).

`MoQTestRun.__init__ (120-193)`: merge `{**network_defaults, **run.topology}`, `capture` from run→network→plan, `run_id` explicit or `make_run_id(pub/relay/sub+bw/delay/loss) (66-81)`, `run_dir=batch/sanitize(run_id)`, `topology_type`, per-run `test_duration`, layout `pcaps/qlogs/logs/keys/output/certs/coordinator`, optional `MOQ_FAST_IO=1` staging to VM-local disk (`166-177`, B37), `completed/completion_reason/run_duration_s`, `MetricsCollector()` + `TOPOLOGIES[type]()`.

`run() (250-278)`: `setup_dirs() → save_metadata() → _execute_test() → _copy_stage_back()`. `setup_dirs() (195-216)` mkdirs + `coordinator/cache/namespaces/tracks` + `ensure_cert_set(cert_dir, _relay_cert_aliases())`. `save_metadata()` → `metadata.json` (B29 fix). `run()` only sets `error` on exception; pass/fail left to `evaluate()`.

`_execute_test() (679-1171)`: `_cleanup_stale_containers(mn.*)`, `_verify_image_tags()` (B36 Hub-vs-local ID check, `628-677`), `_create_network()` (see Ch03), `net.start()`, link-up + OVS fix + impairment verify + tcpdump, startup order (below), `_wait_for_completion()` with cap, SIGINT subs (`STOP_GRACE_S=3.0`), pkill pub, `STOP_DRAIN_S=12.0` drain (pub-first drain recovers buffered bytes, B37), pkill all, `net.stop()`.

## 4.2 Startup ordering, supervision, completion

Order (`872-1098`): relays sorted +2 s gaps including chain coordinator flags `--coordinator-file/--node/--tls-disable-verify` via `_relay_chain_flags() (516-542)` + downstream `ip route src` fix; publisher(s) (`pub_s{idx}.log`, multi-stream `streams` default 1); `_wait_for_pub_ready(timeout 10, floor 4)` polls relay log for `registering namespace|serving PUBLISH_NAMESPACE`, then for moq-rs gates on first `segment:` (`431-507`, B37: namespace races groups); subscribers with per-role redirect (`951-979`, `_sub_role_cfg 1185-1195`, `_sub_launch_redirect 1344-1359`); `_supervise_sub_joins()` 15 s, `MAX_SUB_RESTARTS=2`, death sigs `Track not found/media error/error subscribing/Closed(16)/Invalid QUIC` + relay `Not found: trac`, log rotation `attemptN.log` (`107-118,544-608`, B38 fix for join race); late joins from `late_joins[]` or `late_sub_count+late_join_delay_s` (`986-1097`, D6).

Fixes stacked here: B19 OVS dead wire, B20 sub-before-pub, B38 surviving race, B39 `--announce`→coordinator file, B7 chain/fanout unrunnable, B10 workers, B21 imquic stdout false-pass (`_LOG_TEXT` + `imquic version/[moq-sub/Bye!`, `1572-1573`).

Completion (`1432-1537`): `_completion_artifact_paths()` mirrors evaluate scoping via `sub_output.file`; `_poll_artifact_completion(poll 1, quiet 3, min_bytes=source×completion_coverage 0.95)` — no-growth counts only if `cur≥min_bytes` (B13rev2/B24; zero-byte never quiesces); `media_bytes()` stripping (B32). `_wait_for_completion()` sets `completed/completion_reason=delivery quiesced|time limit reached|no contract/run_duration_s`. B13 fixed sleep→quiesce; B24 early-quiesce (67.8% + 4 KB pass) fixed by coverage gate + `partial`.

## 4.3 Evaluate ladder (the only pass/fail)

`evaluate() (1670-1939)`: checks `relay_running=all _log_ok(relay*.log)` (`_log_ok` non-empty + no `Usage/Help/Error timed out/FATAL/Invalid QUIC`, `1547-1600`), `pub_started=any _log_ok(pub*.log)`, `sub_received_data`: `object_receipt→count Incoming object: ≥min_objects (1847-1860)` else any `_artifact_has_content()` (media magic `ftyp/FLV/66747970/464c56` definitive, else reject failure/log text, else non-blank, `1639-1668`); `delivered_full=coverage≥completion_coverage×100` or object-count; `sub_started` relaxed for quiet subs; optional `require_draft` from `-- WebTransport (moqt-N)` (`1605-1624`); `stats{delivered_bytes (mlog else artifact), artifact_bytes, original_bytes, coverage_pct, expected_media_bytes, expected_coverage_pct, integrity, per_sub, completed, completion_reason, run_duration_s}`; verdict `!all(checks)→fail; !delivered_full→partial; require_integrity+mismatch→fail; else pass (1895-1908)`; `expect→confusion TP/TN/FP/FN/? (1910-1922)`; metrics via `collect()`.

Replaces B2 files-exist pass. B17 fanout double-count fixed by `groups + verify_groups` (SUM mlogs, worst-tier, never concat; `[full N/M]` replaces N×100%). B18 stdout double-count fixed by `sub_output.file/stdout_is_data`. B26 >100% fixed by mlog authority + `expected_media_bytes` + exact/good/mismatch. B27 report wrong key fixed to `evaluation.metrics`.

## 4.4 Module contracts (one sentence each for Ch5 diagram)

- `runner.py` (~2354 l): input plan+registry+testdata+topology; output per-run dirs + batch summary/report. Owns orchestration, OVS/tc, supervision, completion, evaluate.
- `verify.py` (861 l): mlog parsing (`_json_seq_records`, `_role_from_records` publisher-wins, `parse_mlog_files`, `mlog_subscriber_connections` sum-not-pick), expected model (`expected_objects` init+moof/mdat excl. mfra/free, `expected_media_bytes`), `MLOG_STDOUT_SIG (?:\\x1b\\[[0-9;]*m)+`, `media_bytes()`, `verify_run()` exact/good/mismatch, `verify_groups()` per-sub+aggregate, `verify_lldash_streaming()` per-segment + join skip, `DraftVerifier`.
- `measure.py` (399 l): `MOQRS_SEGMENT_RE \\bsegment:\\s*\\d+:\\d+`, `_count_moqrs_objects` segments+1, `_parse_qlog` JSON-SEQ (seconds vs picoquic µs), `_ttfo_from_mlog`, `_parse_pcap` via `analyze_run_pcaps`, `throughput=delivered×8/duration`.
- `report.py` (797 l): batch `summary.json` → `report.html` (Chart.js: stats, confusion, interop, detailed, per-sub, integrity) + `interop-matrix.csv`. Reads `evaluation.*`. `_transport_label` appends `via h3/tcp-fallback` (D13).
- `probe.py` (471 l): `(draft|None, setup/alpn/tap14/boot/unverified/failed)`; never returns claimed; moq-rs relay+mlog+ALPN, imquic `-M {draft}` + `setup-only` TAP14, moxygen/generic boot-only, lldash boot.
- `certs.py` (121 l): `cryptography` else `openssl`, idempotent, alias copies.
- `pcap.py` (195 l): `tshark_available()`, `analyze_pcap()` JSON + AppArmor retry + `quic.ack.rtt→ms`, `decryption_success=bool(rtt)`.
- `playable.py` (144 l): `copy/strip_ansi/hex_decode`, `reconstruct_from_mlog()` slice-by-length + sort `(group,object)`, best-effort.
- `plan_validation.py` (144 l): `UNWIRED_RUN_KEYS` (aqm/mode/cc/tracks/relays/filters…), `MISPLACED_RUN_KEYS` (devices→network), `WIRED_*`, topology/role cross-checks (chain/fanout mismatches fail fast).
- `quic_alpn.py` (253 l): `MOQ_ALPN_TO_DRAFT`, RFC9000/9001 Initial decrypt + ClientHello parse, `extract_alpn_from_pcap()`.
- `scenarios.py/topology.py`: dead code (B8), commented.
