#!/usr/bin/env python3
"""Build-compat patches for the getdeps-fetched proxygen checkout.

Applied by Dockerfile.media step [1.5] before the moxygen build. Idempotent:
safe to run every build regardless of cache state.

Why:
  - moxygen@4095b18 pins proxygen 2052038ce4db, which has a use-after-free in
    WebTransportImpl::onWebTransportUniStream that SIGSEGVs the FLV clients on
    the first server-initiated uni stream (openmoq/moqx#403). We re-pin proxygen
    to 3ad19acf ("Buffer unknown WebTransport uni/bidi streams in HQSession").
  - proxygen@3ad19acf's samples require mvfst timestamp-frame APIs newer than
    the mvfst moxygen@4095b18 pins, so:
      * BUILD_SAMPLES is forced OFF (moxygen links proxygen libs only; the hq /
        masque / push sample executables are skipped), and
      * the timestamp-frame references are removed from the one failing file,
        HQCommandLine.cpp (part of the unconditional proxygen_hq_samples object
        lib that moxygen does not link).
"""

import sys
from pathlib import Path

REPO = Path("/cache/scratch/repos/github.com-facebook-proxygen.git")
MANIFEST = Path("/app/moxygen/build/fbcode_builder/manifests/proxygen")


def log(msg: str) -> None:
    print(f"    patch_proxygen: {msg}")


def patch_manifest() -> None:
    if not MANIFEST.exists():
        log(f"SKIP manifest (missing {MANIFEST})")
        return
    src = MANIFEST.read_text()
    if "BUILD_SAMPLES" in src:
        log("manifest already has BUILD_SAMPLES; skipping")
        return
    MANIFEST.write_text(src + "\n[cmake.defines]\nBUILD_SAMPLES = OFF\n")
    log("patched manifest with BUILD_SAMPLES = OFF")


def patch_cmakelists() -> None:
    p = REPO / "CMakeLists.txt"
    if not p.exists():
        log(f"SKIP CMakeLists (missing {p})")
        return
    src = p.read_text()
    marker = 'set(BUILD_SAMPLES OFF CACHE BOOL "" FORCE)'
    if marker in src:
        log("CMakeLists already forces BUILD_SAMPLES=OFF; skipping")
        return
    anchor = (
        'option(BUILD_SAMPLES\n'
        '  "If enabled, proxygen will build various examples/samples"\n'
        '  ON\n'
        ')'
    )
    if anchor not in src:
        log("WARN: could not locate BUILD_SAMPLES option block; skipping")
        return
    insert = (
        "\n"
        "# moxygen build-compat: proxygen samples need mvfst timestamp-frame\n"
        "# APIs newer than the version moxygen pins; moxygen links proxygen\n"
        "# libs only. Applied by docker/moxygen/patch_proxygen.py.\n"
        "set(BUILD_SAMPLES OFF CACHE BOOL \"\" FORCE)\n"
    )
    p.write_text(src.replace(anchor, anchor + insert))
    log("patched CMakeLists: force BUILD_SAMPLES=OFF")


HQCOMMANDLINE = REPO / "proxygen/httpserver/samples/hq/HQCommandLine.cpp"

TS_TOKENS = (
    "kMaxTimestampFrameTimestampExponent",
    "TimestampFrameWriteMode",
    "advertisedTimestampFrameSupport",
    "oneRttTimestampFrameWriteMode",
    "timestampFrameTimestampExponent",
    "kDefaultTimestampFrameTimestampExponent",
)

# Line anchors for the timestamp-frame block in initializeTransportSettings.
TS_START_LINE = '  CHECK(FLAGS_timestamp_frame_mode == "disabled" ||'
TS_END_LINE = "      FLAGS_timestamp_frame_exponent;"


def patch_hqcommandline() -> None:
    if not HQCOMMANDLINE.exists():
        log(f"SKIP HQCommandLine.cpp (missing {HQCOMMANDLINE})")
        return
    src = HQCOMMANDLINE.read_text()
    changed = False

    if "kDefaultTimestampFrameTimestampExponent" in src:
        src = src.replace(
            "quic::kDefaultTimestampFrameTimestampExponent", "0"
        )
        changed = True

    if TS_START_LINE in src:
        lines = src.splitlines()
        start = end = None
        for i, ln in enumerate(lines):
            if ln == TS_START_LINE:
                start = i
            if ln == TS_END_LINE:
                end = i
        if start is not None and end is not None and start < end:
            replacement = (
                "  // timestamp-frame settings removed for mvfst build-compat"
                " (docker/moxygen/patch_proxygen.py)"
            )
            src = "\n".join(lines[:start] + [replacement] + lines[end + 1 :])
            if not src.endswith("\n"):
                src += "\n"
            changed = True

    if changed:
        HQCOMMANDLINE.write_text(src)
        log("patched HQCommandLine.cpp (removed mvfst timestamp-frame refs)")

    leftovers = []
    for other in sorted((HQCOMMANDLINE.parent).rglob("*.cpp")):
        if other == HQCOMMANDLINE:
            continue
        try:
            txt = other.read_text()
        except OSError:
            continue
        for tok in TS_TOKENS:
            if tok in txt:
                leftovers.append(f"{other.name}:{tok}")
    if leftovers:
        log("WARN: timestamp-frame tokens still referenced in hq samples:")
        for l in leftovers:
            log(f"      {l}")
    else:
        log("no other timestamp-frame references in samples/hq")
    if not changed:
        log("HQCommandLine.cpp already patched; skipping")


def main() -> int:
    if not REPO.exists():
        log(f"SKIP all (proxygen repo not present at {REPO})")
        return 0
    patch_manifest()
    patch_cmakelists()
    patch_hqcommandline()
    return 0


if __name__ == "__main__":
    sys.exit(main())