# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2020 Daniel Thompson

"""Photoplethysmogram (PPG) Signal Processing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Algorithms and signal processing primatives that can be used to convert
raw PPG signals into something useful.

The heart rate comes from the frequency spectrum of the signal, as in
InfiniTime (src/components/heartrate/Ppg.cpp): every half second, the
last 64 samples are detrended, band-pass filtered, windowed and
transformed, and the heart rate is the one clear peak between 40 and 230
bpm. Readings with too much noise, a broad peak or more than one peak
are rejected, and the last 20 good readings are averaged. A rise in
ambient light means that the watch is not on the skin, and starts over.
"""

import array
import math
import micropython
import watch
from micropython import const

# Samples in each analysis: a power of two, for the FFT
_LENGTH = 64
# Spectra averaged, besides the newest
_SPECTRAL_AVG_MAX = 2
# Other peaks above this part of the highest one make a reading invalid
_PEAK_THRESHOLD = 0.6
# The widest valid peak at that threshold, in bins
_MAX_PEAK_WIDTH = 2.5
# How much the highest peak must stand above the mean of the spectrum
_SNR_THRESHOLD = 3.0
# The highest DC level, after filtering, of a valid reading
_DC_THRESHOLD = 0.5
# Ambient light this many times higher than at the last analysis resets
_ALS_FACTOR = 2
# Heart rates, in beats per minute
_ROI_MIN, _ROI_MAX = 30, 240
_HR_MIN, _HR_MAX = 40, 230
# Readings averaged for the heart rate shown
_AVERAGE = 20


# The heavy loops work in fixed point, with viper, which runs as fast as
# machine code: floating point in MicroPython puts every number on the
# heap, and took a quarter of a second for each analysis. Samples are
# scaled up by 2**_SCALE; coefficients have _Q fractional bits.
_SCALE = const(8)
_Q = const(12)
_ONE = const(4096)
_HALF = const(2048)
# Bigger steps between samples are movement, not a pulse (which moves
# the signal by tens): clip them, so that no product overflows 31 bits.
# Shifts round to nearest, so that no DC level builds up.
_MAX_STEP = const(511)


# Tables for 64 samples, as little-endian 32-bit ints in fixed point.
# They stay in flash when frozen into the firmware. Made with:
#   [int(4096 * (0.5 - 0.5 * math.cos(2 * math.pi * i / 63))) for i in range(64)]
#   [int(4096 * math.cos(-2 * math.pi * k / 64)) for k in range(32)], and sin
# numpy.hanning(64)
_WINDOW = (
    b'\x00\x00\x00\x00\x0a\x00\x00\x00\x28\x00\x00\x00\x5a\x00\x00\x00'
    b'\xa0\x00\x00\x00\xf9\x00\x00\x00\x63\x01\x00\x00\xdf\x01\x00\x00'
    b'\x6a\x02\x00\x00\x03\x03\x00\x00\xa8\x03\x00\x00\x59\x04\x00\x00'
    b'\x13\x05\x00\x00\xd5\x05\x00\x00\x9c\x06\x00\x00\x66\x07\x00\x00'
    b'\x33\x08\x00\x00\xfe\x08\x00\x00\xc7\x09\x00\x00\x8c\x0a\x00\x00'
    b'\x4a\x0b\x00\x00\x00\x0c\x00\x00\xab\x0c\x00\x00\x4b\x0d\x00\x00'
    b'\xdd\x0d\x00\x00\x60\x0e\x00\x00\xd3\x0e\x00\x00\x35\x0f\x00\x00'
    b'\x84\x0f\x00\x00\xc0\x0f\x00\x00\xe9\x0f\x00\x00\xfd\x0f\x00\x00'
    b'\xfd\x0f\x00\x00\xe9\x0f\x00\x00\xc0\x0f\x00\x00\x84\x0f\x00\x00'
    b'\x35\x0f\x00\x00\xd3\x0e\x00\x00\x60\x0e\x00\x00\xdd\x0d\x00\x00'
    b'\x4b\x0d\x00\x00\xab\x0c\x00\x00\xff\x0b\x00\x00\x4a\x0b\x00\x00'
    b'\x8c\x0a\x00\x00\xc7\x09\x00\x00\xfe\x08\x00\x00\x33\x08\x00\x00'
    b'\x66\x07\x00\x00\x9c\x06\x00\x00\xd5\x05\x00\x00\x13\x05\x00\x00'
    b'\x59\x04\x00\x00\xa8\x03\x00\x00\x03\x03\x00\x00\x6a\x02\x00\x00'
    b'\xdf\x01\x00\x00\x63\x01\x00\x00\xf9\x00\x00\x00\xa0\x00\x00\x00'
    b'\x5a\x00\x00\x00\x28\x00\x00\x00\x0a\x00\x00\x00\x00\x00\x00\x00'
)
# cos(-2 pi k / 64)
_COS = (
    b'\x00\x10\x00\x00\xec\x0f\x00\x00\xb1\x0f\x00\x00\x4f\x0f\x00\x00'
    b'\xc8\x0e\x00\x00\x1c\x0e\x00\x00\x4d\x0d\x00\x00\x5e\x0c\x00\x00'
    b'\x50\x0b\x00\x00\x26\x0a\x00\x00\xe3\x08\x00\x00\x8a\x07\x00\x00'
    b'\x1f\x06\x00\x00\xa5\x04\x00\x00\x1f\x03\x00\x00\x91\x01\x00\x00'
    b'\x00\x00\x00\x00\x6f\xfe\xff\xff\xe1\xfc\xff\xff\x5b\xfb\xff\xff'
    b'\xe1\xf9\xff\xff\x76\xf8\xff\xff\x1d\xf7\xff\xff\xda\xf5\xff\xff'
    b'\xb0\xf4\xff\xff\xa2\xf3\xff\xff\xb3\xf2\xff\xff\xe4\xf1\xff\xff'
    b'\x38\xf1\xff\xff\xb1\xf0\xff\xff\x4f\xf0\xff\xff\x14\xf0\xff\xff'
)
# sin(-2 pi k / 64)
_SIN = (
    b'\x00\x00\x00\x00\x6f\xfe\xff\xff\xe1\xfc\xff\xff\x5b\xfb\xff\xff'
    b'\xe1\xf9\xff\xff\x76\xf8\xff\xff\x1d\xf7\xff\xff\xda\xf5\xff\xff'
    b'\xb0\xf4\xff\xff\xa2\xf3\xff\xff\xb3\xf2\xff\xff\xe4\xf1\xff\xff'
    b'\x38\xf1\xff\xff\xb1\xf0\xff\xff\x4f\xf0\xff\xff\x14\xf0\xff\xff'
    b'\x00\xf0\xff\xff\x14\xf0\xff\xff\x4f\xf0\xff\xff\xb1\xf0\xff\xff'
    b'\x38\xf1\xff\xff\xe4\xf1\xff\xff\xb3\xf2\xff\xff\xa2\xf3\xff\xff'
    b'\xb0\xf4\xff\xff\xda\xf5\xff\xff\x1d\xf7\xff\xff\x76\xf8\xff\xff'
    b'\xe1\xf9\xff\xff\x5b\xfb\xff\xff\xe1\xfc\xff\xff\x6f\xfe\xff\xff'
)


@micropython.viper
def _fft(re, im, cos, sin, n: int):
    """In-place radix-2 FFT of re + j*im, in fixed point. Each stage
    halves the values, so the result is the transform divided by n."""
    r = ptr32(re)
    m = ptr32(im)
    c = ptr32(cos)
    s = ptr32(sin)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            t = r[i]
            r[i] = r[j]
            r[j] = t
            t = m[i]
            m[i] = m[j]
            m[j] = t
    size = 2
    stride = n >> 1
    while size <= n:
        half = size >> 1
        for k in range(half):
            wr = c[k * stride]
            wi = s[k * stride]
            a = k
            while a < n:
                b = a + half
                tr = (wr * r[b] - wi * m[b] + _HALF) >> _Q
                ti = (wr * m[b] + wi * r[b] + _HALF) >> _Q
                ur = r[a]
                ui = m[a]
                r[b] = (ur - tr + 1) >> 1
                m[b] = (ui - ti + 1) >> 1
                r[a] = (ur + tr + 1) >> 1
                m[a] = (ui + ti + 1) >> 1
                a += size
        size <<= 1
        stride >>= 1


@micropython.viper
def _prepare(samples, pos: int, out, n: int, slope: int):
    """Detrend the samples (a ring buffer, oldest at pos), then take the
    differences, as InfiniTime's Detrend() does.

    The differences of a detrended signal are those of the signal less
    the slope (scaled, from the caller); the last value is zero, as the
    trend ends on the last sample.
    """
    s = ptr16(samples)
    o = ptr32(out)
    mask = n - 1
    prev = int(s[pos])
    for i in range(1, n):
        x = int(s[(pos + i) & mask])
        step = x - prev
        prev = x
        if step > _MAX_STEP:
            step = _MAX_STEP
        elif step < -_MAX_STEP:
            step = -_MAX_STEP
        o[i - 1] = (step << _SCALE) - slope
    o[mask] = 0


@micropython.viper
def _smooth(buf, a: int, high: int, n: int):
    """InfiniTime's band-pass: four exponential moving averages, as a
    low-pass filter, or with high, subtracted, as a high-pass filter."""
    p = ptr32(buf)
    b = _ONE - a
    for _ in range(4):
        avg = p[0]
        for i in range(n):
            avg = (a * p[i] + b * avg + _HALF) >> _Q
            if high:
                p[i] = p[i] - avg
            else:
                p[i] = avg


@micropython.viper
def _window(buf, window, n: int):
    p = ptr32(buf)
    w = ptr32(window)
    for i in range(n):
        p[i] = (p[i] * w[i] + _HALF) >> _Q


def _peak(spectrum, threshold, start, end):
    """The centre and width, in bins, of the one peak above threshold.

    The same as InfiniTime's PeakSearch(), which walks the linearly
    interpolated spectrum in steps of 0.01 bins, but working out where
    it crosses the threshold instead. A peak counts once the spectrum
    has been below the threshold, and only if it falls below again
    before the end. Returns (0, 0) unless there is exactly one.
    """
    peaks = 0
    centre = width = 0.0
    enabled = False
    rise = 0.0
    for i in range(start, end):
        y0 = spectrum[i]
        y1 = spectrum[i + 1] if i + 1 < len(spectrum) else y0
        if y0 < threshold:
            enabled = True
            if y1 >= threshold:
                rise = i + (threshold - y0) / (y1 - y0)
        elif y1 < threshold and enabled:
            fall = i + (y0 - threshold) / (y0 - y1)
            peaks += 1
            width = fall - rise
            centre = rise + width / 2
    if peaks != 1:
        return 0.0, 0.0
    return centre, width


class PTAGC():
    """Peak Tracking Automatic Gain Control

    Scales a signal to about -50 to 50, and rejects spikes caused by
    fast DC steps.
    """
    def __init__(self, start, decay, threshold):
        self._peak = start
        self._decay = decay
        self._boost = 1 / decay
        self._threshold = threshold

    def step(self, spl):
        # peak tracking
        peak = self._peak
        if abs(spl) > peak:
            peak *= self._boost
        else:
            peak *= self._decay
        self._peak = peak

        # rejection filter (clipper)
        threshold = self._threshold
        if spl > (peak * threshold) or spl < (peak * -threshold):
            return 0

        # booster
        spl = 100 * spl / (2 * peak)

        return spl


class PPG():
    """Heart rate from a PPG sensor, sampled at a fixed rate.

    :param spl: The first sample, to start the graph from
    :param rate: Samples per second (at least 8 for heart rates up to 240)
    """

    def __init__(self, spl, rate=8):
        self.rate = rate
        self.debug = None
        # Samples between analyses: half a second
        self._hop = max(1, rate // 2)
        self._resolution = rate / _LENGTH * 60  # bpm per bin
        self._roi = (int(_ROI_MIN / self._resolution + 0.5),
                     min(int(_ROI_MAX / self._resolution + 0.5), _LENGTH // 2 - 1))
        # The band-pass filter of InfiniTime, which runs at 10 Hz: its
        # cut-offs of about 2.7 Hz and 0.5 Hz, for this rate
        self._alpha_low = int(_ONE * (1 - math.exp(-2 * math.pi * 2.69 / rate)))
        self._alpha_high = int(_ONE * (1 - math.exp(-2 * math.pi * 0.497 / rate)))
        # numpy.hanning()
        self._re = array.array('i', [0] * _LENGTH)
        self._im = array.array('i', [0] * _LENGTH)
        self._spectrum = array.array('f', [0] * (_LENGTH // 2))
        self._average = array.array('f', [0] * _AVERAGE)
        # The last samples, oldest at _pos once there are enough
        self._samples = array.array('H', [0] * _LENGTH)
        self._pos = 0
        self.reset(True)

        # For the graph: drop the DC level, then scale
        self._dc = spl
        self._agc = PTAGC(20, 0.971 ** (24 / rate), 2)

    def reset(self, samples):
        """Start the averaging over; with samples, the data too."""
        if samples:
            self._count = 0
            self._pos = 0
            self._new = 0
            self._enough = False
        self._avg_index = 0
        for i in range(_AVERAGE):
            self._average[i] = 0
        self._last = 0.0
        self._als_threshold = None
        self._spectral_count = 0
        self._bpm = None if samples else 0

    def preprocess(self, spl, als=None):
        """Add a sample, and return it scaled for a graph (about +-50).

        Must be called at the rate given when creating the PPG. With the
        ambient light level (als), a sudden rise in it resets the data.
        """
        if self.debug is not None:
            self.debug.append(spl)

        if als is not None and self._als_threshold is not None \
                and als > self._als_threshold:
            self.reset(True)
        self._als = als

        self._samples[self._pos] = spl
        self._pos = (self._pos + 1) % _LENGTH
        if self._count < _LENGTH:
            self._count += 1
        self._new += 1
        if self._count == _LENGTH and (not self._enough or self._new >= self._hop):
            self._enough = True
            self._new = 0
            self._bpm = self._process()
            if self._bpm < 0:
                self.reset(False)

        self._dc += self._alpha_high * (spl - self._dc) / _ONE
        return int(self._agc.step(spl - self._dc))

    def _process(self):
        """Analyse the last samples; the heart rate, 0 if there is no
        clear one, or -1 to start the averaging over."""
        re = self._re
        im = self._im
        n = _LENGTH
        for i in range(n):
            im[i] = 0
        samples = self._samples
        pos = self._pos
        slope = ((samples[(pos + n - 1) % n] - samples[pos]) << _SCALE) // (n - 1)
        _prepare(samples, pos, re, n, slope)
        _smooth(re, self._alpha_low, 0, n)
        _smooth(re, self._alpha_high, 1, n)
        _window(re, _WINDOW, n)
        _fft(re, im, _COS, _SIN, n)

        # Average the magnitude with the last few spectra
        spectrum = self._spectrum
        count = self._spectral_count
        # Back to the scale of the samples: the FFT divided by n
        scale = n / (1 << _SCALE)
        for i in range(n // 2):
            r = float(re[i])
            j = float(im[i])
            mag = scale * math.sqrt(r * r + j * j)
            spectrum[i] = (spectrum[i] * count + mag) / (count + 1)
        if count < _SPECTRAL_AVG_MAX:
            self._spectral_count += 1

        start, end = self._roi
        peak = mean = 0.0
        for i in range(start, end):
            peak = max(peak, spectrum[i])
            mean += spectrum[i]
        mean /= end - start

        hr = 0.0
        width = 0.0
        if mean and peak / mean > _SNR_THRESHOLD and spectrum[0] < _DC_THRESHOLD:
            centre, width = _peak(spectrum, peak * _PEAK_THRESHOLD, start, end)
            hr = centre * self._resolution
        if width > _MAX_PEAK_WIDTH or not _HR_MIN <= hr <= _HR_MAX:
            hr = 0.0
        if hr == 0:
            self._spectral_count = 0

        if self._als is not None:
            self._als_threshold = self._als * _ALS_FACTOR

        # The average of the good readings
        self._avg_index = (self._avg_index + 1) % _AVERAGE
        self._average[self._avg_index] = hr
        total = good = 0
        for v in self._average:
            if v > 0:
                total += v
                good += 1
        hr = total / good if good else 0.0
        if hr == 0 and self._last > 0:
            self._last = 0.0
            return -1
        self._last = hr
        return int(hr + 0.5)

    def get_heart_rate(self):
        """The heart rate in bpm, None while there are not enough samples
        yet, or 0 if there is no clear reading."""
        bpm = self._bpm
        if self.debug and len(self.debug) >= 30 * self.rate:
            # Dump the debug data, every 30 seconds
            with open('hrs.data', 'ab') as f:
                # Re-sync marker
                f.write(b'\xff\xff')
                now = watch.rtc.get_localtime()
                f.write(array.array('H', now[:6]))
                f.write(self.debug)
            self.debug = array.array('H')
        return bpm if bpm is None else max(bpm, 0)

    def enable_debug(self):
        if self.debug is None:
            self.debug = array.array('H')
