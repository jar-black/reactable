import argparse
import math
import sys

import cv2

import tracking


def main():
    p = argparse.ArgumentParser(description="Camera + ArUco overlay -> raw BGR on stdout")
    p.add_argument("--device", default=tracking.DEFAULT_DEVICE)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    args = p.parse_args()

    cap = tracking.open_camera(args.device, args.width, args.height)

    detector = tracking.make_detector()

    out = sys.stdout.buffer
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = tracking.preprocess(gray)
        corners, ids, _rejected = detector.detectMarkers(gray)

        if ids is not None:
            cv2.aruco.drawDetectedMarkers(frame, corners, ids)
            for i in range(len(ids)):
                c = corners[i].reshape(4, 2)
                cx, cy = c.mean(axis=0)
                cv2.circle(frame, (int(cx), int(cy)), 6, (0, 0, 255), -1)
                dx = c[1][0] - c[0][0]
                dy = c[1][1] - c[0][1]
                angle = math.degrees(math.atan2(dy, dx))
                if angle < 0:
                    angle += 360.0
                cv2.putText(frame, f"id={int(ids[i][0])} {angle:.0f}deg",
                            (int(cx) + 12, int(cy)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.8, (0, 255, 0), 2)

        try:
            out.write(frame.tobytes())
            out.flush()
        except BrokenPipeError:
            break

    cap.release()


if __name__ == "__main__":
    main()
