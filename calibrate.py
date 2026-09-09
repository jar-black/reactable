import argparse
import time

import cv2
import numpy as np
import pygame

import layout
import tracking

AUTO_SETTLE_SECONDS = 6.0
AUTO_ATTEMPTS = 3


def make_pattern(path):
    img = np.full((layout.PROJ_H, layout.PROJ_W), 255, np.uint8)
    dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, tracking.DICT_NAME))
    pad = layout.MARKER_SIZE // 6
    for mid, (cx, cy) in layout.POSITIONS.items():
        marker = cv2.aruco.generateImageMarker(dic, mid, layout.MARKER_SIZE)
        size = layout.MARKER_SIZE + 2 * pad
        block = np.full((size, size), 255, np.uint8)
        block[pad:pad + layout.MARKER_SIZE, pad:pad + layout.MARKER_SIZE] = marker
        x0 = cx - size // 2
        y0 = cy - size // 2
        img[y0:y0 + size, x0:x0 + size] = block
    cv2.imwrite(path, img)
    print(f"wrote {path} ({len(layout.POSITIONS)} markers)")


def capture(device):
    det = tracking.make_detector()

    cap = tracking.open_camera(device, layout.CALIB_W, layout.CALIB_H)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale_x = layout.CALIB_W / actual_w
    scale_y = layout.CALIB_H / actual_h

    cam_pts = {}
    for _ in range(30):
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for processed in (tracking.preprocess(gray), gray):
            corners, ids, _ = det.detectMarkers(processed)
            if ids is None:
                continue
            for i in range(len(ids)):
                mid = int(ids[i][0])
                if mid in layout.POSITIONS:
                    c = corners[i].reshape(4, 2)
                    c[:, 0] *= scale_x
                    c[:, 1] *= scale_y
                    cam_pts.setdefault(mid, []).append(c.mean(axis=0))
    cap.release()

    if len(cam_pts) < 4:
        print(f"found {len(cam_pts)}/{len(layout.POSITIONS)} grid markers: {sorted(cam_pts)}")
        return None, None, None

    ids_sorted = sorted(cam_pts)
    cam = np.float32([np.mean(cam_pts[m], axis=0) for m in ids_sorted])
    proj = np.float32([layout.POSITIONS[m] for m in ids_sorted])

    span_x = float(proj[:, 0].max() - proj[:, 0].min())
    span_y = float(proj[:, 1].max() - proj[:, 1].min())
    hull = cv2.convexHull(proj.reshape(-1, 1, 2))
    hull_area = float(cv2.contourArea(hull))
    min_hull = layout.MIN_HULL_AREA * layout.PROJ_W * layout.PROJ_H
    if hull_area < min_hull:
        print(f"detected markers are collinear or too clustered "
              f"(hull area {hull_area:.0f} px2, need {min_hull:.0f}); retrying")
        return None, None, None
    if (span_x < layout.MIN_MARKER_SPAN * layout.PROJ_W and
            span_y < layout.MIN_MARKER_SPAN * layout.PROJ_H):
        print(f"detected markers too clustered (span {span_x:.0f}x{span_y:.0f} px); retrying")
        return None, None, None

    return cam, proj, ids_sorted


def transform_points(H, pts):
    pts = np.float32(pts).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)


def clip_poly_to_rect(poly, w, h):
    def intersect_x(a, b, x):
        t = (x - a[0]) / (b[0] - a[0])
        return (x, a[1] + t * (b[1] - a[1]))

    def intersect_y(a, b, y):
        t = (y - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), y)

    poly = [(float(x), float(y)) for x, y in poly]
    edges = [
        (lambda p: p[0] >= 0, lambda a, b: intersect_x(a, b, 0)),
        (lambda p: p[0] <= w, lambda a, b: intersect_x(a, b, w)),
        (lambda p: p[1] >= 0, lambda a, b: intersect_y(a, b, 0)),
        (lambda p: p[1] <= h, lambda a, b: intersect_y(a, b, h)),
    ]
    for keep, cross in edges:
        new = []
        for i in range(len(poly)):
            a, b = poly[i - 1], poly[i]
            a_in, b_in = keep(a), keep(b)
            if b_in:
                if not a_in:
                    new.append(cross(a, b))
                new.append(b)
            elif a_in:
                new.append(cross(a, b))
        poly = new
        if not poly:
            break
    return poly


def point_in_convex(p, poly):
    signs = set()
    for i in range(len(poly)):
        a, b = poly[i - 1], poly[i]
        cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        if cross > 0:
            signs.add(1)
        elif cross < 0:
            signs.add(-1)
    return len(signs) <= 1


def largest_rect_in_poly(poly):
    xs = sorted({p[0] for p in poly})
    ys = sorted({p[1] for p in poly})
    best = None
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            for k in range(len(ys)):
                for l in range(k + 1, len(ys)):
                    x0, x1 = xs[i], xs[j]
                    y0, y1 = ys[k], ys[l]
                    area = (x1 - x0) * (y1 - y0)
                    if best is not None and area <= best[4]:
                        continue
                    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
                    if all(point_in_convex(c, poly) for c in corners):
                        best = (x0, y0, x1, y1, area)
    if best is None:
        return None
    return best[:4]


def compute_play_rect(H):
    m = layout.PLAY_MARGIN_CAM
    inset = [(m, m), (layout.CALIB_W - m, m),
             (layout.CALIB_W - m, layout.CALIB_H - m), (m, layout.CALIB_H - m)]
    q = transform_points(H, inset)
    poly = clip_poly_to_rect(q, layout.PROJ_W, layout.PROJ_H)
    if len(poly) < 4:
        print("visible play region is empty (camera sees nothing of the projection?)")
        return None
    rect = largest_rect_in_poly(poly)
    if rect is None:
        print("could not fit a play rectangle in the visible region")
        return None
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    if w < layout.MIN_PLAY_SIZE or h < layout.MIN_PLAY_SIZE:
        print(f"play area too small: {w:.0f}x{h:.0f} px")
        return None
    return tuple(rect)


def compute_and_save(cam, proj, ids, out, playout):
    homography, _ = cv2.findHomography(cam, proj, cv2.RANSAC)
    if homography is None:
        print("findHomography failed")
        return False

    reproj = cv2.perspectiveTransform(cam.reshape(-1, 1, 2), homography).reshape(-1, 2)
    err = np.linalg.norm(reproj - proj, axis=1)

    rect = compute_play_rect(homography)
    if rect is None:
        return False

    np.save(out, homography)
    np.save(playout, np.array(rect))
    print(f"saved {out} (ids {ids})")
    print(f"reprojection errors (px): {[round(float(e), 1) for e in err]}")
    print(f"saved {playout} play area {tuple(round(v, 1) for v in rect)}")
    return True


def auto_calibrate(device, out, playout):
    pattern_path = "calib_pattern.png"
    make_pattern(pattern_path)

    pygame.init()
    try:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        pattern = pygame.image.load(pattern_path).convert()
        pattern = pygame.transform.smoothscale(pattern, screen.get_size())
        screen.fill((0, 0, 0))
        screen.blit(pattern, (0, 0))
        pygame.display.flip()
        print(f"projecting {pattern_path} fullscreen; "
              f"settling {AUTO_SETTLE_SECONDS:.0f}s for exposure...")
        time.sleep(AUTO_SETTLE_SECONDS)

        for attempt in range(1, AUTO_ATTEMPTS + 1):
            pygame.event.pump()
            print(f"capture attempt {attempt}/{AUTO_ATTEMPTS}")
            cam, proj, ids = capture(device)
            if cam is not None and compute_and_save(cam, proj, ids, out, playout):
                return 0
            if attempt < AUTO_ATTEMPTS:
                time.sleep(1.0)

        print(f"auto-calibration failed: need at least 4 visible grid markers "
              f"(ids {layout.GRID_IDS_START}..{layout.GRID_IDS_START + len(layout.POSITIONS) - 1})")
        return 1
    finally:
        pygame.quit()


def main():
    p = argparse.ArgumentParser(description="Camera-projector calibration")
    p.add_argument("--pattern", action="store_true", help="generate calibration pattern PNG")
    p.add_argument("--auto", action="store_true",
                   help="project the pattern fullscreen, detect it, and save the homography")
    p.add_argument("--device", default=tracking.DEFAULT_DEVICE)
    p.add_argument("--out", default="homography.npy")
    p.add_argument("--playarea", default="playarea.npy")
    args = p.parse_args()

    if args.pattern:
        make_pattern("calib_pattern.png")
        return

    if args.auto:
        raise SystemExit(auto_calibrate(args.device, args.out, args.playarea))

    cam, proj, ids = capture(args.device)
    if cam is None:
        raise SystemExit(1)

    if not compute_and_save(cam, proj, ids, args.out, args.playarea):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
