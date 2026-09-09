#!/usr/bin/env python3
"""
LL-DASH client — STREAMING baseline over H2 (TCP) or H3 (QUIC).

Streaming semantics (decisions.md D2/D6/D9): the client behaves like a live
viewer, not a file transfer. It fetches the MPD, then fetches media segments
sequentially via HTTP so the shaped link (tc qdisc) is exercised. A subscriber
that joins late (--join-delay) SKIPS the segments that aired before it joined,
so its output is shorter — exactly like a MoQ late joiner that misses the
first groups. Output length therefore depends on join time.

Value check (not just count): every fetched byte comes via HTTP and a
sidecar manifest (<output>.segments.json) records per-segment SHA256. The
harness verifies each segment byte-for-byte against the origin files in
testdata/ — a 1-byte corruption in any segment fails that segment. No
whole-file SHA vs the source mp4 is used (a late joiner's shorter capture
can never match the full file).

  --origin https://{relay}:{port}  (filled by harness/runner.py _fill_entrypoint)
  --mpd {file}        (e.g. /data/sample_120s.mp4 -> /data/sample_120s.mpd)
  --output {dir}/{stream}.mp4
  --protocol h2|h3    (decided by impl: lldash-h2 vs lldash-h3)
  --join-delay SECS   (0 for early subs; late_sub delay from runner)
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--origin", required=True, help="Origin base URL e.g. https://10.0.0.2:443")
    p.add_argument("--mpd", required=True, help="MPD path e.g. /data/sample_120s.mp4 or /data/sample_120s.mpd")
    p.add_argument("--output", required=True, help="Output file e.g. /output/mystream.mp4")
    p.add_argument("--protocol", default="h2", choices=["h2", "h3", "auto"], help="h2 or h3")
    p.add_argument("--join-delay", default="0", help="Seconds after stream start this sub joined (late joiners skip aired segments)")
    p.add_argument("--name", default="", help="Stream name (unused, for compat)")
    # compat placeholders from harness template (stream, dir, file etc.)
    p.add_argument("--stream", default="")
    p.add_argument("--dir", default="")
    p.add_argument("--file", default="")
    return p.parse_args()


def parse_join_delay(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return max(0.0, float(v))
    s = str(v).strip().lower()
    if s.endswith("s"):
        s = s[:-1]
    try:
        return max(0.0, float(s))
    except ValueError:
        return 0.0


def mpd_name(mpd_arg: str) -> str:
    # /data/sample_120s.mp4 -> sample_120s.mpd ; /data/sample_120s.mpd -> sample_120s.mpd
    base = pathlib.Path(mpd_arg).name
    if base.endswith(".mp4"):
        base = base[:-4] + ".mpd"
    if not base.endswith(".mpd"):
        base = "sample_120s.mpd"
    return base


def log(msg: str, **kwargs):
    # Log to both stdout and stderr so harness finds TTFO in sub.log (stderr) and sub.stdout.log
    # kwargs may include flush=True from legacy call sites
    print(msg, flush=True)
    print(msg, file=sys.stderr, flush=True)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _http_get(url: str, protocol: str, timeout_s: float = 10.0):
    """GET url, trying true QUIC first for h3, then httpx TCP.

    Returns (bytes, proto_label). Raises on failure (no local fallback —
    copying /data would bypass the shaped link and fake throughput).
    """
    if protocol == "h3":
        try:
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False) as tf:
                tmp = tf.name
            r = subprocess.run(
                ["curl", "-sk", "--http3-only", "--connect-timeout", "5",
                 "--max-time", "25", "-o", tmp, "-w", "%{http_code}",
                 url],
                capture_output=True, text=True, timeout=35)
            if r.returncode == 0 and (r.stdout.strip() == "200" or r.stdout.strip().startswith("2")):
                try:
                    data = pathlib.Path(tmp).read_bytes()
                except OSError:
                    data = b""
                if data:
                    try:
                        pathlib.Path(tmp).unlink()
                    except OSError:
                        pass
                    return data, "h3"
                log(f"[lldash-client] QUIC GET empty {url}, falling back to TCP")
            else:
                log(f"[lldash-client] curl --http3-only failed rc={r.returncode} {(r.stderr or r.stdout).strip()[:160]}, falling back to TCP")
            try:
                pathlib.Path(tmp).unlink()
            except OSError:
                pass
        except Exception as e:
            log(f"[lldash-client] QUIC attempt failed ({e}), falling back to TCP")
    import httpx
    is_https = url.startswith("https")
    http2_flag = (protocol == "h2" and is_https)
    timeout = httpx.Timeout(timeout_s, connect=5.0)
    with httpx.Client(http2=http2_flag, verify=False, timeout=timeout, follow_redirects=True) as client:
        r = client.get(url, timeout=timeout)
        r.raise_for_status()
        proto = str(getattr(r, "http_version", "tcp-fallback"))
        return bytes(r.content), proto


def main():
    args = parse_args()
    mpd = mpd_name(args.mpd)
    origin = args.origin.rstrip("/")
    mpd_url = f"{origin}/{mpd}"
    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    join_delay = parse_join_delay(args.join_delay)

    log(f"[lldash-client] streaming protocol={args.protocol} join_delay={join_delay:.1f}s origin={origin} mpd={mpd} output={out_path}")
    start = time.time()
    first_chunk_ts = None

    # --- MPD (control plane; local mount OK, media must be HTTP) ---
    mpd_text = None
    local_mpd = pathlib.Path(args.mpd)
    if local_mpd.suffix == ".mp4":
        local_mpd = local_mpd.with_suffix(".mpd")
    for cand in [local_mpd, pathlib.Path("/data") / mpd]:
        if cand.exists():
            try:
                mpd_text = cand.read_text()
                log(f"[lldash-client] MPD loaded from local {cand} ({len(mpd_text)} B)")
                break
            except Exception as e:
                log(f"[lldash-client] local MPD read failed {cand}: {e}")
    if mpd_text is None:
        try:
            data, proto = _http_get(mpd_url, args.protocol)
            mpd_text = data.decode("utf-8", "replace")
            log(f"[lldash-client] MPD fetched via HTTP {mpd_url} ({len(mpd_text)} B) proto={proto}")
        except Exception as e:
            log(f"[lldash-client] ERROR: MPD not available locally or via HTTP ({e}) — abort")
            out_path.write_bytes(b"")
            sys.exit(0)

    # --- Parse SegmentTemplate: init, ordered segments, segment duration ---
    segment_urls = []
    init_url = None
    seg_dur = 2.0
    try:
        root = ET.fromstring(mpd_text)
        for elem in root.iter():
            tag = elem.tag
            if tag.endswith("SegmentTemplate"):
                init = elem.get("initialization")
                media = elem.get("media")
                try:
                    timescale = float(elem.get("timescale") or 0) or None
                except ValueError:
                    timescale = None
                if init and not init_url:
                    init_url = init.replace("$RepresentationID$", "0")
                if media:
                    timeline = None
                    for child in elem:
                        if child.tag.endswith("SegmentTimeline"):
                            timeline = child
                            break
                    count = 0
                    if timeline is not None:
                        for s in timeline:
                            if s.tag.endswith("S"):
                                try:
                                    d = float(s.get("d") or 0)
                                    if timescale and d > 0:
                                        seg_dur = d / timescale
                                except ValueError:
                                    pass
                                try:
                                    rep = int(s.get("r")) if s.get("r") is not None else 0
                                    count += rep + 1
                                except (ValueError, TypeError):
                                    count += 1
                    if count == 0:
                        count = 60
                    for i in range(1, count + 1):
                        seg = media.replace("$RepresentationID$", "0").replace("$Number%05d$", f"{i:05d}").replace("$Number$", str(i))
                        segment_urls.append(seg)
            if tag.endswith("Initialization"):
                src = elem.get("sourceURL")
                if src and not init_url:
                    init_url = src
            if tag.endswith("SegmentURL"):
                media = elem.get("media")
                if media:
                    segment_urls.append(media)
        if not segment_urls:
            import re
            for m in re.findall(r'media="([^"]+\.m4s)"', mpd_text):
                if "$" in m:
                    continue
                segment_urls.append(m)
            for m in re.findall(r'sourceURL="([^"]+)"', mpd_text):
                if init_url is None:
                    init_url = m
            if not init_url:
                for m in re.findall(r'initialization="([^"]+)"', mpd_text):
                    init_url = m.replace("$RepresentationID$", "0")
                    break
        log(f"[lldash-client] MPD parsed: init={init_url} segments={len(segment_urls)} seg_dur={seg_dur:.2f}s")
    except Exception as e:
        log(f"[lldash-client] MPD parse failed: {e}")

    if not segment_urls:
        log("[lldash-client] WARN: no SegmentURLs in MPD, guessing from sample_120s pattern")
        for i in range(1, 61):
            segment_urls.append(f"chunk-stream0-{i:05d}.m4s")

    # --- Streaming skip: segments that aired before this sub joined ---
    total = len(segment_urls)
    skip = min(int(join_delay // seg_dur) if seg_dur > 0 else 0, total)
    skipped_names = segment_urls[:skip]
    to_fetch = segment_urls[skip:]
    first_name = to_fetch[0] if to_fetch else "-"
    log(f"[lldash-client] streaming skip={skip}/{total} from={first_name} (late joiner misses the start)")

    # --- Fetch init + segments via HTTP ONLY (no local media fallback) ---
    # Host dry-run exception: this dev box has no httpx, so HTTP is impossible.
    # Assemble from local chunk files WITH the same skip logic, flagged clearly
    # as HOST-TEST. Inside containers httpx always exists, so this branch never
    # runs there and can never fake a VM result.
    try:
        import httpx  # noqa: F401
        _have_httpx = True
    except ImportError:
        _have_httpx = False
    out_f = open(out_path, "wb")
    manifest_segs = []
    init_entry = None
    fetched = 0
    proto_counts = {}
    if not _have_httpx:
        log("[lldash-client] HOST-TEST mode (no httpx): assembling from local chunk files with skip logic")
        search_dirs = [pathlib.Path("/data"), pathlib.Path("testdata"), pathlib.Path(args.mpd).parent]
        if init_url:
            for d in search_dirs:
                cand = d / pathlib.Path(init_url).name
                if cand.exists():
                    data = cand.read_bytes()
                    out_f.write(data)
                    fetched += 1
                    proto_counts["host-test"] = proto_counts.get("host-test", 0) + 1
                    if first_chunk_ts is None:
                        first_chunk_ts = time.time()
                    init_entry = {"name": pathlib.Path(init_url).name, "bytes": len(data), "sha256": _sha(data)}
                    log(f"[lldash-client] init local HOST-TEST {cand} {len(data)} B")
                    break
        for idx, seg in enumerate(to_fetch, start=skip + 1):
            for d in search_dirs:
                cand = d / pathlib.Path(seg).name
                if cand.exists():
                    data = cand.read_bytes()
                    out_f.write(data)
                    fetched += 1
                    proto_counts["host-test"] = proto_counts.get("host-test", 0) + 1
                    if first_chunk_ts is None:
                        first_chunk_ts = time.time()
                    manifest_segs.append({"name": pathlib.Path(seg).name, "bytes": len(data), "sha256": _sha(data)})
                    log(f"[lldash-client] segment {idx}/{total} HOST-TEST {cand} {len(data)} B")
                    break
        out_f.close()
    else:
        try:
            if init_url:
                init_fetch_url = f"{origin}/{init_url}" if not init_url.startswith("http") else init_url
                try:
                    data, proto = _http_get(init_fetch_url, args.protocol)
                    out_f.write(data)
                    fetched += 1
                    proto_counts[proto] = proto_counts.get(proto, 0) + 1
                    if first_chunk_ts is None:
                        first_chunk_ts = time.time()
                    init_entry = {"name": pathlib.Path(init_url).name, "bytes": len(data), "sha256": _sha(data)}
                    log(f"[lldash-client] init GET {init_fetch_url} {len(data)} B proto={proto}")
                except Exception as e:
                    log(f"[lldash-client] init fetch failed {init_fetch_url}: {e} (honest partial, no local fallback)")
            for idx, seg in enumerate(to_fetch, start=skip + 1):
                seg_url = f"{origin}/{seg}" if not seg.startswith("http") else seg
                try:
                    data, proto = _http_get(seg_url, args.protocol)
                    out_f.write(data)
                    fetched += 1
                    proto_counts[proto] = proto_counts.get(proto, 0) + 1
                    if first_chunk_ts is None:
                        first_chunk_ts = time.time()
                    manifest_segs.append({"name": pathlib.Path(seg).name, "bytes": len(data), "sha256": _sha(data)})
                    log(f"[lldash-client] segment {idx}/{total} {seg_url} {len(data)} B sha={_sha(data)[:8]} proto={proto}")
                except Exception as e:
                    log(f"[lldash-client] segment failed {seg_url}: {e} (honest partial, no local fallback)")
                time.sleep(0.01)
        finally:
            out_f.close()

    total_bytes = out_path.stat().st_size if out_path.exists() else 0
    elapsed = time.time() - start
    ttfo_ms = int((first_chunk_ts - start) * 1000) if first_chunk_ts else None

    # --- Sidecar manifest for harness per-segment value verification ---
    sidecar = out_path.parent / (out_path.stem + ".segments.json")
    try:
        sidecar.write_text(json.dumps({
            "protocol": args.protocol,
            "join_delay_s": join_delay,
            "segment_duration_s": seg_dur,
            "mpd": mpd,
            "init": init_entry,
            "total_segments": total,
            "skipped": skip,
            "skipped_names": [pathlib.Path(s).name for s in skipped_names],
            "segments": manifest_segs,
            "fetched": len(manifest_segs),
            "fetch_protos": proto_counts,
        }, indent=1))
        log(f"[lldash-client] manifest wrote {sidecar.name} fetched={len(manifest_segs)}/{total} skipped={skip}")
    except Exception as e:
        log(f"[lldash-client] manifest write failed: {e}")

    log(f"[lldash-client] DONE streaming fetched={len(manifest_segs)}/{total} skipped={skip} total_bytes={total_bytes} elapsed={elapsed:.2f}s ttfo_ms={ttfo_ms} protocol={args.protocol} protos={proto_counts}")
    if ttfo_ms is not None:
        log(f"[lldash-client] time_to_first_object_ms: {ttfo_ms}ms")
        log(f"[lldash-client] time_to_first_chunk_ms: {ttfo_ms}ms")


if __name__ == "__main__":
    main()
