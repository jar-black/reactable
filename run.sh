#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-wayland}"

for _ in $(seq 1 50); do
    [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] && break
    sleep 0.2
done

AUDIO=""
[ "${1:-}" = "--audio" ] && AUDIO="--audio"

# Projector also acts as a light source for the camera (0 = black, 255 = white)
BACKGROUND="${BACKGROUND:-180}"

# Startup auto-calibration: project corner markers, detect them, save homography.npy
if ! python3 -u calibrate.py --auto; then
    echo "WARN: startup calibration failed; using existing homography.npy if present"
fi

python3 -u renderer.py $AUDIO --background "$BACKGROUND" &
RPID=$!
# Lower capture resolution keeps tracker latency down; coords are still scaled to 1280x720 calib space
TRACKER_SIZE="${TRACKER_SIZE:-640x360}"
TW=${TRACKER_SIZE%x*}
TH=${TRACKER_SIZE#*x}
python3 -u tracker.py --width "$TW" --height "$TH" &
TPID=$!

trap 'kill $RPID $TPID 2>/dev/null' EXIT INT TERM
wait
