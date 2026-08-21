import argparse
import math
import struct


def normal(v0, v1, v2):
    ax, ay, az = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
    bx, by, bz = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / length, ny / length, nz / length


def make_puck(path, diameter, height, segments):
    r = diameter / 2.0
    top = height
    tris = []

    def add(v0, v1, v2):
        tris.append((v0, v1, v2))

    top_ring = []
    bot_ring = []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        x = r * math.cos(a)
        y = r * math.sin(a)
        top_ring.append((x, y, top))
        bot_ring.append((x, y, 0.0))

    top_c = (0.0, 0.0, top)
    bot_c = (0.0, 0.0, 0.0)
    for i in range(segments):
        j = (i + 1) % segments
        add(top_c, top_ring[i], top_ring[j])
        add(bot_c, bot_ring[j], bot_ring[i])
        add(bot_ring[i], bot_ring[j], top_ring[i])
        add(top_ring[i], bot_ring[j], top_ring[j])

    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(tris)))
        for v0, v1, v2 in tris:
            f.write(struct.pack("<3f", *normal(v0, v1, v2)))
            for v in (v0, v1, v2):
                f.write(struct.pack("<3f", *v))
            f.write(struct.pack("<H", 0))

    print(f"wrote {path}: {len(tris)} triangles, d={diameter}mm h={height}mm")


def main():
    p = argparse.ArgumentParser(description="Generate a flat puck STL for a marker")
    p.add_argument("--diameter", type=float, default=60.0, help="mm")
    p.add_argument("--height", type=float, default=5.0, help="mm")
    p.add_argument("--segments", type=int, default=96)
    p.add_argument("--out", default="puck.stl")
    args = p.parse_args()
    make_puck(args.out, args.diameter, args.height, args.segments)


if __name__ == "__main__":
    main()
