#!/usr/bin/env python3
"""
make_icons.py — PWA のアイコンを生成する。

朱地に紙色の折れ線。maskable でも切り落とされないよう、図は中央60%に収めてある。
Pillow を足したくないので、zlib と struct だけで PNG を書く。

    python make_icons.py        # docs/icon-192.png と docs/icon-512.png を作り直す
"""

import struct
import zlib
from pathlib import Path

SHU = (0xB2, 0x3C, 0x26)     # 地
PAPER = (0xF4, 0xF1, 0xE8)   # 図

# 単位座標(0〜1)。右肩上がりの折れ線と、その下の基線。
LINE = [(0.26, 0.63), (0.40, 0.50), (0.52, 0.57), (0.64, 0.34), (0.75, 0.27)]
BASE = [(0.24, 0.72), (0.76, 0.72)]


def _dist_to_seg(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
    dx, dy = wx - t * vx, wy - t * vy
    return (dx * dx + dy * dy) ** 0.5


def render(size: int):
    segs = [(LINE[i][0] * size, LINE[i][1] * size, LINE[i + 1][0] * size, LINE[i + 1][1] * size)
            for i in range(len(LINE) - 1)]
    segs += [(BASE[0][0] * size, BASE[0][1] * size, BASE[1][0] * size, BASE[1][1] * size)]

    half_line = size * 0.030
    half_base = size * 0.007
    cap = (LINE[-1][0] * size, LINE[-1][1] * size)
    cap_r = size * 0.055

    # 図が乗りうる範囲だけ走査する
    y0, y1 = int(size * 0.18), int(size * 0.82)
    x0, x1 = int(size * 0.16), int(size * 0.86)

    rows = []
    for y in range(size):
        row = [SHU] * size
        if y0 <= y <= y1:
            py = y + 0.5
            for x in range(x0, x1 + 1):
                px = x + 0.5
                cov = 0.0
                for i, (ax, ay, bx, by) in enumerate(segs):
                    hw = half_base if i == len(segs) - 1 else half_line
                    d = _dist_to_seg(px, py, ax, ay, bx, by)
                    cov = max(cov, min(1.0, max(0.0, hw + 0.5 - d)))
                    if cov >= 1.0:
                        break
                if cov < 1.0:
                    d = ((px - cap[0]) ** 2 + (py - cap[1]) ** 2) ** 0.5
                    cov = max(cov, min(1.0, max(0.0, cap_r + 0.5 - d)))
                if cov > 0:
                    row[x] = tuple(round(SHU[c] + (PAPER[c] - SHU[c]) * cov) for c in range(3))
        rows.append(row)
    return rows


def write_png(path: Path, rows):
    size = len(rows)
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in rows)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)   # 8bit RGB
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    out = Path("docs")
    out.mkdir(exist_ok=True)
    for size in (192, 512):
        p = out / f"icon-{size}.png"
        write_png(p, render(size))
        print(f"{p}  {p.stat().st_size:,} bytes")
