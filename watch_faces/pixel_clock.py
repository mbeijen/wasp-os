# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michiel W. Beijen

"""Pixel clock with epoch counter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shows a time (as HH:MM), the date (as YYYY-MM-DD) and the Unix epoch, all
in a blocky 8-bit style, together with a battery meter.

The watch only keeps local time, so the epoch assumes Dutch time: UTC+1,
and UTC+2 from the last Sunday of March to the last Sunday of October.

.. figure:: res/screenshots/PixelClockApp.png
    :width: 179
"""

import wasp

# 6x7 glyphs, one byte per row, the leftmost pixel in bit 5
CHARS = '0123456789-'
GLYPHS = (
    b'\x1e\x33\x33\x33\x33\x33\x1e'  # 0
    b'\x0c\x1c\x3c\x0c\x0c\x0c\x3f'  # 1
    b'\x1e\x33\x03\x06\x0c\x18\x3f'  # 2
    b'\x1e\x33\x03\x0e\x03\x33\x1e'  # 3
    b'\x06\x0e\x1e\x36\x3f\x06\x06'  # 4
    b'\x3f\x30\x3e\x03\x03\x33\x1e'  # 5
    b'\x0e\x18\x30\x3e\x33\x33\x1e'  # 6
    b'\x3f\x03\x06\x0c\x18\x18\x18'  # 7
    b'\x1e\x33\x33\x1e\x33\x33\x1e'  # 8
    b'\x1e\x33\x33\x1f\x03\x06\x1c'  # 9
    b'\x00\x00\x00\x1e\x00\x00\x00'  # -
)

def _days(y, m, d):
    """Days since 1970-01-01 (Howard Hinnant's days_from_civil)."""
    if m <= 2:
        y -= 1
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m - 3 if m > 2 else m + 9) + 2) // 5 + d - 1
    return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468

def _last_sunday(y, m):
    """Day of the month of the last Sunday of March or October."""
    # 1970-01-01 was a Thursday, so (days + 3) % 7 is 0 on a Monday
    return 31 - (_days(y, m, 31) + 4) % 7

def utc_offset(now):
    """Hours Dutch local time is ahead of UTC at local time now."""
    m = now[1]
    if m < 3 or m > 10:
        return 1
    if 3 < m < 10:
        return 2
    sunday = _last_sunday(now[0], m)
    # Summer time starts at 02:00 and ends at 03:00 local time
    if m == 3:
        return 2 if (now[2], now[3]) >= (sunday, 2) else 1
    return 2 if (now[2], now[3]) < (sunday, 3) else 1

def epoch(now):
    """Unix time from a local time tuple."""
    return ((_days(now[0], now[1], now[2]) * 24 + now[3] - utc_offset(now))
            * 60 + now[4]) * 60 + now[5]

class PixelClockApp():
    """Pixel clock application."""
    NAME = 'Pixel'

    def foreground(self):
        """Activate the application."""
        wasp.system.bar.clock = False
        self._draw(True)
        wasp.system.request_tick(1000)

    def sleep(self):
        """Prepare to enter the low power mode."""
        return True

    def wake(self):
        """Return from low power mode."""
        self._draw()

    def tick(self, ticks):
        """Periodic callback to update the display."""
        self._draw()

    def preview(self):
        """Provide a preview for the watch face selection."""
        wasp.system.bar.clock = False
        self._draw(True)

    def _glyph(self, c, x, y, scale, fg):
        """Draw one character, background included, to avoid flicker."""
        draw = wasp.watch.drawable
        i = CHARS.find(c) * 7
        for row in range(7):
            bits = GLYPHS[i + row]
            col = 0
            while col < 6:
                on = (bits >> (5 - col)) & 1
                run = 1
                while col + run < 6 and (bits >> (5 - col - run)) & 1 == on:
                    run += 1
                draw.fill(fg if on else 0, x + col * scale, y + row * scale,
                          run * scale, scale)
                col += run

    def _text(self, s, old, x, y, scale, fg):
        """Draw the characters of s that differ from old."""
        for i in range(len(s)):
            if not old or s[i] != old[i]:
                self._glyph(s[i], x + i * 7 * scale, y, scale, fg)

    def _draw(self, redraw=False):
        """Draw or lazily update the display."""
        draw = wasp.watch.drawable
        hi = wasp.system.theme('bright')
        lo = wasp.system.theme('mid')
        dim = draw.darken(lo, 3)

        if redraw:
            draw.fill()
            wasp.system.bar.draw()
            # The colon, two blocks as wide as a stroke, centred between
            # the hours and the minutes
            draw.fill(lo, 113, 67, 14, 14)
            draw.fill(lo, 113, 88, 14, 14)
            self._hhmm = self._date = self._epoch = None
        else:
            wasp.system.bar.update()

        now = wasp.watch.rtc.get_localtime()

        hhmm = '{:02d}{:02d}'.format(now[3], now[4])
        if hhmm != self._hhmm:
            self._text(hhmm[:2], self._hhmm and self._hhmm[:2],
                       8, 60, 7, hi)
            self._text(hhmm[2:], self._hhmm and self._hhmm[2:],
                       141, 60, 7, hi)
            self._hhmm = hhmm

        date = '{}-{:02d}-{:02d}'.format(now[0], now[1], now[2])
        if date != self._date:
            self._text(date, self._date, 16, 135, 3, dim)
            self._date = date

        e = str(epoch(now))
        if self._epoch and len(e) != len(self._epoch):
            self._epoch = None
        self._text(e, self._epoch, 16, 180, 3, dim)
        self._epoch = e
