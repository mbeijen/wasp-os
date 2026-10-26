#!/usr/bin/env python3

# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michiel W. Beijen

"""Encode palette images of up to 16 colours as 4-bit RLE.

The format, decoded by apps/guido.py:

    width, height, scale, number of colours
    the palette, two bytes per colour (RGB565, big endian)
    runs of one byte each: the colour index in the high nibble and the
    run length minus one in the low nibble; a low nibble of 15 means the
    run is 16 plus the next byte. Runs carry on into the next row.

The image is drawn scale times larger.
"""

import argparse
import os.path
from PIL import Image

def encode(im, scale):
    if im.mode != 'P':
        im = im.quantize(16)
    colours = len(im.getcolors(16) or ())
    assert 0 < colours <= 16, 'at most 16 colours'
    assert im.width * scale <= 240 and im.height * scale <= 240

    # Renumber the colours actually used, in order of first use
    pixels = list(im.getdata())
    used = list(dict.fromkeys(pixels))
    index = {p: i for i, p in enumerate(used)}
    pal = im.getpalette()

    out = bytearray((im.width, im.height, scale, len(used)))
    for p in used:
        r, g, b = pal[3*p:3*p+3]
        rgb565 = ((r & 0xf8) << 8) | ((g & 0xfc) << 3) | (b >> 3)
        out += rgb565.to_bytes(2, 'big')

    i = 0
    while i < len(pixels):
        j = i + 1
        while j < len(pixels) and pixels[j] == pixels[i] and j - i < 271:
            j += 1
        rl = j - i
        if rl <= 15:
            out.append(index[pixels[i]] << 4 | (rl - 1))
        else:
            out.append(index[pixels[i]] << 4 | 15)
            out.append(rl - 16)
        i = j
    return bytes(out)

def render_py(data, fname):
    name = os.path.splitext(os.path.basename(fname))[0]
    print(f'# 4-bit RLE, {data[0]}x{data[1]} drawn {data[2]}x, '
          f'generated from {fname}, {len(data)} bytes')
    print(f'{name} = (')
    for i in range(0, len(data), 16):
        print(f'    {data[i:i+16]}')
    print(')')

parser = argparse.ArgumentParser(description='4-bit RLE encoder tool.')
parser.add_argument('files', nargs='+', help='files to be encoded')
parser.add_argument('--scale', default=1, type=int,
                    help='Draw the image this many times larger')
args = parser.parse_args()

for fname in args.files:
    render_py(encode(Image.open(fname), args.scale), fname)
