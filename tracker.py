import argparse
from collections import deque
import json
import math
import socket
import time

import cv2

import layout
import tracking

ANGLE_HISTORY = 8
CALIB_WIDTH = layout.CALIB_W
CALIB_HEIGHT = layout.CALIB_H


def median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def smooth_angle(hist):
    rads = [math.radians(a) for a in hist]
    sa = median([math.sin(r) for r in rads])
    ca = median([math.cos(r) for r in rads])
    angle = math.degrees(math.atan2(sa, ca))
    if angle < 0:
        angle += 360.0
    return angle


def main():
    p = argparse.ArgumentParser(description="ArUco marker tracker (UDP/JSON out)")
    p.add_argument("--device", default=tracking.DEFAULT_DEVICE, help="camera device path or index")
    p.add_argument("--width", type=int, default=960)
    p.add_argument("--height", type=int, default=540)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7000)
    p.add_argument("--show", action="store_true", help="show annotated preview window")
    p.add_argument("--raw", action="store_true", help="skip CLAHE preprocessing")
    args = p.parse_args()

    cap = tracking.open_camera(args.device, args.width, args.height, args.fps)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale_x = CALIB_WIDTH / actual_w
    scale_y = CALIB_HEIGHT / actual_h
    print(f"camera {args.device}: {actual_w}x{actual_h} "
          f"(scaled to {CALIB_WIDTH}x{CALIB_HEIGHT} calibration coords)")

    detector = tracking.make_detector()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    angle_hist = {}
    hist_seen = {}

    frames = 0
    last_markers = []
    t0 = time.time()
    last_log = t0
    frame_win = deque()
    while True:
        ok, frame = cap.read()
        if not ok:
            print("read failed")
            break
        frames += 1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if not args.raw:
            gray = tracking.preprocess(gray)
        corners, ids, _rejected = detector.detectMarkers(gray)

        count = 0 if ids is None else len(ids)

        now = time.time()
        frame_win.append((now, count > 0))
        while frame_win and now - frame_win[0][0] > 2.0:
            frame_win.popleft()

        last_markers = []
        for i in range(count):
            mid = int(ids[i][0])
            c = corners[i].reshape(4, 2)
            cx, cy = c.mean(axis=0)
            dx = c[1][0] - c[0][0]
            dy = c[1][1] - c[0][1]
            angle = math.degrees(math.atan2(dy, dx))
            if angle < 0:
                angle += 360.0
            side = 0.0
            for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
                side += math.hypot(c[b][0] - c[a][0], c[b][1] - c[a][1])
            side /= 4.0
            if mid not in angle_hist:
                angle_hist[mid] = deque(maxlen=ANGLE_HISTORY)
            angle_hist[mid].append(angle)
            hist_seen[mid] = frames
            sangle = smooth_angle(angle_hist[mid])
            cxs = cx * scale_x
            cys = cy * scale_y
            csize = side * (scale_x + scale_y) / 2.0
            last_markers.append(f"id{mid}@({cxs:.0f},{cys:.0f}) {sangle:.0f}deg "
                                f"sz{csize:.0f}")
            msg = {"id": mid, "x": float(cxs), "y": float(cys),
                   "angle": float(sangle), "size": float(csize),
                   "frame": frames, "t": now}
            sock.sendto(json.dumps(msg).encode(), (args.host, args.port))

        for mid in list(angle_hist):
            if frames - hist_seen[mid] > ANGLE_HISTORY:
                del angle_hist[mid]
                del hist_seen[mid]

        if now - last_log >= 0.5:
            if len(frame_win) > 1:
                win_span = frame_win[-1][0] - frame_win[0][0]
                fps = (len(frame_win) - 1) / win_span if win_span > 0 else 0.0
            else:
                fps = 0.0
            rate = sum(1 for _, s in frame_win if s) / len(frame_win)
            seen = ", ".join(last_markers) if last_markers else "-"
            print(f"[{now - t0:5.1f}s] fps={fps:4.1f} rate={rate:6.1%} "
                  f"markers({count}): {seen}")
            last_log = now

        if args.show:
            out = cv2.aruco.drawDetectedMarkers(frame, corners, ids)
            cv2.imshow("tracker", out)
            if cv2.waitKey(1) & 0xFF == 27:
                break

    cap.release()


if __name__ == "__main__":
    main()
