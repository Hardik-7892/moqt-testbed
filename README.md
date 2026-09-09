# MoQ Testbed: Reproducible Media over QUIC Experiments

A reproducible testbed for **Media over QUIC Transport (MoQT)**. It runs
publishers, relays and subscribers from independent implementations on a
planned Containernet network with set loss, delay and bandwidth, then scores
every viewer on byte value with auditable pass, partial and fail verdicts.

The testbed answers two questions that interop events leave open: what draft
did each build really agree on (not just claim), and how does delivery hold
when the network turns bad.

Builds under test: **moq-rs** (Cloudflare, Rust), **imquic** (Meetecho, C on
picoquic) and **moxygen** (Meta, C++), plus **LL-DASH over H2 and H3** as
baselines on the same source. All pins live in `registry.json`.

## Headline Results

From the citable headline campaign (`reports/moq-vs-lldash_agg_20260908_172709.csv`,
16 rows at 3 repeats, 120 second film, 2 second groups):

| Comparison | Result |
|---|---|
| H3 vs H2 (clean) | H3 ~37% above H2: transport gain from QUIC |
| MoQ vs H3 (clean) | MoQ ~1.95x H3: app gain from push vs paced fetch |
| MoQ vs H2 (clean) | MoQ ~2.67x H3-side baseline |
| MoQ loss 1% | Full cover with byte proof 3 of 3, best MoQ row |
| MoQ clean | Full cover, byte proof 1 of 3 (tail flake, not a wall) |

Caveats, stated with the numbers: MoQ pushes until quiet (~3 s) while DASH
fetches paced to the time limit (40 s), so speeds use different clocks. First
object and wire times stay null throughout (clocks and decrypt do not allow
them). Sweep and topology rows are single-run appendix data until repeated.

## Features

- **Pinned builds.** Every image is fixed by commit hash in `registry.json`,
  never by floating tag. Re-tag scripts guard against Hub drift.
- **Draft verification.** A probe checks claimed vs agreed draft before any
  network starts. ALPN word on the wire or setup-only pass counts as
  CONFIRMED. Boot-only stays UNVERIFIED and never counts as a result.
  (`make verify`)
- **Planned networks.** Basic, chain, fanout and chainfanout topologies drawn
  in code. Per-link shaping with kernel receipts (`tc_{host}.log`) on every
  run. Named overrides move weather onto one wire; anything unwired fails
  fast instead of running clean silently.
- **Byte-value verdicts.** Hash plus prefix match, not byte count. Full and
  exact is a pass, full but wrong bytes fails when integrity is on, short but
  correct is partial. Worst viewer sets the run verdict. Fanout cites saved
  files only, never relay counters (restarts inflate them 2x-4x).
- **Same-source baselines.** MoQ and both DASH baselines play the same film
  with the same 2 second quantum, so content never explains the gap. H2 vs
  H3 splits transport effects; MoQ vs H3 splits app effects.
- **One-command campaigns.** Phase scripts run full matrices with repeats
  and merge them into aggregate CSVs with percentiles and fairness index.

## Repository Layout

```
registry.json          Pins, images, start commands, ports (single source)
run_testbed.py         Entry point: --plan, --workers, --verify
Makefile               Build, test, verify, report targets
harness/               Runner, draft probe, verifier, report builder
topologies/            basic, chain, fanout, chainfanout network files
docker/                Builds: cloudflare-moq-rs, moxygen, imquic, lldash
testplans/             Short YAML files, one per test (future/ quarantined)
analysis/              Merge repeats into CSV tables (aggregate.py)
evaluation_tests/      Phase scripts: phase1_interop … phase6_missed
scripts/               Media fetch, test data generation, VM setup notes
tests/                 Docker-free unit tests (validation, wiring, aggregate)
testdata/              README only in git; media built or fetched locally
features/              Draft capability maps (draft-18, draft-19)
examples/              Small real runs: headline, fanout, chain, interop, capture
reports/               Citable aggregate CSVs
dissertation_research/ Notes behind the thesis chapters
decisions.md           Design contract D1-D14
IMPLEMENTATION_REGISTRY.md  Human view of the registry
```

## Prerequisites

Tested on an Ubuntu 24.04 VM (75 GB disk; image builds peak around 30 to
50 GB, so leave headroom). Full steps live in `scripts/setup-vm.md`.

| Need | Version used | Install |
|---|---|---|
| Docker Engine + Compose | 29.x / 2.40.x | `sudo apt install -y docker.io docker-compose-v2`, then `sudo usermod -aG docker $USER` and log back in |
| Containernet (Mininet fork with Docker support) | source build | `git clone https://github.com/containernet/containernet.git`, then `sudo make install` inside it. Do not install Mininet from pip. |
| Open vSwitch + tc | via Containernet deps | `sudo apt install -y openvswitch-switch iproute2 net-tools` |
| Python 3 + pip | 3.12 or newer | `pip3 install -r requirements.txt` (add `--break-system-packages` on Ubuntu 24.04) |
| Go toolchain | 1.22 or newer | `sudo apt install -y golang-go` (only needed for some builds) |
| tshark (optional) | 4.x | Only for pcap checks. Without it, captures still save and qlogs stay canonical. |

Verify before building:

```bash
docker --version
python3 -c "from mininet.net import Containernet; print('Containernet OK')"
pip3 install -r requirements.txt
```

Note: Docker build cache lives outside this repo and can grow to GBs
with the moxygen source build. Never commit `.tar` exports. The moxygen
client takes the longest (source build with patches); layer caching makes
rebuilds fast, so keep the Docker cache between builds.

## Quick Start

Build the images you need:

```bash
make build-moq-rs
make build-moxygen
make build-imquic
make build-lldash-h2
make build-lldash-h3
```

Make test media locally (never committed):

```bash
bash scripts/generate-test-data.sh
bash scripts/fetch-bbb.sh        # Big Buck Bunny, CC-BY Blender Foundation
bash scripts/fetch-flv.sh        # FLV copies for moxygen
```

## Running Tests

One plan, one worker. Workers stay at 1 so runs go one by one and never
fight over ports.

```bash
# Smoke check: 8 triples, 3 repeats, citable
python3 run_testbed.py --plan testplans/interop-quick.yaml --workers 1

# Same, with draft check first
python3 run_testbed.py --plan testplans/interop-quick.yaml --workers 1 --verify

# Headline triple: MoQ vs H2 vs H3 (via phase script, 3 repeats)
REPEATS_HEADLINE=3 ./evaluation_tests/phase4_baselines.sh
```

Draft check alone, before any network:

```bash
make verify
python3 -m harness.verify
```

`CONFIRMED` needs the ALPN word on the wire or a passed setup-only test.
`BOOT` means the box started and proves nothing. imquic needs pinning with
`-M` (default `any` silently agrees the highest common draft). moxygen tags
`:14/:16/:18` hold identical bits, so its draft label stays BOOT-only.

## Reproducibility Notes

- **FAST_IO staging.** Shared folders are slow for captures, so
  `MOQ_FAST_IO=1` stages output, qlogs and pcaps on local disk during the
  run and copies them back before scoring. Without it the run is unstaged.
  In the Makefile this is the `FAST_IO` knob:

  ```bash
  MOQ_FAST_IO=1 python3 run_testbed.py --plan testplans/bbb-smoke.yaml --workers 1
  ```

- **Merging repeats.** The aggregate script takes batch folders and writes
  one CSV. `--min-repeats 3` keeps only rows with three repeats.
  Single-run pilots use `--min-repeats 1` and stay appendix-only:

  ```bash
  python3 analysis/aggregate.py artifacts/runs/run_A artifacts/runs/run_B \
    --out artifacts/reports/out.csv --min-repeats 3
  make report
  ```

- **Shaping receipts.** Every run keeps `logs/tc_{host}.log` (kernel
  queue rules), `qlogs/*.mlog` (relay object log), output files (final
  bytes) and, for DASH rows, `segments.json` with per-segment `via h3`
  tags. Default shapes only viewer wires; `network.devices` moves weather
  onto a named wire (e.g. `devices.relay_a` for the middle chain wire).

- **Known limits.** Chain needs a shared coordinator file; cross-build
  chain fails by design. Captures hold headers only (decrypt off), so wire
  timing stays null and qlog time is canonical. moq-rs needs fragmented
  MP4; moxygen speaks FLV only with approximate byte compare.

## Examples

Each folder is one real run with logs, qlogs, shaping receipts, output
files and metadata:

- `examples/headline/` — moq-clean, moq-loss1, h3-clean from the citable
  triple (1 MB each). moq-loss1 shows `netem loss 1%` in `tc_sub.log`;
  h3-clean shows 60/60 segments over H3 with zero fallback.
- `examples/fanout/` — one publisher to three viewers, per-viewer files
  with worst-sets-verdict.
- `examples/chain/` — relay-to-relay middle wire with coordinator fix.
- `examples/interop/` — passing moq-rs triple plus failing imquic-sub
  triple from the smoke matrix.
- `examples/capture/` — run with real pcaps alongside mlogs.

## Evaluation Campaigns

| Phase | Script | What it proves |
|---|---|---|
| 1 Interop | `phase1_interop.sh` | Tuple matrix + mismatch controls (true negatives) |
| 2 Sweeps | `phase2_sweeps.sh` | Loss, delay, bandwidth, queue grids (appendix until n=3) |
| 3 Topologies | `phase3_topologies.sh` | Fanout, fairness, chain status |
| 4 Baselines | `phase4_baselines.sh` | Headline MoQ vs H2 vs H3 triple at 3 repeats |
| 5 Large file | `phase5_largefile.sh` | BBB pilot, scoped as future work |
| 6 Missed | `phase6_missed.sh` | Loss knee, late join, datagram pilots |

## Citation

If you use this testbed, please cite the dissertation and the MoQ
Transport draft:

```bibtex
@misc{my_testbed,
  author = {Hardik Hemant Pandey},
  title  = {Reproducible Media-over-QUIC Testbed},
  year   = {2026},
}
```

## Media Credit

`bbb.mp4` is *Big Buck Bunny* (c) Blender Foundation, CC-BY. Fetched by
script, never committed.

## License

MIT. See `LICENSE`.
