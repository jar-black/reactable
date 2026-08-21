import argparse
import colorsys
import json
import socket
import time

import numpy as np
import pygame

try:
    from drums import DrumKit, VOICES
except Exception:
    DrumKit = None
    VOICES = ("kick", "snare", "hihat", "clap", "tom")

RPM_MIN = 30.0
RPM_MAX = 240.0
BEAT_MARKER_ID = 0
SOUND_MARKER_ID = 1
CENTER_COLOR = (60, 130, 255)


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


def make_kick(rate=44100, dur=0.25):
    t = np.linspace(0.0, dur, int(rate * dur), endpoint=False)
    freq = np.linspace(150.0, 50.0, t.size)
    env = np.exp(-t * 18.0)
    samples = (np.sin(2 * np.pi * freq * t) * env * 0.5 * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(samples)


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


def main():
    p = argparse.ArgumentParser(description="Projector renderer (UDP in, circles out)")
    p.add_argument("--port", type=int, default=7000)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--radius", type=int, default=70)
    p.add_argument("--homography", default="homography.npy")
    p.add_argument("--fade-frames", type=int, default=10)
    p.add_argument("--test", action="store_true", help="animate a circle, ignore UDP")
    p.add_argument("--audio", action="store_true", help="play a tone pitched by marker angle")
    p.add_argument("--no-debug", action="store_true", help="hide status overlay")
    args = p.parse_args()

    try:
        H = np.load(args.homography)
        print(f"loaded {args.homography}")
    except FileNotFoundError:
        print("no homography file; using identity mapping")
        H = np.eye(3)

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
            seen_now = set()
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
                markers[mid] = {"pos": (qx, qy), "angle": msg["angle"], "frames_since": 0}
                seen_now.add(mid)

            for mid in list(markers):
                if mid not in seen_now:
                    markers[mid]["frames_since"] += 1
                    if markers[mid]["frames_since"] > args.fade_frames:
                        del markers[mid]

        m0 = markers.get(BEAT_MARKER_ID)
        m1 = markers.get(SOUND_MARKER_ID)
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

        screen.fill((0, 0, 0))

        if args.test:
            t = now
            cx = args.width / 2 + 400 * np.cos(t * 0.8)
            cy = args.height / 2 + 300 * np.sin(t * 0.8)
            hue = (t * 30) % 360 / 360.0
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            color = (int(r * 255), int(g * 255), int(b * 255))
            pygame.draw.circle(screen, color, (int(cx), int(cy)), args.radius)
        else:
            for mid, m in markers.items():
                fade = max(0.0, 1.0 - m["frames_since"] / args.fade_frames)
                r, g, b = colorsys.hsv_to_rgb((m["angle"] % 360.0) / 360.0, 1.0, 1.0)
                color = (int(r * 255 * fade), int(g * 255 * fade), int(b * 255 * fade))
                pygame.draw.circle(screen, color, (int(m["pos"][0]), int(m["pos"][1])), args.radius)
                if mid == SOUND_MARKER_ID:
                    text = f"id={mid} {VOICES[sound_index(m['angle'])]} {m['angle']:.0f}deg"
                else:
                    text = f"id={mid} {m['angle']:.0f}deg"
                label = font.render(text, True, (255, 255, 255))
                screen.blit(label, (int(m["pos"][0]) + args.radius + 8, int(m["pos"][1]) - 12))

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
            if markers:
                m = min(markers.values(), key=lambda x: x["frames_since"])
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
                status = (f"markers: {len(markers)}  msgs: {msg_count}  "
                          f"last: {age:.1f}s ago  fps: {int(clock.get_fps())}{beat}")
            screen.blit(font.render(status, True, (0, 255, 0)), (16, 16))

        pygame.display.flip()
        frames += 1
        clock.tick(60)

    pygame.quit()
    if drumkit is not None:
        drumkit.shutdown()


if __name__ == "__main__":
    main()
