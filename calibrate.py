import argparse

import cv2
import numpy as np

import tracking

W, H = 1920, 1080
MARKER_SIZE = 200
MARGIN = 160
POSITIONS = {
    0: (MARGIN, MARGIN),
    1: (W - MARGIN, MARGIN),
    2: (MARGIN, H - MARGIN),
    3: (W - MARGIN, H - MARGIN),
}


def make_pattern(path):
    img = np.full((H, W), 255, np.uint8)
    dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, tracking.DICT_NAME))
    pad = MARKER_SIZE // 6
    for mid, (cx, cy) in POSITIONS.items():
        marker = cv2.aruco.generateImageMarker(dic, mid, MARKER_SIZE)
        size = MARKER_SIZE + 2 * pad
        block = np.full((size, size), 255, np.uint8)
        block[pad:pad + MARKER_SIZE, pad:pad + MARKER_SIZE] = marker
        x0 = cx - size // 2
        y0 = cy - size // 2
        img[y0:y0 + size, x0:x0 + size] = block
    cv2.imwrite(path, img)
    print(f"wrote {path}")


def capture(device):
    det = tracking.make_detector()

    cap = tracking.open_camera(device, 1280, 720)

    cam_pts = {}
    for _ in range(20):
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = tracking.preprocess(gray)
        corners, ids, _ = det.detectMarkers(gray)
        if ids is None:
            continue
        for i in range(len(ids)):
            mid = int(ids[i][0])
            if mid in POSITIONS:
                c = corners[i].reshape(4, 2)
                cam_pts.setdefault(mid, []).append(c.mean(axis=0))
    cap.release()

    if len(cam_pts) < 4:
        print(f"found {len(cam_pts)}/4 markers: {sorted(cam_pts)}")
        return None, None, None

    ids_sorted = sorted(cam_pts)
    cam = np.float32([np.mean(cam_pts[m], axis=0) for m in ids_sorted])
    proj = np.float32([POSITIONS[m] for m in ids_sorted])
    return cam, proj, ids_sorted


def main():
    p = argparse.ArgumentParser(description="Camera-projector calibration")
    p.add_argument("--pattern", action="store_true", help="generate calibration pattern PNG")
    p.add_argument("--device", default=tracking.DEFAULT_DEVICE)
    p.add_argument("--out", default="homography.npy")
    args = p.parse_args()

    if args.pattern:
        make_pattern("calib_pattern.png")
        return

    cam, proj, ids = capture(args.device)
    if cam is None:
        return

    homography, _ = cv2.findHomography(cam, proj, cv2.RANSAC)
    np.save(args.out, homography)

    reproj = cv2.perspectiveTransform(cam.reshape(-1, 1, 2), homography).reshape(-1, 2)
    err = np.linalg.norm(reproj - proj, axis=1)
    print(f"saved {args.out}")
    print(f"ids {ids}")
    print(f"reprojection errors (px): {[round(float(e), 1) for e in err]}")


if __name__ == "__main__":
    main()
