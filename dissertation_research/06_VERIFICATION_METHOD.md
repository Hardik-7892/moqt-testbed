# 06 — Verification Method: Claimed vs Negotiated (RQ1, Ch6 §6.1)

## 6.1 Why verification is a contribution

Interop papers routinely tabulate claimed drafts. The testbed refuses to: any probe that cannot confirm returns `None`, never the claim (`harness/probe.py:55-56`). Draft-only counts when evidence is `setup/tap14` (`OK/PARTIAL/MISMATCH`); `boot/unverified→UNVERIFIED`; `failed→NOT BUILT` (`harness/verify.py:797-804`). The report shows per-draft evidence. This STRICT discipline (B16 fix) is your RQ1 method.

## 6.2 How each impl is probed (`harness/probe.py:43-76`)

- **moq-rs** (`_probe_moqrs 173-290`): relay + `moq-sub` (unconditionally in image; `moq-test-client` only copied if exists so never relied on), poll relay exit for crash logs, scan mlog via `_parse_mlog_version()` (collect every `selected_version`, prefer SETUP-like, return only if unanimous), plus ALPN extraction from pcap. mlog 16/18 does not log draft; ALPN is only wire evidence (`probe.py:118-120`). Draft-14 mlog logs `selected_version: DRAFT_14` (`135-144`). Handshake confirmation needs `server_setup + parameters` (16/18) or `selected_version/supported_versions` (14) (`109-132`). Relay exit polled so crash surfaces logs, not bare `failed`.
- **imquic** (`_probe_imquic 293-370`): launch relay with `-M {draft}` (claimed, not `any` — `any` would prove nothing per-draft), client `imquic-moq-interop-test --test setup-only`; `ok setup-only → (claimed, tap14)`.
- **moxygen / generic** (`_probe_moxygen/_probe_generic 373-471`): boot-only → `(None, boot)`. Boot proves nothing about negotiated draft.
- **lldash** → boot (not MoQ).
- All return `(draft|None, evidence)`. `DraftVerifier.verify_all()` probes every `(impl,claimed_draft)` after `{draft}` substitution (`verify.py:814-835`); `print_report()` table; `__main__` so `python3 -m harness.verify` works (`858-861`); `make verify` (`Makefile:208-209`); `--verify` flag (`runner.py:2336-2340`). Verified on VM `run_20260825_182826` (B28 fix).

## 6.3 ALPN extraction (`harness/quic_alpn.py`)

`MOQ_ALPN_TO_DRAFT={moq-00:14,moqt-16:16,moqt-18:18}` (`28`). Decrypt QUIC v1 Initials via RFC 9000/9001 keys from DCID, strip header protection, GCM-decrypt, parse ClientHello ALPN (`50-162`, validated RFC vectors + live 14/16/18 captures `11-13`). `extract_alpn_from_pcap()` reads first decryptable Initial to `dport` (`229-253`). `moq-rs` probe uses `moqt://` so client offers draft literal (`probe.py:237-241`).

## 6.4 Current evidence table (cite as Table 6.1)

| Impl | Claimed | Evidence | Reading |
|------|---------|----------|---------|
| moq-rs 14/16/18 | 14,16,18 | UNVERIFIED-honest (mlog lacks draft; ALPN-only since 16) | Do not cite as confirmed; cite as “honestly unverified, ALPN-only” |
| imquic 16/17/18/19 | 16–19 | CONFIRMED via TAP14 (`setup-only`) when pinned `-M {draft}` | Citable, but note `-M any` negotiates `moqt-19`/`moqt-16` regardless of row label — pin matters |
| moxygen 14/16/18 | 14,16,18 | BOOT-only | Do not trust `d18` label; WT CH ALPN `h3`, raw offers `moqt-16/14/moq-00` never `18` (B46); most likely 16 |

`negotiated_drafts null` in `registry.json` for moqtail/moq-dev/quiche-moq/moq-go is the same honesty: unprobed, not failed.

## 6.5 Confusion-matrix controls (I1)

`interop-mismatch.yaml` (moq-rs-only pure protocol): `d14pub-d18relay/d18-d14/d14-d16 fail`, `d16-d18 pass` (ALPN compat at pin). Sep08: 4/4 `fail/mismatch 0 bps` (`interop-mismatch_agg_20260908_133402.csv:2-5`, `phase1 log:4968`). With `expect:fail` these become TN in `_build_confusion_matrix()` (`report.py:227-248`; B41 fixed `evaluation.confusion` read). `REPORT_testbed_status_2026-08-31.md:95` cites `3 TN+1 TP`. Ch6 §6.1 pairs Table 6.1 (verification) with this confusion matrix — method + control in one spread.

## 6.6 What to write (examiner-proof sentences)

- “Draft claims are not results. Only `setup/alpn/tap14` counts as confirmation; `boot` is explicitly UNVERIFIED.”
- “moq-rs draft negotiation is ALPN-only and mlog-silent; we report it as honestly unverified rather than inflating RQ1.”
- “imquic confirmation is conditional on `-M {draft}` pinning; default `any` silently negotiates the highest common and invalidates per-draft rows. Cheapest RQ1 experiment banked as future: paired `-M 18` vs `-M any` rows quoting `-- WebTransport (moqt-N)` per row (file 14 §B3).”
- “moxygen `:18` tags are source-identical to `:16`/`:14` and offer no `moqt-18` on the wire; we retain the vendor claim but grade it BOOT-only.”
