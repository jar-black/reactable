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
- Perf: ~18 fps @ 1280x720 MJPG (scene dark; exposure may throttle). Occasional spurious detection (~1/100 frames) — tune `DetectorParameters` later if stray circles appear.

### Run tracker

```sh
python3 -u tracker.py            # raw camera coords + angle -> UDP 7000 (uses /dev/webcam)
python3 -u tracker.py --show     # X11 preview window (needs DISPLAY)
```

## Phase 3 — Camera–projector calibration

- `calibrate.py`:
  - `python3 calibrate.py --pattern` → `calib_pattern.png` (4 ArUco markers at fixed projector coords `POSITIONS`)
  - project it fullscreen, then `python3 calibrate.py` → detects the 4 projected markers, `cv2.findHomography(camera, projector)` → `homography.npy`
- **Gotcha 3**: `mpv` on a still image exits immediately; use `mpv --loop=inf --image-display-duration=inf`.
- **Gotcha 4**: projector/camera auto-exposure takes a couple seconds to settle — wait ~6 s after the pattern appears before calibrating.
- Result: homography maps camera px → projector px (1920×1080). Reprojection error 0 px (4-point fit, exact).

## Phase 4 — Renderer

- `renderer.py`: pygame fullscreen (SDL **wayland** driver) on the projector; binds UDP 7000; applies `homography.npy` to each `(x,y)`; draws a radius-70 circle colored by `angle → HSV hue`; fades a marker out over ~10 frames when it stops being seen.
- `run.sh`: launches renderer + tracker together (sets `XDG_RUNTIME_DIR`/`WAYLAND_DISPLAY`/`SDL_VIDEODRIVER`).
- pygame/SDL needs `SDL_VIDEODRIVER=wayland` (else it may fall back to X11/XWayland).

### Run the full pipeline

```sh
./run.sh               # tracker + renderer; Ctrl+C to stop
./run.sh --audio       # + tone pitched by marker angle
```

## Phase 5 — Fiducial marker

- `make_marker.py` generates printable markers (`markers/marker_*.png`, 800px, quiet-zone padded). `--invert` for white-on-black.
- `make_puck.py` generates `puck.stl` (60 mm Ø × 5 mm flat puck) to glue/slot a paper marker onto. Print flat; keep marker matte + un-warped.

## Phase 6 — Audio

- `renderer.py --audio` plays a continuous tone pitched by the marker angle (200–1200 Hz via `numpy` sine + `pygame.sndarray.make_sound`), looping on a mixer channel; silences when no marker is seen (within the fade window).
- Audio goes through SDL → PipeWire → default sink (3.5mm jack, card 2).

## Detection tuning (glossy paper)

- Shared helper `tracking.py`: `make_detector()` (relaxed params: `errorCorrectionRate=0.8`, subpixel corner refinement, `minMarkerPerimeterRate=0.02`, larger adaptive-thresh window) + `preprocess()` (CLAHE).
- `tracker.py --raw` / edit `tracking.py` to disable CLAHE if it hurts. CLAHE helps with glare but can't be validated without a real marker in frame — tune empirically.
- Physical fixes beat software: use **matte** paper (glossy specular highlights wash out cells), diffuse lighting, keep marker flat and large.

> Tuning notes: renderer's black background dims the table → keep marker contrast high. Angle→hue sweeps opposite to physical CW rotation (invert hue if desired).

## Deployment / autostart

- `install.sh` installs the udev rule (`/etc/udev/rules.d/99-reactable-webcam.rules`) and a **systemd user service** (`~/.config/systemd/user/reactable.service`), then `systemctl --user enable`s it.
- The service runs `run.sh` (tracker + renderer), `WantedBy=default.target`, `Restart=on-failure`. `run.sh` waits for the Wayland socket before launching, so boot-order race is handled.
- lightdm auto-logs in `johan` (`autologin-session=rpd-labwc`), so the pipeline starts fully headless on boot.
- Manage: `systemctl --user status|restart|stop reactable`; logs via `journalctl --user -u reactable`.
- Enable audio at boot: edit the service `ExecStart=` to `/home/johan/reactable/run.sh --audio`, then `systemctl --user daemon-reload && systemctl --user restart reactable`.
