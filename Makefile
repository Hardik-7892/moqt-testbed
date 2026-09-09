.PHONY: setup fetch-bbb fetch-bbb-video fetch-flv build-all build-moq-rs build-moxygen build-imquic build-moqtail build-moq-dev build-quiche-moq build-lldash build-lldash-h2 build-lldash-h3 test test-quick test-built test-full test-bbb test-bbb-smoke test-bbb-smoke-nocap test-bbb-smoke-video test-moxygen-self test-moqrs-self test-chainfanout test-imquic-self test-impairments test-chain test-fanout test-fairness test-fairness-bbb test-bufferbloat test-mismatch test-latency test-bandwidth test-loss test-queue test-cross-impl test-multi-pub-sub test-congestion-cascade test-track-priority test-join-leave test-datagram test-aqm test-bbr-fairness test-lldash test-lldash-h2 test-lldash-h3 test-moq-vs-lldash test-all test-all-quick test-all-impairments test-all-sweeps test-all-sample test-all-full verify clean logs report help

SHELL := /bin/bash
PARALLEL := 1
# FAST_IO=1 stages subscriber output / qlogs / pcaps on VM-local disk during
# the run and copies them back afterwards (B37: shared-folder write sync was
# throttling BBB transfers to ~1-4 Mbps with silent relay group-skipping).
FAST_IO ?= 0
MXY_TAG := 4095b1811a2d69d267a858b6483fc72fa7ea0588-amd64
# Official ghcr moqrelay tag (kept for reference; the relay image is now built
# FROM our source-built client image, docker/moxygen/Dockerfile.relay, so the
# server also runs the fixed proxygen).
# Source commit we rebuild moxygen's media clients from (matches MXY_TAG's SHA).
# Official images only ship moqrelayserver / moq_interop_client; the FLV
# pub/sub clients (moqflvstreamerclient / moqflvreceiverclient) need a source
# build (docker/moxygen/Dockerfile.media).
MXY_COMMIT := 4095b1811a2d69d267a858b6483fc72fa7ea0588
# Override proxygen's pin only: moxygen@4095b18's proxygen pin (2052038ce4db)
# SIGSEGVs the FLV clients (use-after-free in WebTransportImpl::onWebTransportUniStream,
# openmoq/moqx#403); proxygen 3ad19acf fixes it and keeps the old qmux targets.
MXY_PROXYGEN_COMMIT := 3ad19acf78fb42db0b0a71ba0558af2b6c909d7b

help:
	@echo "MoQT Interop Testbed"
	@echo ""
	@echo "Targets:"
	@echo "  setup              Install Python deps, check Docker/Containernet"
	@echo "  build-all          Build all Docker images (all impls, all drafts)"
	@echo "  build-moq-rs       Build Cloudflare moq-rs images"
	@echo "  build-moxygen      Build Meta moxygen images (client: source build w/ FLV media clients)"
	@echo "  build-imquic       Build Meetecho imquic images"
	@echo "  build-moqtail      Build OzU MOQtail images"
	@echo "  build-moq-dev      Build moq-dev (kixelated) images"
	@echo "  build-quiche-moq   Build Google quiche-moq image"
	@echo "  build-lldash       Build LL-DASH baseline H2+H3 (both)"
	@echo "  build-lldash-h2    Build LL-DASH H2 origin+client"
	@echo "  build-lldash-h3    Build LL-DASH H3 origin+client"
	@echo "  fetch-flv          Convert bbb.mp4 -> bbb.flv (moxygen media is FLV)"
	@echo "  verify             Run draft version verification (RQ1)"
	@echo "  test-quick         Run interop-quick test plan"
	@echo "  test-built         Run interop-built test plan (only built impls)"
	@echo "  test-moxygen-self  Run moxygen self-interop verify plan (FLV media)"
	@echo "  test-moqrs-self    Run moq-rs self-interop plan (all built drafts)"
	@echo "  test-chainfanout   Run chain+fanout combo plan (all impls + mixed)"
	@echo "  test-imquic-self   Run imquic self-interop plan (clock pub, object-receipt mode)"
	@echo "  test-bbb           Run Big Buck Bunny large-media plan (bbb.yaml)"
	@echo "  test-bbb-smoke     Run single-row BBB smoke plan (bbb-smoke.yaml, 180s cap)"
	@echo "  test-bbb-smoke-nocap  A/B: same row without pcap capture"
	@echo "  test-bbb-smoke-video  Single-track BBB (video-only) -- comparable+playable"
	@echo "  test-full          Run interop-full test plan"
	@echo "  test-impairments   Run impairment sweeps"
	@echo "  test-chain         Run relay-chain test plan (chain topology)"
	@echo "  test-fanout        Run fan-out test plan (multi-subscriber topology)"
	@echo "  test-fairness      Run fairness experiment (fanout with per-sub BW limits)"
	@echo "  test-bufferbloat   Run bufferbloat experiment (queue size vs latency)"
	@echo "  test-mismatch      Run true-negative mismatch controls (I1)"
	@echo "  test-latency       Latency sweep across topologies (basic/chain/fanout)"
	@echo "  test-bandwidth     Bandwidth sweep across topologies"
	@echo "  test-loss          Packet loss sweep across topologies"
	@echo "  test-queue         Queue size sweep across topologies"
	@echo "  test-cross-impl    Full cross-implementation matrix"
	@echo "  test-multi-pub-sub Multi-publisher / multi-subscriber scenarios"
	@echo "  test-congestion-cascade  Cascading congestion (chain + fanout)"
	@echo "  test-track-priority MoQ track priority & filter types"
	@echo "  test-join-leave    Join/leave dynamics (late-join, rejoin)"
	@echo "  test-datagram      Datagram vs stream transport mode"
	@echo "  test-aqm           AQM sweep (pfifo, fq_codel, cake)"
	@echo "  test-bbr-fairness  BBR vs CUBIC congestion control fairness"
	@echo "  test-all           Run ALL sweeps sequentially (basic suite)"
	@echo "  test-all-quick     Quick smoke: interop + fanout + chain + mismatch"
	@echo "  test-all-impairments  All impairment sweeps (latency+bw+loss+queue)"
	@echo "  test-all-sweeps    Extended sweeps (includes multi-pub, cascade, aqm)"
	@echo "  test-all-sample    Sample-only: all with sample.mp4/sample.flv (no BBB, fast)"
	@echo "  report             Generate analysis report from latest run"
	@echo "  logs               Tail latest test run logs"
	@echo "  clean              Remove Docker images and artifacts"
	@echo ""

setup:
	pip3 install -r requirements.txt 2>/dev/null || true
	sudo docker info > /dev/null 2>&1 || (echo "Docker not running"; exit 1)
	which ovs-vsctl > /dev/null 2>&1 || (echo "Install: sudo apt-get install -y openvswitch-switch"; exit 1)

fetch-bbb:
	bash scripts/fetch-bbb.sh

fetch-bbb-video:
	bash scripts/fetch-bbb-video.sh

fetch-flv:
	bash scripts/fetch-flv.sh

#
# Build targets
#
build-all: build-moq-rs build-moxygen build-imquic build-moqtail build-moq-dev build-quiche-moq

build-moq-rs:
	for d in 14 16 18; do \
		echo "Building moq-rs draft-$$d..."; \
		sudo docker build \
			--build-arg DRAFT=$$d \
			-t moq-rs/relay:$$d \
			-f docker/cloudflare-moq-rs/Dockerfile \
			docker/cloudflare-moq-rs/; \
		sudo docker tag moq-rs/relay:$$d moq-rs/client:$$d; \
		sudo docker tag moq-rs/relay:$$d 0hardikpandey/moq-rs-relay:$$d; \
		sudo docker tag moq-rs/client:$$d 0hardikpandey/moq-rs-client:$$d; \
	done
	@echo "moq-rs images ready (drafts 14, 16, 18)"

build-moxygen:
	set -e; \
	echo "Building moxygen client (source build w/ FLV media clients + fixed proxygen)..."; \
	sudo DOCKER_BUILDKIT=1 docker build \
		--build-arg MXY_COMMIT=$(MXY_COMMIT) \
		--build-arg MXY_PROXYGEN_COMMIT=$(MXY_PROXYGEN_COMMIT) \
		-t 0hardikpandey/moxygen-client:latest \
		-f docker/moxygen/Dockerfile.media \
		docker/moxygen/; \
	echo "Building moxygen relay from the fixed client image..."; \
	sudo docker build \
		-t 0hardikpandey/moxygen-relay:latest \
		-f docker/moxygen/Dockerfile.relay \
		docker/moxygen/; \
	for d in 14 16 18; do \
		sudo docker tag 0hardikpandey/moxygen-client:latest 0hardikpandey/moxygen-client:$$d; \
		sudo docker tag 0hardikpandey/moxygen-client:$$d moxygen/client:$$d; \
		sudo docker tag 0hardikpandey/moxygen-relay:latest 0hardikpandey/moxygen-relay:$$d; \
		sudo docker tag 0hardikpandey/moxygen-relay:$$d moxygen/relay:$$d; \
	done
	@echo "moxygen images ready (drafts 14, 16, 18)"

build-imquic:
	for d in 16 17 18 19; do \
		echo "Building imquic variant draft-$$d..."; \
		sudo docker build \
			--build-arg DRAFT=$$d \
			-t imquic/relay:$$d \
			-f docker/imquic/Dockerfile.relay \
			docker/imquic/; \
		sudo docker build \
			--build-arg DRAFT=$$d \
			-t imquic/cli:$$d \
			-f docker/imquic/Dockerfile.cli \
			docker/imquic/; \
		sudo docker tag imquic/relay:$$d 0hardikpandey/imquic-relay:$$d; \
		sudo docker tag imquic/cli:$$d 0hardikpandey/imquic-cli:$$d; \
	done
	@echo "imquic images ready (drafts 16, 17, 18, 19)"

build-moqtail:
	sudo docker build \
		-t moqtail/relay:16 \
		-f docker/moqtail/Dockerfile \
		docker/moqtail/; \
	sudo docker tag moqtail/relay:16 moqtail/client:16
	@echo "moqtail images ready (draft 16)"

build-moq-dev:
	sudo docker pull moqdev/moq-relay:latest
	sudo docker pull moqdev/moq-cli:latest
	sudo docker build \
		-t moq-dev/relay:latest \
		-f docker/moq-dev/relay.Dockerfile \
		docker/moq-dev/; \
	sudo docker build \
		-t moq-dev/cli:latest \
		-f docker/moq-dev/cli.Dockerfile \
		docker/moq-dev/
	@echo "moq-dev images ready (use MOQ_MODE=ietf for full IETF mode)"

build-quiche-moq:
	sudo docker build \
		-t quiche-moq:16 \
		-f docker/quiche-moq/Dockerfile \
		docker/quiche-moq/
	@echo "quiche-moq image ready (draft 16)"

build-lldash-h2:
	sudo docker build \
		-t 0hardikpandey/lldash-origin-h2:latest \
		-f docker/lldash/Dockerfile.origin.h2 \
		docker/lldash/
	sudo docker build \
		-t 0hardikpandey/lldash-client-h2:latest \
		-f docker/lldash/Dockerfile.client \
		docker/lldash/
	@echo "lldash H2 images ready (origin-h2 + client-h2)"

build-lldash-h3:
	sudo docker build \
		-t 0hardikpandey/lldash-origin-h3:latest \
		-f docker/lldash/Dockerfile.origin.h3 \
		docker/lldash/
	sudo docker build \
		-t 0hardikpandey/lldash-client-h3:latest \
		-f docker/lldash/Dockerfile.client \
		docker/lldash/
	@echo "lldash H3 images ready (origin-h3 + client-h3)"

build-lldash: build-lldash-h2 build-lldash-h3
	@echo "lldash images ready (H2 + H3)"

#
# Verification
#
verify:
	python3 -m harness.verify

#
# Test targets
#
test: test-quick

test-quick:
	python3 run_testbed.py --plan testplans/interop-quick.yaml --workers $(PARALLEL)

testdata/sample.mp4:
	which ffmpeg > /dev/null 2>&1 || sudo apt-get install -y ffmpeg
	@if [ -f /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf ]; then \
		FONT="fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"; \
	else \
		FONT=""; \
	fi; \
	ffmpeg -f lavfi -i "color=c=red:s=320x240:r=30:d=10,drawtext=$${FONT}text='%{eif\:10-t\:d} seconds':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2-16:box=1:boxcolor=black@0.5,drawtext=$${FONT}text='%{eif\:(10-t)*1000-1000*trunc(10-t)\:d} milliseconds':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2+16:box=1:boxcolor=black@0.5" -an -c:v libx264 -pix_fmt yuv420p -g 30 -force_key_frames expr:gte\(t,n_forced*1\) -t 10 -movflags empty_moov+frag_keyframe+separate_moof testdata/sample.mp4 -y
	@ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 testdata/sample.mp4 2>/dev/null | xargs -I{} sh -c 'echo "sample.mp4 duration: {}s (expected 10.000000)"'

testdata/sample_120s.mp4:
	which ffmpeg > /dev/null 2>&1 || sudo apt-get install -y ffmpeg
	@if [ -f /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf ]; then \
		FONT="fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"; \
	else \
		FONT=""; \
	fi; \
	ffmpeg -f lavfi -i "color=c=red:s=320x240:r=30:d=120,drawtext=$${FONT}text='%{eif\:120-t\:d} seconds':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2-16:box=1:boxcolor=black@0.5,drawtext=$${FONT}text='%{eif\:(120-t)*1000-1000*trunc(120-t)\:d} milliseconds':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2+16:box=1:boxcolor=black@0.5" -an -c:v libx264 -pix_fmt yuv420p -g 60 -force_key_frames expr:gte\(t,n_forced*2\) -t 120 -movflags empty_moov+frag_keyframe+separate_moof testdata/sample_120s.mp4 -y
	@ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 testdata/sample_120s.mp4 2>/dev/null | xargs -I{} sh -c 'echo "sample_120s.mp4 duration: {}s (expected 120.000000)"'

testdata/sample_120s.flv: testdata/sample_120s.mp4
	which ffmpeg > /dev/null 2>&1 || sudo apt-get install -y ffmpeg
	ffmpeg -y -i testdata/sample_120s.mp4 -c copy testdata/sample_120s.flv 2>/dev/null || ffmpeg -y -i testdata/sample_120s.mp4 -c:v libx264 -an testdata/sample_120s.flv >/dev/null 2>&1
	@ls -lh testdata/sample_120s.flv 2>/dev/null | awk '{print "sample_120s.flv: " $$9 " " $$5}'

testdata/sample_120s.mpd: testdata/sample_120s.mp4
	@echo "Generating DASH MPD (2s segments) for sample_120s.mp4..."
	@if command -v MP4Box >/dev/null 2>&1; then \
		echo "Using MP4Box -dash 2000 -frag 2000"; \
		MP4Box -dash 2000 -frag 2000 -profile live -out testdata/sample_120s.mpd testdata/sample_120s.mp4 2>/dev/null && ls -lh testdata/sample_120s.mpd testdata/sample_120s*.m4s 2>/dev/null | head -n 20; \
	elif ffmpeg -h 2>&1 | grep -q dash; then \
		echo "Using ffmpeg -f dash fallback"; \
		mkdir -p testdata/dash && ffmpeg -y -i testdata/sample_120s.mp4 -c copy -f dash -seg_duration 2 -use_timeline 1 -use_template 1 testdata/sample_120s.mpd 2>/dev/null && ls -lh testdata/sample_120s.mpd 2>/dev/null; \
	else \
		echo "No MP4Box/ffmpeg dash — generating minimal MPD placeholder"; \
		python3 scripts/gen-lldash-mpd.py testdata/sample_120s.mp4 testdata/sample_120s.mpd 2>/dev/null || cp testdata/sample_120s.mp4 testdata/sample_120s.mpd; \
	fi
	@ls -lh testdata/sample_120s.mpd 2>/dev/null | awk '{print "sample_120s.mpd: " $$9 " " $$5}'

testdata/bbb.mp4:
	bash scripts/fetch-bbb.sh

testdata/sample.flv: testdata/sample.mp4
	which ffmpeg > /dev/null 2>&1 || sudo apt-get install -y ffmpeg
	ffmpeg -y -i testdata/sample.mp4 -c copy testdata/sample.flv 2>/dev/null || ffmpeg -y -i testdata/sample.mp4 -c:v libx264 -an testdata/sample.flv >/dev/null 2>&1
	@ls -lh testdata/sample.flv 2>/dev/null | awk '{print "sample.flv: " $$9 " " $$5}'

testdata/sample.mpd: testdata/sample.mp4
	which ffmpeg > /dev/null 2>&1 || sudo apt-get install -y ffmpeg
	@echo "Generating DASH MPD (2s segments, sample10-* prefix) for sample.mp4..."
	@cd testdata && ffmpeg -y -i sample.mp4 -c copy -f dash -seg_duration 2 -use_timeline 1 -use_template 1 -init_seg_name sample10-init.m4s -media_seg_name 'sample10-chunk-$$Number%05d$$.m4s' sample.mpd 2>/dev/null || python3 ../scripts/gen-lldash-mpd.py sample.mp4 sample.mpd
	@ls -lh testdata/sample.mpd testdata/sample10-*.m4s 2>/dev/null | head -n 10

testdata/bbb.flv: testdata/bbb.mp4
	bash scripts/fetch-flv.sh

test-moxygen-self: testdata/bbb.flv
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	python3 run_testbed.py --plan testplans/moxygen-self.yaml --workers $(PARALLEL)

test-moqrs-self: testdata/sample.mp4
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	python3 run_testbed.py --plan testplans/moq-rs-self.yaml --workers $(PARALLEL)

test-chainfanout: testdata/sample.mp4
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	python3 run_testbed.py --plan testplans/chainfanout.yaml --workers $(PARALLEL)

test-imquic-self:
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	python3 run_testbed.py --plan testplans/imquic-self.yaml --workers $(PARALLEL)

test-built: testdata/sample.mp4
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	python3 run_testbed.py --plan testplans/interop-built.yaml --workers $(PARALLEL)

test-bbb: testdata/bbb.mp4
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	python3 run_testbed.py --plan testplans/bbb.yaml --workers $(PARALLEL)

test-bbb-smoke: testdata/bbb.mp4
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	sudo MOQ_FAST_IO=$(FAST_IO) python3 run_testbed.py --plan testplans/bbb-smoke.yaml --workers $(PARALLEL)

testdata/bbb-video.mp4: testdata/bbb.mp4
	bash scripts/fetch-bbb-video.sh

test-bbb-smoke-nocap: testdata/bbb.mp4
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	sudo MOQ_FAST_IO=$(FAST_IO) python3 run_testbed.py --plan testplans/bbb-smoke-nocap.yaml --workers $(PARALLEL)

test-bbb-smoke-video: testdata/bbb-video.mp4
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	sudo MOQ_FAST_IO=$(FAST_IO) python3 run_testbed.py --plan testplans/bbb-smoke-video.yaml --workers $(PARALLEL)

test-full:
	python3 run_testbed.py --plan testplans/interop-full.yaml --workers $(PARALLEL)

test-impairments:
	python3 run_testbed.py --plan testplans/impairments.yaml --workers $(PARALLEL)

test-chain:
	python3 run_testbed.py --plan testplans/chain.yaml --workers $(PARALLEL)

test-fanout:
	python3 run_testbed.py --plan testplans/fanout.yaml --workers $(PARALLEL)

test-fairness:
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.sub2 mn.sub3 mn.sub4 mn.s1 2>/dev/null || true
	python3 run_testbed.py --plan testplans/fairness.yaml --workers $(PARALLEL)

test-bufferbloat:
	python3 run_testbed.py --plan testplans/bufferbloat.yaml --workers $(PARALLEL)

test-mismatch:
	-sudo docker rm -f mn.relay mn.pub mn.sub mn.s1 2>/dev/null || true
	python3 run_testbed.py --plan testplans/interop-mismatch.yaml --workers $(PARALLEL)

test-latency:
	python3 run_testbed.py --plan testplans/latency-sweep.yaml --workers $(PARALLEL)

test-bandwidth:
	python3 run_testbed.py --plan testplans/bandwidth-sweep.yaml --workers $(PARALLEL)

test-loss:
	python3 run_testbed.py --plan testplans/loss-sweep.yaml --workers $(PARALLEL)

test-queue:
	python3 run_testbed.py --plan testplans/queue-sweep.yaml --workers $(PARALLEL)

test-cross-impl:
	python3 run_testbed.py --plan testplans/cross-impl.yaml --workers $(PARALLEL)

test-multi-pub-sub:
	python3 run_testbed.py --plan testplans/future/multi-pub-sub.yaml --workers $(PARALLEL)

test-congestion-cascade:
	python3 run_testbed.py --plan testplans/future/congestion-cascade.yaml --workers $(PARALLEL)

test-track-priority:
	python3 run_testbed.py --plan testplans/future/track-priority.yaml --workers $(PARALLEL)

test-join-leave:
	python3 run_testbed.py --plan testplans/future/join-leave-dynamics.yaml --workers $(PARALLEL)

test-datagram:
	python3 run_testbed.py --plan testplans/future/datagram-vs-stream.yaml --workers $(PARALLEL)

test-aqm:
	python3 run_testbed.py --plan testplans/future/aqm-sweep.yaml --workers $(PARALLEL)

test-bbr-fairness:
	python3 run_testbed.py --plan testplans/future/bbr-cubic-fairness.yaml --workers $(PARALLEL)

test-lldash:
	python3 run_testbed.py --plan testplans/lldash-baseline.yaml --workers $(PARALLEL)

test-lldash-h2:
	python3 run_testbed.py --plan testplans/lldash-h2.yaml --workers $(PARALLEL)

test-lldash-h3:
	python3 run_testbed.py --plan testplans/lldash-h3.yaml --workers $(PARALLEL)

test-moq-vs-lldash:
	python3 run_testbed.py --plan testplans/moq-vs-lldash.yaml --workers $(PARALLEL)

# --- Meta-targets: run multiple plans sequentially ---

test-all-quick: testdata/sample.mp4
	@echo "========== test-all-quick: smoke suite (4 plans) =========="
	@$(MAKE) test-quick
	@$(MAKE) test-mismatch
	@$(MAKE) test-fanout
	@$(MAKE) test-chain
	@echo "========== test-all-quick: done =========="

test-all-impairments: testdata/sample.mp4
	@echo "========== test-all-impairments: latency+bw+loss+queue (4 plans) =========="
	@$(MAKE) test-latency
	@$(MAKE) test-bandwidth
	@$(MAKE) test-loss
	@$(MAKE) test-queue
	@echo "========== test-all-impairments: done =========="

test-all-sweeps: testdata/sample.mp4 testdata/bbb-video.mp4
	@echo "========== test-all-sweeps: QUARANTINED (Phase 1, 2026-09-06) =========="
	@echo "  multi-pub-sub, congestion-cascade, track-priority, join-leave, aqm"
	@echo "  live in testplans/future/ — unwired keys, fail fast by design."
	@echo "  See 2_weeks/01-future-work-quarantine.md. Citable sweeps are:"
	@echo "  test-all-impairments (latency+bw+loss+queue) + test-moq-vs-lldash."
	@echo "========== test-all-sweeps: nothing to run (quarantined) =========="

test-all: testdata/sample.mp4
	@echo "============================================================"
	@echo "  test-all: full MoQ interop + impairment + topology suite"
	@echo "  Plans: interop-quick, interop-mismatch, fanout, chain,"
	@echo "         impairments, bufferbloat, fairness, latency,"
	@echo "         bandwidth, loss, queue, cross-impl"
	@echo "  Total: ~95 runs  |  Estimated: 2-3 hours  |  FAST_IO=$(FAST_IO)"
	@echo "============================================================"
	@$(MAKE) test-quick
	@$(MAKE) test-mismatch
	@$(MAKE) test-fanout
	@$(MAKE) test-chain
	@$(MAKE) test-impairments
	@$(MAKE) test-bufferbloat
	@$(MAKE) test-fairness
	@$(MAKE) test-latency
	@$(MAKE) test-bandwidth
	@$(MAKE) test-loss
	@$(MAKE) test-queue
	@$(MAKE) test-cross-impl
	@echo "============================================================"
	@echo "  test-all: complete. Use 'make report' for latest HTML."
	@echo "  Full artifact tree: artifacts/runs/"
	@echo "============================================================"

test-all-full: testdata/sample.mp4 testdata/bbb-video.mp4
	@echo "============================================================"
	@echo "  test-all-full: EVERYTHING (basic + impairments + extended sweeps)"
	@echo "  = test-all + test-all-sweeps + bbr-fairness + datagram"
	@echo "  Total: ~145 runs  |  Estimated: 5-6 hours (overnight)  |  FAST_IO=$(FAST_IO)"
	@echo "============================================================"
	@$(MAKE) test-all
	@$(MAKE) test-all-sweeps
	@$(MAKE) test-bbr-fairness
	@$(MAKE) test-datagram
	@echo "============================================================"
	@echo "  test-all-full: complete. Every plan executed."
	@echo "  Full artifact tree: artifacts/runs/"
	@echo "============================================================"

test-all-sample: testdata/sample.mp4 testdata/sample.flv
	@echo "============================================================"
	@echo "  test-all-sample: CITABLE SUITE (Phase 1: quarantined plans excluded)"
	@echo "  = test-all + test-moq-vs-lldash + test-lldash (all sample.mp4)"
	@echo "  Plans: quick, mismatch, fanout, chain, impairments, bufferbloat,"
	@echo "         fairness, latency, bandwidth, loss, queue, cross-impl,"
	@echo "         moq-vs-lldash, lldash-baseline (quarantined: future/)"
	@echo "  Estimated: 3-4 hours  |  FAST_IO=$(FAST_IO)"
	@echo "============================================================"
	@if [ ! -f testdata/bbb-video.mp4 ]; then echo "NOTE: bbb-video.mp4 missing -> using sample.mp4 for extended sweeps (SAMPLE-ONLY mode)"; cp testdata/sample.mp4 testdata/bbb-video.mp4; BBB_TMP=1; else BBB_TMP=0; fi; \
	$(MAKE) test-all; \
	$(MAKE) test-moq-vs-lldash; \
	$(MAKE) test-lldash; \
	if [ "$$BBB_TMP" = "1" ]; then rm -f testdata/bbb-video.mp4; echo "cleaned tmp bbb-video.mp4 (was sample copy)"; fi
	@echo "============================================================"
	@echo "  test-all-sample: complete. CITABLE suite done (quarantined excluded)."
	@echo "  Artifacts: artifacts/runs/  report: make report"
	@echo "============================================================"

#
# Analysis
#
LATEST_RUN := $(shell cat artifacts/runs/.latest 2>/dev/null)

report:
	python3 -c "from harness.report import ReportGenerator; import sys; from pathlib import Path; r = ReportGenerator(Path('$(LATEST_RUN)')); p = r.save_report(); print(f'Report: {p}')"

logs:
	@tail -f $(LATEST_RUN)/logs/*.log 2>/dev/null || echo "No logs found"

#
# Cleanup
#
clean:
	-sudo docker rmi moq-rs/relay:18 moq-rs/client:18 0hardikpandey/moq-rs-relay:18 0hardikpandey/moq-rs-client:18 2>/dev/null
	-for d in 14 16 18; do sudo docker rmi 0hardikpandey/moxygen-relay:$$d 0hardikpandey/moxygen-client:$$d moxygen/relay:$$d moxygen/client:$$d 2>/dev/null; done
	-for d in 16 17 18 19; do sudo docker rmi imquic/relay:$$d imquic/cli:$$d 0hardikpandey/imquic-relay:$$d 0hardikpandey/imquic-cli:$$d 2>/dev/null; done
	-sudo docker rmi moqtail/relay:16 moqtail/client:16 2>/dev/null
	-sudo docker rmi moq-dev/relay:latest moq-dev/cli:latest 2>/dev/null
	-sudo docker rmi quiche-moq:16 2>/dev/null
	-sudo docker rmi 0hardikpandey/lldash-origin-h2:latest 0hardikpandey/lldash-origin-h3:latest 0hardikpandey/lldash-client-h2:latest 0hardikpandey/lldash-client-h3:latest 0hardikpandey/lldash-origin:latest 0hardikpandey/lldash-client:latest 2>/dev/null
	-rm -rf artifacts/runs/*
	@echo "Cleaned up"
