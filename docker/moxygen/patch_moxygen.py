#!/usr/bin/env python3
"""Client-side crash fixes for the getdeps-fetched moxygen checkout.

Applied by Dockerfile.media step [1.6] before the moxygen build. Idempotent:
safe to run every build regardless of cache state. The working tree is patched
in place at /cache/scratch/repos/github.com-facebookexperimental-moxygen.git
(the getdeps scratch repo), so the rebuilt binaries pick up the fixes.

Why (verified from the run logs):
  - MoQWebTransportClient.cpp calls session->drain() on the H3 session
    immediately after the WebTransport handshake. The MoQ session is then set up
    and the relay starts sending uni-streams (SUBSCRIBE_OK / control data) while
    the session is draining; the uni-stream dispatch lands on an already-torn
    down WebTransportImpl and SIGSEGVs the client
    (WebTransportImpl::onWebTransportUniStream -> _M_emplace_unique UAF,
    openmoq/moqx#403). Removing the premature drain keeps the H3 session open
    until MoQSession teardown / process exit closes it.
  - MoQFlvStreamerClient::publishLoop() runs on the global IO executor and
    iterates the subscriptions_ map while subscribe()/unsubscribe() mutate it on
    the EventBase thread. During relay-driven teardown (STOP_SENDING ->
    publishDone) the erase races the iteration and SIGSEGVs publishLoop. A mutex
    guards the map.
  - publishLoop()'s `while (moqClient_.getSession())` re-copies the moqSession_
    shared_ptr EVERY iteration. On teardown the EventBase thread closes/shuts
    down the session (controlReadLoop exits, ~MoQSession), releasing the last
    strong ref while the IO thread is mid-copy -> the shared_ptr copy reads a
    freed control block (shared_ptr_base.h:1075 __shared_count copy ctor) and
    SIGSEGVs. The session and EventBase are now captured ONCE up front and held
    as a weak_ptr + shared_ptr, and the loop uses weak.lock() per iteration
    (race-free), so teardown can no longer race the copy.
"""

import os
import re
import sys
from pathlib import Path

REPO = Path(
    os.environ.get(
        "MXYGEN_REPO",
        "/cache/scratch/repos/github.com-facebookexperimental-moxygen.git",
    )
)

WT_CLIENT = REPO / "moxygen/MoQWebTransportClient.cpp"
FLV_STREAMER = REPO / "moxygen/samples/flv_streamer_client/MoQFlvStreamerClient.cpp"

# Idempotency marker for the publishLoop close edit. A plain `marker in src`
# check is unusable here: `      }` (6 spaces) is a substring of the deeper-
# indented `        }` / `          }` lines, so a brace-only marker falsely
# matches the UNPATCHED source and the edit self-skips. Anchoring with ^ and
# MULTILINE requires the braces to be full lines: the patched source has TWO
# `      }` lines before `if (item->isEOF)`, the original has only one.
CLOSE_LOCK_RE = re.compile(
    r"^      }\n      }\n      if \(item->isEOF\) \{\n"
    r'        XLOG\(INFO\) << "FLV file EOF";',
    re.MULTILINE,
)


def log(msg: str) -> None:
    print(f"    patch_moxygen: {msg}")


def _write(p: Path, src: str, msg: str) -> None:
    if not src.endswith("\n"):
        src += "\n"
    p.write_text(src)
    log(msg)


def patch_wt_client() -> bool:
    if not WT_CLIENT.exists():
        log(f"SKIP MoQWebTransportClient.cpp (missing {WT_CLIENT})")
        return False
    src = WT_CLIENT.read_text()
    if "session->drain() removed" in src:
        log("MoQWebTransportClient.cpp already patched; skipping")
        return False
    old = "  session->drain();\n  wt = wtTry.value();"
    new = (
        "  // session->drain() removed (docker/moxygen/patch_moxygen.py): draining\n"
        "  // the H3 session right after the WebTransport handshake races with\n"
        "  // in-flight uni-stream dispatch and SIGSEGVs the client\n"
        "  // (openmoq/moqx#403, WebTransportImpl::onWebTransportUniStream UAF).\n"
        "  // The session is closed by MoQSession teardown or process exit.\n"
        "  wt = wtTry.value();"
    )
    if old not in src:
        log("WARN: drain() anchor not found in MoQWebTransportClient.cpp; skipping")
        return False
    _write(WT_CLIENT, src.replace(old, new), "removed session->drain()")
    return True


def patch_flv_streamer() -> bool:
    if not FLV_STREAMER.exists():
        log(f"SKIP MoQFlvStreamerClient.cpp (missing {FLV_STREAMER})")
        return False
    src = FLV_STREAMER.read_text()

    # (idempotency marker, anchor, replacement, description)
    edits = [
        (
            "#include <mutex>",
            "#include <signal.h>\n"
            "#include <moxygen/util/InsecureVerifierDangerousDoNotUseInProduction.h>",
            "#include <signal.h>\n"
            "#include <mutex>\n"
            "#include <moxygen/util/InsecureVerifierDangerousDoNotUseInProduction.h>",
            "added <mutex> include",
        ),
        (
            "std::mutex subscriptionsMtx_;",
            "  std::map<RequestID, std::shared_ptr<Subscription>> subscriptions_;\n"
            "  std::shared_ptr<TrackConsumer> audioPub_;",
            "  std::map<RequestID, std::shared_ptr<Subscription>> subscriptions_;\n"
            "  // Guards subscriptions_ between publishLoop (IO executor) and\n"
            "  // subscribe/unsubscribe (EventBase). Added by\n"
            "  // docker/moxygen/patch_moxygen.py.\n"
            "  std::mutex subscriptionsMtx_;\n"
            "  std::shared_ptr<TrackConsumer> audioPub_;",
            "added subscriptionsMtx_ member",
        ),
        (
            "std::lock_guard<std::mutex> subscriptionsGuard(subscriptionsMtx_);\n"
            "    if (subscribeReq.fullTrackName == fullVideoTrackName_) {",
            "    auto consumerPtr = consumer.get();\n"
            "    if (subscribeReq.fullTrackName == fullVideoTrackName_) {",
            "    auto consumerPtr = consumer.get();\n"
            "    // Lock across the video/audio assignment and the emplace below\n"
            "    // (publishLoop iterates this map on the IO executor). Added by\n"
            "    // docker/moxygen/patch_moxygen.py.\n"
            "    std::lock_guard<std::mutex> subscriptionsGuard(subscriptionsMtx_);\n"
            "    if (subscribeReq.fullTrackName == fullVideoTrackName_) {",
            "locked subscribe() mutation",
        ),
        (
            "client_.subscriptionsMtx_);",
            "      // Delete subscribe/this\n"
            "      client_.subscriptions_.erase(requestID);",
            "      // Delete subscribe/this\n"
            "      {\n"
            "        std::lock_guard<std::mutex> subscriptionsGuard(\n"
            "            client_.subscriptionsMtx_);\n"
            "        client_.subscriptions_.erase(requestID);\n"
            "      }",
            "locked unsubscribe() erase",
        ),
        (
            "std::lock_guard<std::mutex> subscriptionsGuard(\n"
            "            subscriptionsMtx_);\n"
            "        for (auto& sub : subscriptions_) {",
            "      for (auto& sub : subscriptions_) {",
            "      {\n"
            "        std::lock_guard<std::mutex> subscriptionsGuard(\n"
            "            subscriptionsMtx_);\n"
            "        for (auto& sub : subscriptions_) {",
            "locked publishLoop() iteration (open)",
        ),
        (
            "      }\n"
            "      }\n"
            "      if (item->isEOF) {\n"
            "        XLOG(INFO) << \"FLV file EOF\";",
            "      }\n"
            "      if (item->isEOF) {\n"
            "        XLOG(INFO) << \"FLV file EOF\";",
            "      }\n"
            "      }\n"
            "      if (item->isEOF) {\n"
            "        XLOG(INFO) << \"FLV file EOF\";",
            "locked publishLoop() iteration (close)",
        ),
        (
            "std::weak_ptr<MoQSession> sessionWeak",
            "    while (moqClient_.getSession()) {",
            "    // Capture the session once and hold it weakly: re-copying\n"
            "    // moqClient_.getSession() every iteration races the EventBase\n"
            "    // thread's teardown (close/shutdown resets moqSession_), freeing\n"
            "    // the shared_ptr control block under the copy and SIGSEGVing\n"
            "    // publishLoop. lock() per iteration is race-free. Added by\n"
            "    // docker/moxygen/patch_moxygen.py.\n"
            "    std::weak_ptr<MoQSession> sessionWeak = moqClient_.getSession();\n"
            "    auto evb = moqClient_.getEventBase();\n"
            "    while (sessionWeak.lock()) {",
            "captured session weak_ptr + evb (publishLoop loop condition)",
        ),
    ]

    applied = []
    for marker, old, new, desc in edits:
        if desc == "locked publishLoop() iteration (close)":
            if CLOSE_LOCK_RE.search(src):
                log(f"    {desc}: already applied; skipping")
                continue
        elif marker in src:
            log(f"    {desc}: already applied; skipping")
            continue
        if old not in src:
            log(f"WARN: {desc}: anchor not found; skipping")
            continue
        src = src.replace(old, new, 1)
        applied.append(desc)

    # evb->add(...) in the video and audio dispatch lambdas
    if "evb->add(" not in src:
        if "moqClient_.getEventBase()->add(" in src:
            src = src.replace("moqClient_.getEventBase()->add(", "evb->add(")
            applied.append("evb->add( in publishLoop lambdas")
        else:
            log("WARN: moqClient_.getEventBase()->add( anchor not found; skipping")
    else:
        log("    evb->add( already applied; skipping")

    _write(FLV_STREAMER, src, f"MoQFlvStreamerClient.cpp patched ({len(applied)} edits)")
    return bool(applied)


def main() -> int:
    if not REPO.exists():
        log(f"SKIP all (moxygen repo not present at {REPO})")
        return 0
    changed = patch_wt_client()
    changed = patch_flv_streamer() or changed
    log("done" if changed else "no changes needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())