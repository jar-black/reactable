#!/usr/bin/env bash
set -euo pipefail
export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-0
cd "$(dirname "$0")"
python3 -u preview.py "$@" | mpv - \
  --demuxer=rawvideo \
  --demuxer-rawvideo-w=1280 --demuxer-rawvideo-h=720 \
  --demuxer-rawvideo-mp-format=bgr24 --demuxer-rawvideo-fps=30 \
  --vo=gpu --fullscreen --no-audio --no-cache --untimed
