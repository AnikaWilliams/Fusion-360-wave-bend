"""Generate the Wave Bend toolbar icons (16/32/64 px PNG) from the REAL cell
geometry in WaveBend/lib/geometry.py — the icon is the actual pattern.

Pure Python (struct + zlib PNG writer, no PIL). Run:  py tools/make_icons.py
Overwrites WaveBend/commands/waveBendCmd/resources/{16x16,32x32,64x64}.png
"""
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "WaveBend", "lib"))
import geometry as G  # noqa: E402

OUT_DIR = os.path.join(REPO, "WaveBend", "commands", "waveBendCmd", "resources")
BLUE = (46, 132, 216)          # Fusion-ish command blue
LINE = (140, 148, 156)         # muted bend-line gray


def png_bytes(size, rgba_rows):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(row) for row in rgba_rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def polygons():
    """Two nested wave cells (smile + frown) sampled to polygons, in cell coords."""
    slot, gap, fil = 1.651, 0.5, 0.16   # exaggerated gap so slots read at 16 px
    pitch = 1.9
    polys = []
    for i, orient in enumerate((+1, -1)):
        cell = G.build_wave_cell(slot, gap, fil, 40.0, 0.55, orient, cx=i * pitch, cy=0.0)
        pts = G.sample_profile(cell, n=6)
        polys.append([(p.x, p.y) for p in pts])
    return polys


def inside(px, py, poly):
    """Even-odd point-in-polygon."""
    n = len(poly)
    hit = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py):
            x_at = xi + (py - yi) / (yj - yi) * (xj - xi)
            if px < x_at:
                hit = not hit
        j = i
    return hit


def render(size):
    polys = polygons()
    xs = [x for poly in polys for x, _ in poly]
    ys = [y for poly in polys for _, y in poly]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    span = max(max(xs) - min(xs), (max(ys) - min(ys)) * 1.4) * 1.12
    scale = size / span
    ss = 3                                             # supersampling factor
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            cover_slot = 0
            cover_line = 0
            for sy in range(ss):
                for sx in range(ss):
                    wx = cx + ((px + (sx + 0.5) / ss) - size / 2.0) / scale
                    wy = cy - ((py + (sy + 0.5) / ss) - size / 2.0) / scale
                    if any(inside(wx, wy, poly) for poly in polys):
                        cover_slot += 1
                    elif abs(wy - cy) < 0.5 / scale:   # 1px bend line through the middle
                        cover_line += 1
            a_slot = cover_slot / (ss * ss)
            a_line = cover_line / (ss * ss)
            if a_slot > 0:
                r, g, b = BLUE
                row += [r, g, b, int(255 * min(1.0, a_slot))]
            elif a_line > 0:
                r, g, b = LINE
                row += [r, g, b, int(140 * a_line)]
            else:
                row += [0, 0, 0, 0]
        rows.append(row)
    return png_bytes(size, rows)


def main():
    for size in (16, 32, 64):
        data = render(size)
        path = os.path.join(OUT_DIR, f"{size}x{size}.png")
        with open(path, "wb") as fh:
            fh.write(data)
        print(f"wrote {path} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
