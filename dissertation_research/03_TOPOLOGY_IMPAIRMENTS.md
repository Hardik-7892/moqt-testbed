# 03 — Topology and Impairments: Controlled Networks (Ch5 §5.2 + §5.4)

## 3.1 Why this matters (the gap you close)

Prior interop events run on clean nets. Your claim is controlled networks: per-device impairments on explicit topologies, verified via `tc`, auditable via `tc_{host}.log`. Same wiring for MoQ and LL-DASH (D3), single-wire placement so `delay:10ms` means 10 ms, not 20 ms (D4/B12), bottleneck placement honest (D12).

`topology.yaml:5-25` (`pub1→relay1→sub1` clean) and `ScenarioApplier/TopologyBuilder` (`harness/scenarios.py`, `harness/topology.py`) are dead code (B8, imports commented `harness/runner.py:36-42`). The live system is `topologies/` descriptors + `harness/runner.py:_create_network`. Say so in Ch5 — examiners reward honesty about dead config.

## 3.2 Descriptor contract (`topologies/base.py:1-90`)

Plain descriptors, not Mininet `Topo`. `CLEAN_LINK={bw:1000,delay:1ms,loss:0}` (`base.py:18`).

- `roles(network)` — hosts to create; `config_key(role)` — registry lookup; `switch_ids()` — OVS bridges; `links()->(a,b,param_role)` where `__clean__` always clean, `__inter_relay__` chain measurement link (`base.py:38-45`).
- `default_impaired_roles()->{sub}` (`base.py:47-52`); `link_params_for_role()` devices-merge (`base.py:54-74`): if `network.devices` present, listed role gets `{**top_level, **devices[role]}`; unlisted gets `CLEAN`. If absent, only default-impaired (subscriber wires) get top-level; pub/relay clean.
- `client_roles()` gets `max_queue_size` (`base.py:76-78`); `relay_port_binding()` (`base.py:80-82`). Registered in `topologies/__init__.py:7-12`.

## 3.3 Four topologies (explain basic, delta the rest)

**basic** (`basic.py:11-25`): `roles=[pub,relay,sub]`, `switches=[s1]`, `links=[(pub,s1,pub),(relay,s1,relay),(sub,s1,sub)]`. No late_sub, no inter-relay. Ch5 explains this end-to-end; chain/fanout by delta.

**chain** (`chain.py:14-96`): `roles=[pub,relay_a,relay_b,sub]+late_sub*` (`late_sub_count|late_joins`); `switches=[s1,s2]`; `links=[(pub,s1,pub),(relay_a,s1,__clean__),(relay_a,s2,__inter_relay__),(relay_b,s2,relay_b),(sub,s2,sub)]`; `extra_links=[(late_subi,s2,late_subi)]`; `default_impaired={sub}+late_sub*`; `__inter_relay__→inter_relay_link_params()` (`chain.py:72-88`): `devices.relay_a ? merged : CLEAN+relay_delay default 20ms`; `relay_b port=base+1` (`chain.py:93-96`). Models origin→edge cache hierarchy; `relay_delay` is cache-miss fill over `s2`.

**fanout** (`fanout.py:14-70`): `roles=[pub,relay,sub1..N]+late_sub*`, default `N=4`; `switches=[s1]`; `links=[(pub,s1,pub),(relay,s1,relay)]`; `fanout_sub_links=[(subi,s1,subi)+(late_subi,s1,late_subi)]`; `default_impaired={subi}+late_sub*`. `config_key sub{i}→sub{i}` allows mixed-impl override (runner falls back to `sub`); `late_sub→sub`. Per-sub impaired; `N=3` in most plans; `late_sub*` for late-join (D6).

**chainfanout** (`chainfanout.py:17-117`): `roles=[pub,relay_a,relay_b,sub1..N]+late_sub*`, default `N=3`; `switches=[s1,s2]`; fanout off downstream `s2`; same inter-relay contract; `extra_links` only when `late_sub_count` unset to avoid duplicate.

Validation enforces wiring: `relay_a/b⇒chain/chainfanout`, `num_subscribers/sub{i}⇒fanout/chainfanout` (`harness/plan_validation.py:123-143`). Every nominal sweep row carries explicit per-run `topology: chain/fanout` because the runner resolves topology purely from `run['topology']` (plan default when absent, `harness/runner.py:138,194`) — without it a “chain” row silently runs as `basic` (found during Phase 2; pre-fix sweeps never built a chain).

## 3.4 Impairment model: per-device, single-wire, verified

Profiles (`scenarios.yaml:4-57`): `clean (100/10ms/0)`, `low_latency (5ms)`, `high_latency (100ms)`, `lossy_1/5/10pct (20ms)`, `bw_limited_5/2mbps`, `constrained (50/50ms/0.5)`. Each with `bw/delay/loss/max_queue_size`.

Application (`harness/runner.py:1202-1321`): one Docker host per `roles()` with `sleep infinity`, mounts `/keys/logs/pcaps/qlogs/output/certs/data` + `MOQ_ROLE,RUST_LOG,SSLKEYLOGFILE` (`runner.py:1232-1239`); lldash data mounts + shared `/moq-coordinator` for chain + per-sub `output/<role>` for fanout; `port_bindings` via `relay_port_binding()`; switches + links with `link_params_for_role()+max_queue_size` on client roles only. `net.start()`, bring every `*eth*` up, assign `10.250.x.10` to inter-relay wire, `_fix_ovs_switching()` (`fail_mode=standalone` + `priority=0,actions=normal`, `runner.py:410-429`, B19 fix for OVS `secure` + DOWN veth dead wire), `_verify_impairments()` (`runner.py:344-388`: `tc qdisc/class show` per host, persist `logs/tc_{host}.log`, require `htb|tbf|netem` on impaired hosts only; raise on missing `iproute2` or no shaping), optional tcpdump (`-i {host}-eth0 -U -w /pcaps/{host}.pcap`, availability probe + 1.5 s liveness, `runner.py:227-248,772-785`; opt-in `capture:true` because pcaps are large; all built images ship tcpdump, B3 fix).

Single-wire rule (B12 fix): without `devices`, only subscriber wires impaired (fanout: every `sub{i}`), never both pub+sub. Historical double-placement gave `10ms→~20ms` and `1%→1.99%` (`found-bugs.md:286-302`). `_is_impaired()` is exact CLEAN comparison (`runner.py:325-329`); `_impaired_host_names()` includes `relay_a` when inter-relay impaired (B33 fix, `runner.py:331-342`).

D12 honesty (Phase 2): chain sweeps constrain inter-relay via `devices.relay_a` (sub stays CLEAN); `relay_delay` omitted where `devices.relay_a` present (inert). Fanout `devices.sub{i}` = independent last-mile shapers, not shared bottleneck (top-level `bw` ignored when `devices` lists subs; relay stays `1000M/1ms`, `base.py:68-71`). Shared-bottleneck approximation is `devices.relay` (shapes `relay→s1`, `fanout.py:35`, traversed by all subs) in `fairness-3sub-shared-egress-10m/5m`. True single-queue CBQ needs OVS QoS — future work. `max_queue_size` applies to pub/sub only (`runner.py:1277`), so queue-sweep chain rows measure end-to-end bufferbloat, not inter-relay queue.

Sweeps reuse same values: latency 5→200 ms, bandwidth 1→100 Mbps, loss 0→20%, queue 10→1000 (bufferbloat I16: `queue:1000` at `bw:5` ≈2 s standing queue).

Ch5 table: profiles × topologies × per-device placement + `tc_*.log` audit trail. That is your “controlled networks implemented” evidence.
