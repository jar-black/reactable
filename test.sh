#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-0
export SDL_VIDEODRIVER=wayland
exec python3 -u renderer.py --test
