"""Generate the WaveBend toolbar icons (16/32/64 px PNG) from the REAL cell
geometry in WaveBend/lib/geometry.py — the icon is the actual pattern.

Two icon sets:
  - Wave Bend command: two nested wave cells on the bend line
  - Export DXF command: one wave cell over a download-style arrow

Pure Python (struct + zlib PNG writer, no PIL). Run:  py tools/make_icons.py
Overwrites {waveBendCmd,dxfExportCmd}/resources/{16x16,32x32,64x64}.png
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
OUT_DIR_DXF = os.path.join(REPO, "WaveBend", "commands", "dxfExportCmd", "resources")
BLUE = (46, 132, 216)          # Fusion-ish command blue
GREEN = (72, 160, 84)          # export-arrow green
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


def dxf_shapes():
    """One wave cell above a chunky download arrow (the export motif)."""
    slot, gap, fil = 1.651, 0.55, 0.17
    cell = G.build_wave_cell(slot, gap, fil, 40.0, 0.55, +1, cx=0.0, cy=0.0)
    wave = [(p.x, p.y + 0.95) for p in G.sample_profile(cell, n=6)]
    s, h = 0.30, 0.72                                  # shaft half-width, head half-width
    arrow = [(-s, 0.45), (s, 0.45), (s, -0.35), (h, -0.35),
             (0.0, -1.25), (-h, -0.35), (-s, -0.35)]
    return [(wave, BLUE), (arrow, GREEN)]


def render(size, shapes, bend_line_y=None):
    """shapes: [(polygon, rgb)]; optional 1px bend line at world y."""
    xs = [x for poly, _ in shapes for x, _y in poly]
    ys = [y for poly, _ in shapes for _x, y in poly]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    span = max(max(xs) - min(xs), (max(ys) - min(ys)) * 1.4) * 1.12
    scale = size / span
    ss = 3                                             # supersampling factor
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            cover = {}
            cover_line = 0
            for sy in range(ss):
                for sx in range(ss):
                    wx = cx + ((px + (sx + 0.5) / ss) - size / 2.0) / scale
                    wy = cy - ((py + (sy + 0.5) / ss) - size / 2.0) / scale
                    hit = None
                    for poly, color in shapes:
                        if inside(wx, wy, poly):
                            hit = color
                            break
                    if hit is not None:
                        cover[hit] = cover.get(hit, 0) + 1
                    elif bend_line_y is not None and abs(wy - bend_line_y) < 0.5 / scale:
                        cover_line += 1
            if cover:
                color = max(cover, key=cover.get)
                a = sum(cover.values()) / (ss * ss)
                r, g, b = color
                row += [r, g, b, int(255 * min(1.0, a))]
            elif cover_line > 0:
                r, g, b = LINE
                row += [r, g, b, int(140 * cover_line / (ss * ss))]
            else:
                row += [0, 0, 0, 0]
        rows.append(row)
    return png_bytes(size, rows)


def main():
    wave_shapes = [(poly, BLUE) for poly in polygons()]
    icon_sets = (
        (OUT_DIR, wave_shapes, 0.0),
        (OUT_DIR_DXF, dxf_shapes(), None),
    )
    for out_dir, shapes, line_y in icon_sets:
        os.makedirs(out_dir, exist_ok=True)
        for size in (16, 32, 64):
            data = render(size, shapes, bend_line_y=line_y)
            path = os.path.join(out_dir, f"{size}x{size}.png")
            with open(path, "wb") as fh:
                fh.write(data)
            print(f"wrote {path} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
