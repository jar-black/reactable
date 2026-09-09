import argparse
import colorsys
import json
import math
import socket
import time

import numpy as np
import pygame

import layout

try:
    from drums import DrumKit, VOICES
except Exception:
    DrumKit = None
    VOICES = ("kick", "snare", "hihat", "clap", "tom")


def load_marker_config(path):
    defaults = {"beat_marker": 0, "sound_marker": 1}
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            "beat_marker": int(data.get("beat_marker", defaults["beat_marker"])),
            "sound_marker": int(data.get("sound_marker", defaults["sound_marker"])),
        }
    except (OSError, ValueError, TypeError):
        print(f"marker config {path} unavailable; using defaults {defaults}")
        return defaults


RPM_MIN = 30.0
RPM_MAX = 240.0
BEAT_MARKER_ID = 0
SOUND_MARKER_ID = 1
POS_EMA = 0.6
SIZE_EMA = 0.5
CENTER_COLOR = (60, 130, 255)
SIZE_MIN = 30.0
SIZE_MAX = 150.0
SQUARE_INNER = 1.4
SQUARE_OUTER = 1.9
SQUARE_LAYERS = 6
PLAY_RECT = layout.play_rect()


def transform(H, x, y):
    p = np.array([x, y, 1.0])
    q = H @ p
    return q[0] / q[2], q[1] / q[2]


def tone_freq(angle):
    return 200.0 + (angle % 360.0) / 360.0 * 1000.0


def make_tone(freq, rate=44100, dur=0.15):
    t = np.linspace(0.0, dur, int(rate * dur), endpoint=False)
    samples = (np.sin(2 * np.pi * freq * t) * 0.3 * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(samples)


def make_kick(rate=44100, dur=0.5):
    n = int(rate * dur)
    t = np.linspace(0.0, dur, n, endpoint=False)
    freq = 190.0 * np.exp(-t * 4.0) + 38.0
    phase = 2.0 * np.pi * np.cumsum(freq) / rate
    body = np.sin(phase) * np.exp(-t * 6.0)
    click_len = int(rate * 0.008)
    click = np.zeros(n)
    click[:click_len] = np.random.randn(click_len) * np.exp(-t[:click_len] * 400.0)
    samples = (body * 0.6 + click * 0.25) * 32767.0
    return pygame.sndarray.make_sound(samples.astype(np.int16))


def rpm_from_angle(angle):
    return RPM_MIN + (angle % 360.0) / 360.0 * (RPM_MAX - RPM_MIN)


def sound_index(angle):
    return int((angle % 360.0) / 360.0 * len(VOICES)) % len(VOICES)


def draw_glow(screen, pos, rgb, radius, intensity=1.0):
    layers = 8
    for i in range(layers, 0, -1):
        f = i / layers
        r = max(1, int(radius * f))
        a = intensity * (1.0 - f)
        color = (int(rgb[0] * a), int(rgb[1] * a), int(rgb[2] * a))
        pygame.draw.circle(screen, color, pos, r)
    core = (
        min(255, int(rgb[0] + (255 - rgb[0]) * 0.6 * intensity)),
        min(255, int(rgb[1] + (255 - rgb[1]) * 0.6 * intensity)),
        min(255, int(rgb[2] + (255 - rgb[2]) * 0.6 * intensity)),
    )
    pygame.draw.circle(screen, core, pos, max(2, int(radius * 0.18)))


def draw_square_glow(screen, pos, rgb, size, intensity=1.0, angle=0.0):
    half = size / 2.0
    inner = half * SQUARE_INNER
    outer = half * SQUARE_OUTER
    side = max(2, int(2 * outer))
    surf = pygame.Surface((side, side), pygame.SRCALPHA)
    center = side // 2
    for i in range(SQUARE_LAYERS, 0, -1):
        f = i / SQUARE_LAYERS
        h = inner + (outer - inner) * f
        a = intensity * (1.0 - f)
        color = (int(rgb[0]), int(rgb[1]), int(rgb[2]), int(a * 255))
        rect = pygame.Rect(0, 0, int(2 * h), int(2 * h))
        rect.center = (center, center)
        pygame.draw.rect(surf, color, rect)
    hole = pygame.Rect(0, 0, max(1, int(2 * inner)), max(1, int(2 * inner)))
    hole.center = (center, center)
    surf.fill((0, 0, 0, 0), hole)
    band = (
        min(255, int(rgb[0] + (255 - rgb[0]) * 0.6 * intensity)),
        min(255, int(rgb[1] + (255 - rgb[1]) * 0.6 * intensity)),
        min(255, int(rgb[2] + (255 - rgb[2]) * 0.6 * intensity)),
        255,
    )
    pygame.draw.rect(surf, band, hole, max(2, int(size * 0.04)))
    if angle:
        surf = pygame.transform.rotate(surf, -angle)
    screen.blit(surf, surf.get_rect(center=pos))


def inside_play_area(pos):
    x0, y0, x1, y1 = PLAY_RECT
    return x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1


def draw_play_border(screen, bg, label_color):
    x0, y0, x1, y1 = PLAY_RECT
    color = tuple(int(label_color[i] * 0.4 + bg * 0.6) for i in range(3))
    pygame.draw.rect(screen, color, (x0, y0, x1 - x0, y1 - y0), 3)


def main():
    p = argparse.ArgumentParser(description="Projector renderer (UDP in, glow squares out)")
    p.add_argument("--port", type=int, default=7000)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--radius", type=int, default=70,
                   help="fallback marker size when tracker sends no size; also test-mode circle radius")
    p.add_argument("--background", type=int, default=0,
                   help="screen background gray level 0-255 (use projector as light source)")
    p.add_argument("--homography", default="homography.npy")
    p.add_argument("--playarea", default="playarea.npy",
                   help="saved play-area rect [x0,y0,x1,y1]; falls back to layout.play_rect()")
    p.add_argument("--config", default="config.json",
                   help="JSON file mapping marker ids to roles (beat_marker, sound_marker)")
    p.add_argument("--timeout", type=float, default=0.5,
                   help="seconds a marker must be unseen before it disappears")
    p.add_argument("--test", action="store_true", help="animate a circle, ignore UDP")
    p.add_argument("--audio", action="store_true", help="play a tone pitched by marker angle")
    p.add_argument("--no-debug", action="store_true", help="hide status overlay")
    args = p.parse_args()

    global BEAT_MARKER_ID, SOUND_MARKER_ID
    roles = load_marker_config(args.config)
    BEAT_MARKER_ID = roles["beat_marker"]
    SOUND_MARKER_ID = roles["sound_marker"]
    print(f"marker roles: beat={BEAT_MARKER_ID}, sound={SOUND_MARKER_ID}")

    bg = max(0, min(255, args.background))
    label_color = (0, 0, 0) if bg > 127 else (255, 255, 255)

    try:
        H = np.load(args.homography)
        print(f"loaded {args.homography}")
    except FileNotFoundError:
        print("no homography file; using identity mapping")
        H = np.eye(3)

    global PLAY_RECT
    try:
        PLAY_RECT = tuple(float(v) for v in np.load(args.playarea))
        print(f"loaded {args.playarea}: {PLAY_RECT}")
    except (FileNotFoundError, ValueError):
        PLAY_RECT = layout.play_rect()
        print(f"no {args.playarea}; using default play rect {PLAY_RECT}")

    if args.audio:
        pygame.mixer.pre_init(44100, -16, 1, 512)
    pygame.init()
    screen = pygame.display.set_mode((args.width, args.height), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    font = pygame.font.SysFont(None, 36)

    channel = None
    if args.audio:
        try:
            pygame.mixer.init()
            channel = pygame.mixer.Channel(0)
        except pygame.error as e:
            print(f"tone audio unavailable ({e})")

    drumkit = None
    kick = None
    if DrumKit is not None:
        try:
            drumkit = DrumKit()
            print(f"drumkit ready (pyo), voices: {', '.join(VOICES)}")
        except Exception as e:
            print(f"pyo drumkit failed ({e}); falling back to pygame kick")
    if drumkit is None:
        try:
            pygame.mixer.init(44100, -16, 1, 512)
            kick = make_kick()
        except pygame.error as e:
            print(f"beat audio unavailable ({e})")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    sock.setblocking(False)

    markers = {}
    clock = pygame.time.Clock()
    frames = 0
    msg_count = 0
    last_msg = 0.0
    cur_freq = 0.0
    center = (args.width / 2.0, args.height / 2.0)
    phase = 0.0
    flash = 0.0
    prev_now = time.monotonic()
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        now = time.monotonic()
        dt = now - prev_now
        prev_now = now

        if not args.test:
            while True:
                try:
                    data, _addr = sock.recvfrom(65535)
                except BlockingIOError:
                    break
                try:
                    msg = json.loads(data.decode())
                except ValueError:
                    continue
                msg_count += 1
                last_msg = now
                mid = msg["id"]
                qx, qy = transform(H, msg["x"], msg["y"])
                if msg.get("size", 0) > 0:
                    ex, ey = transform(H, msg["x"] + msg["size"], msg["y"])
                    size = math.hypot(ex - qx, ey - qy)
                    rad = math.radians(msg["angle"])
                    ox, oy = transform(H, msg["x"] + math.cos(rad) * msg["size"],
                                       msg["y"] + math.sin(rad) * msg["size"])
                    orient = math.degrees(math.atan2(oy - qy, ox - qx)) % 90.0
                else:
                    size = float(args.radius)
                    orient = 0.0
                size = min(SIZE_MAX, max(SIZE_MIN, size))
                if mid in markers:
                    prev = markers[mid]["pos"]
                    sx = prev[0] * (1.0 - POS_EMA) + qx * POS_EMA
                    sy = prev[1] * (1.0 - POS_EMA) + qy * POS_EMA
                    ss = markers[mid]["size"] * (1.0 - SIZE_EMA) + size * SIZE_EMA
                else:
                    sx, sy = qx, qy
                    ss = size
                markers[mid] = {"pos": (sx, sy), "angle": msg["angle"],
                                "size": ss, "orient": orient,
                                "last_seen": now}

            for mid in list(markers):
                if now - markers[mid]["last_seen"] > args.timeout:
                    del markers[mid]

        inside_markers = {mid: m for mid, m in markers.items()
                          if inside_play_area(m["pos"])}
        m0 = inside_markers.get(BEAT_MARKER_ID)
        m1 = inside_markers.get(SOUND_MARKER_ID)
        sel = sound_index(m1["angle"]) if m1 is not None else 0
        if not args.test and m0 is not None:
            rpm = rpm_from_angle(m0["angle"])
            phase += (rpm / 60.0) * dt
            if phase >= 1.0:
                phase -= 1.0
                flash = 1.0
                if drumkit is not None:
                    drumkit.trigger(sel)
                elif kick is not None:
                    kick.play()
        else:
            phase = 0.0
        flash = max(0.0, flash - dt * 4.0)

        screen.fill((bg, bg, bg))

        if not args.test:
            draw_play_border(screen, bg, label_color)

        if args.test:
            t = now
            cx = args.width / 2 + 400 * np.cos(t * 0.8)
            cy = args.height / 2 + 300 * np.sin(t * 0.8)
            hue = (t * 30) % 360 / 360.0
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            color = (int(r * 255), int(g * 255), int(b * 255))
            pygame.draw.circle(screen, color, (int(cx), int(cy)), args.radius)
        else:
            for mid, m in inside_markers.items():
                age = now - m["last_seen"]
                fade = max(0.0, 1.0 - age / args.timeout)
                r, g, b = colorsys.hsv_to_rgb((m["angle"] % 360.0) / 360.0, 1.0, 1.0)
                rgb = (int(r * 255), int(g * 255), int(b * 255))
                draw_square_glow(screen, (int(m["pos"][0]), int(m["pos"][1])),
                                 rgb, m["size"], fade, m["orient"])
                if mid == SOUND_MARKER_ID:
                    text = f"id={mid} {VOICES[sound_index(m['angle'])]} {m['angle']:.0f}deg"
                else:
                    text = f"id={mid} {m['angle']:.0f}deg"
                label = font.render(text, True, label_color)
                label_x = int(m["pos"][0]) + int(m["size"] * SQUARE_OUTER / 2) + 8
                screen.blit(label, (label_x, int(m["pos"][1]) - 12))

        if not args.test and m0 is not None and m1 is not None:
            pygame.draw.line(screen, (120, 90, 200), (int(m1["pos"][0]), int(m1["pos"][1])),
                             (int(m0["pos"][0]), int(m0["pos"][1])), 2)

        if not args.test and m0 is not None:
            mx, my = m0["pos"]
            pygame.draw.line(screen, (40, 80, 160), (int(mx), int(my)),
                             (int(center[0]), int(center[1])), 2)
            px = mx + (center[0] - mx) * phase
            py = my + (center[1] - my) * phase
            draw_glow(screen, (int(px), int(py)), (120, 180, 255), 26, 0.9)

        draw_glow(screen, (int(center[0]), int(center[1])), CENTER_COLOR, 46, 0.5 + 0.5 * flash)

        if channel is not None:
            if inside_markers:
                m = max(inside_markers.values(), key=lambda x: x["last_seen"])
                freq = tone_freq(m["angle"])
                if abs(freq - cur_freq) > 8.0:
                    cur_freq = freq
                    channel.play(make_tone(freq), loops=-1)
            elif cur_freq:
                cur_freq = 0.0
                channel.stop()

        if not args.no_debug:
            pygame.draw.rect(screen, (60, 60, 60), (0, 0, args.width, args.height), 2)
            pygame.draw.line(screen, (60, 60, 60), (args.width // 2 - 20, args.height // 2), (args.width // 2 + 20, args.height // 2), 2)
            pygame.draw.line(screen, (60, 60, 60), (args.width // 2, args.height // 2 - 20), (args.width // 2, args.height // 2 + 20), 2)
            if args.test:
                status = f"TEST MODE (renderer OK)  {int(clock.get_fps())} fps"
            else:
                age = now - last_msg if last_msg else -1.0
                beat = ""
                if m0 is not None:
                    beat = f"  rpm: {rpm_from_angle(m0['angle']):.0f}  snd: {VOICES[sel]}"
                status = (f"markers: {len(inside_markers)}/{len(markers)} in play area  "
                          f"msgs: {msg_count}  "
                          f"last: {age:.1f}s ago  fps: {int(clock.get_fps())}{beat}")
            screen.blit(font.render(status, True, (0, 255, 0)), (16, 16))

        pygame.display.flip()
        frames += 1
        clock.tick(30)

    pygame.quit()
    if drumkit is not None:
        drumkit.shutdown()


if __name__ == "__main__":
    main()
