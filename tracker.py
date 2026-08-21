import argparse
import json
import math
import socket
import time

import cv2

import tracking


def main():
    p = argparse.ArgumentParser(description="ArUco marker tracker (UDP/JSON out)")
    p.add_argument("--device", default=tracking.DEFAULT_DEVICE, help="camera device path or index")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7000)
    p.add_argument("--show", action="store_true", help="show annotated preview window")
    p.add_argument("--raw", action="store_true", help="skip CLAHE preprocessing")
    args = p.parse_args()

    cap = tracking.open_camera(args.device, args.width, args.height, args.fps)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"camera {args.device}: {actual_w}x{actual_h}")

    detector = tracking.make_detector()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    frames = 0
    seen_frames = 0
    last_markers = []
    t0 = time.time()
    last_log = t0
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
        if count > 0:
            seen_frames += 1

        last_markers = []
        for i in range(count):
            c = corners[i].reshape(4, 2)
            cx, cy = c.mean(axis=0)
            dx = c[1][0] - c[0][0]
            dy = c[1][1] - c[0][1]
            angle = math.degrees(math.atan2(dy, dx))
            if angle < 0:
                angle += 360.0
            last_markers.append(f"id{int(ids[i][0])}@({cx:.0f},{cy:.0f}) {angle:.0f}deg")
            msg = {"id": int(ids[i][0]), "x": float(cx), "y": float(cy), "angle": float(angle)}
            sock.sendto(json.dumps(msg).encode(), (args.host, args.port))

        now = time.time()
        if now - last_log >= 0.5:
            rate = seen_frames / frames
            fps = frames / (now - t0)
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
