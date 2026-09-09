# ReacTable POC — Environment Notes

> IMPORTANT: This build is running on a **Raspberry Pi 4 Model B Rev 1.4 (4 GB)**, NOT a Rock 3c.
> OS is **Raspberry Pi OS (Debian 13 "trixie")**, not Armbian. Plan is otherwise followed as-is.

## System

- Board: Raspberry Pi 4 Model B Rev 1.4 (4 GB)
- Kernel: `6.18.34+rpt-rpi-v8` (aarch64, `arm_64bit=1`)
- OS: Debian GNU/Linux 13 (trixie), Raspberry Pi OS desktop
- Hostname: `raspberrypi`
- User: `johan` (sudo, password prompt)

## Display / session

- Default target: `graphical.target`, display manager: `lightdm`
- Desktop: Raspberry Pi OS Wayland (`labwc` 0.9.8) with XWayland; X11 (`openbox`) also installed
- Current login session is `tty` (headless / SSH) — no active `$DISPLAY` or `$WAYLAND_DISPLAY`
- `wlr-randr` available (Wayland output control) and `xrandr` available (X11 output control)
- Projector (HDMI) must be driven by an active desktop session; no extra X install needed

## Tooling installed (Phase 0)

- `build-essential cmake git v4l-utils alsa-utils python3 python3-pip`
- `python3-opencv` (OpenCV **4.10.0**, `cv2.aruco` present) + `libopencv-dev` (incl. contrib)
- `x11-xserver-utils feh mpv ffmpeg`

## Device paths (Phase 1)

- **Webcam**: Logitech B525 HD Webcam (UVC) — `/dev/video0` (capture), `/dev/video1` (meta)
  - Formats: `YUYV` (max 640x480@30), `MJPG` (max **1920x1080@30**); use MJPEG for 720p/1080p
  - Built-in mic = ALSA card 3 (`B525 HD Webcam`)
  - **Pinned** via udev → `/dev/webcam` (rule `/etc/udev/rules.d/99-reactable-webcam.rules`, id 046d:0836, capture node `index=0`)
  - Captured `test.jpg` 1280x720 OK; scene is DARK (mean BGR ≈ 7/255) — check lighting for ArUco later
- **Projector / HDMI output**: `HDMI-A-2` — "Hitachi ... Hichip TV", **1920x1080@60 Hz**, enabled + current
  - Driven by running `labwc` Wayland compositor (socket `/run/user/1000/wayland-0`)
  - Fullscreen test image rendered OK via `mpv --vo=gpu` (see below for env)
  - HDMI-A-1 is disconnected
- **Audio (speaker)**: no USB speaker present. Default sink = analog 3.5mm jack
  - `pw-play` → default sink "Inbyggt ljud Stereo" (analog) **works**
  - `aplay -D plughw:2,0` (card 2 `Headphones` / bcm2835) **works**
  - `aplay -D default` / `speaker-test` FAIL with ALSA error 524 (`default` PCM misconfigured); HDMI audio = cards 0/1

### Display/audio env for SSH-driven rendering

```sh
export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-0
```

## Phase 2 — ArUco tracker

- Used system `python3-opencv` (4.10.0) — full ArUco API present. **Skipped** `pip install opencv-contrib-python` / `python-osc` (would conflict; OSC not needed for POC).
- Files: `tracking.py` (shared detector + `open_camera`), `tracker.py` (UDP/JSON on 127.0.0.1:7000), `make_marker.py`, `markers/marker_*.png`.
- **Gotcha 1**: `cv2.VideoCapture(0)` defaults to GStreamer backend which FAILS on this build; must force V4L2: `cv2.VideoCapture(0, cv2.CAP_V4L2)`.
- **Gotcha 2**: `generateImageMarker` output has NO quiet zone → undetected as-is. Pad with ≥1 cell of white (`make_marker.py` does this).
- Angle convention: physical CW rotation → angle decreases (0→270→180→90). Full 0–360 covered; invert later if CW color sweep is wanted.
- Perf (benchmarked 2026-09-09, tracker alone): 1280x720 CLAHE+subpix ≈ 9.8 fps, 1280x720 CLAHE no-subpix ≈ 10.6 fps, **960x540 CLAHE no-subpix ≈ 16.6 fps**, without CLAHE detections collapse (≈0.03/frame) — **CLAHE is mandatory** in this dark scene. Defaults are now 960x540, CLAHE on, subpixel refinement off. With the renderer running, tracker fps is lower (~8–9); renderer now ticks at 30 fps to leave CPU headroom.
- Coordinates: `tracker.py` scales detected `(x,y)` from the actual capture size to **1280x720 calibration coords** before sending, so `homography.npy` stays valid at any capture resolution.

### Run tracker

```sh
python3 -u tracker.py            # 960x540, CLAHE, coords scaled to 1280x720 calib -> UDP 7000
python3 -u tracker.py --show     # X11 preview window (needs DISPLAY)
```

## Phase 3 — Camera–projector calibration (dynamic play area)

- `layout.py` holds projector constants: `PROJ_W/H = 1920/1080`, `CALIB_W/H = 1280/720`, `MARKER_SIZE = 130`, `MARGIN = 160`, a **6×6 grid of 36 calibration markers** `POSITIONS` (ids **4–39**, kept away from puck ids 0–3), `PLAY_MARGIN_CAM = 80`, and the fallback `play_rect()`.
- `calibrate.py`:
  - `python3 calibrate.py --pattern` → `calib_pattern.png` (36-marker grid)
  - `python3 calibrate.py --auto` → projects the grid fullscreen itself (pygame), waits 6 s for exposure, detects **any visible grid markers** (needs ≥4 with enough spread), `cv2.findHomography(camera, projector)` → `homography.npy`; retries 3×, exit code 0/1. This is what `run.sh` runs at startup.
  - Manual flow still works: project the pattern (Gotcha 3), then `python3 calibrate.py`
- **Dynamic play area**: after the homography is found, the camera frame (inset by `PLAY_MARGIN_CAM` calib px for marker visibility) is mapped to projector coords, clipped to the projector canvas, and the **largest axis-aligned rectangle inside that visible region** is saved as `playarea.npy`. This works even when the camera only sees part of the projected canvas (e.g. top clipped, or only one half) — the play area becomes the biggest usable region the camera can see.
- **Gotcha 3**: `mpv` on a still image exits immediately; use `mpv --loop=inf --image-display-duration=inf`.
- **Gotcha 4**: projector/camera auto-exposure takes a couple seconds to settle — `--auto` waits ~6 s after the pattern appears.
- **Gotcha 5**: if the webcam cannot see at least 4 grid markers with enough spread, calibration fails and `run.sh` continues with the existing `homography.npy`/`playarea.npy`. Aim the camera so the projected picture (or the playable part of it) is in view and in focus.

## Phase 4 — Renderer

- `renderer.py`: pygame fullscreen (SDL **wayland** driver) on the projector at 30 fps; binds UDP 7000; applies `homography.npy` to each `(x,y)`; draws a **glowing square** around each physical marker with a clear dark gap between the marker edge and the glow (`SQUARE_INNER/OUTER = 1.4/1.9` × marker size) to avoid interfering with ArUco detection, **rotated to the marker's projected orientation**, colored by `angle → HSV hue`; square size is auto-fit from the tracker's `size` field (clamped 30–150 px, median of the last 5); a marker must be unseen for 0.5 s (`--timeout`) before its glow disappears; position is a median of the last 5 samples.
- Play area: loaded from `playarea.npy` (falls back to the fixed `play_rect()` when absent); a dim border is drawn around it; markers outside it are hidden (no glow/audio/beat) until they return. Debug overlay shows `inside/total` marker counts.
- `tracker.py` UDP JSON now includes `size` (mean marker side length scaled to 1280×720 calib coords); renderer falls back to `--radius` if `size` is missing.
- `--background N` (0–255) turns the projector into a light source for the camera; `run.sh` passes `--background 180` by default (override with `BACKGROUND=0 ./run.sh`).
- `run.sh`: runs `calibrate.py --auto` first (continues on failure with the existing `homography.npy`/`playarea.npy`), then launches renderer + tracker (sets `XDG_RUNTIME_DIR`/`WAYLAND_DISPLAY`/`SDL_VIDEODRIVER`).
- pygame/SDL needs `SDL_VIDEODRIVER=wayland` (else it may fall back to X11/XWayland).

### Run the full pipeline

```sh
./run.sh               # startup calibration, then tracker + renderer; Ctrl+C to stop
./run.sh --audio       # + tone pitched by marker angle
```

Startup projects the 36-marker grid for ~6 s while the webcam calibrates; if calibration fails it continues with the saved `homography.npy` and `playarea.npy`.

## Phase 5 — Fiducial marker

- `make_marker.py` generates printable markers (`markers/marker_*.png`, 800px, quiet-zone padded). `--invert` for white-on-black.
- `make_puck.py` generates `puck.stl` (60 mm Ø × 5 mm flat puck) to glue/slot a paper marker onto. Print flat; keep marker matte + un-warped.

## Phase 6 — Audio

- `renderer.py --audio` plays a continuous tone pitched by the marker angle (200–1200 Hz via `numpy` sine + `pygame.sndarray.make_sound`), looping on a mixer channel; silences when no marker is seen (within the fade window).
- Audio goes through SDL → PipeWire → default sink (3.5mm jack, card 2).

## Detection tuning (glossy paper)

- Shared helper `tracking.py`: `make_detector()` (relaxed params: `errorCorrectionRate=0.8`, subpixel refinement **off**, `minMarkerPerimeterRate=0.02`, larger adaptive-thresh window) + `preprocess()` (CLAHE).
- `tracker.py --raw` disables CLAHE — **don't**: benchmark showed detections collapse without CLAHE in this dark scene (0.03/frame vs ~2.9/frame).
- `tracker.py` smooths each marker's angle at the source: circular median over the last 8 angles (`ANGLE_HISTORY`); UDP now also carries `frame` and `t` fields. Its log fps/rate are rolling 2 s windows.
- Physical fixes beat software: use **matte** paper (glossy specular highlights wash out cells), diffuse lighting, keep marker flat and large.

> Tuning notes: renderer's black background dims the table → keep marker contrast high. Angle→hue sweeps opposite to physical CW rotation (invert hue if desired).

## Deployment / autostart

- `install.sh` installs the udev rule (`/etc/udev/rules.d/99-reactable-webcam.rules`) and a **systemd user service** (`~/.config/systemd/user/reactable.service`), then `systemctl --user enable`s it.
- The service runs `run.sh` (tracker + renderer), `WantedBy=default.target`, `Restart=on-failure`. `run.sh` waits for the Wayland socket before launching, so boot-order race is handled.
- lightdm auto-logs in `johan` (`autologin-session=rpd-labwc`), so the pipeline starts fully headless on boot.
- Manage: `systemctl --user status|restart|stop reactable`; logs via `journalctl --user -u reactable`.
- Enable audio at boot: edit the service `ExecStart=` to `/home/johan/reactable/run.sh --audio`, then `systemctl --user daemon-reload && systemctl --user restart reactable`.
