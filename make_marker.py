import argparse

import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser(description="Generate printable ArUco markers")
    p.add_argument("ids", nargs="+", type=int)
    p.add_argument("--dictionary", default="DICT_4X4_50")
    p.add_argument("--side", type=int, default=600, help="marker side in px (incl. border)")
    p.add_argument("--cells", type=int, default=1, help="quiet-zone width in cells")
    p.add_argument("--invert", action="store_true", help="white symbols on black void")
    p.add_argument("--out", default="marker_{id}.png")
    args = p.parse_args()

    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, args.dictionary))
    border = args.side * args.cells // 6

    for mid in args.ids:
        marker = cv2.aruco.generateImageMarker(dictionary, mid, args.side)
        if args.invert:
            marker = 255 - marker
        size = args.side + 2 * border
        canvas = np.full((size, size), 0 if args.invert else 255, np.uint8)
        canvas[border:border + args.side, border:border + args.side] = marker
        path = args.out.format(id=mid)
        cv2.imwrite(path, canvas)
        print(f"wrote {path} ({size}x{size}px)")


if __name__ == "__main__":
    main()
