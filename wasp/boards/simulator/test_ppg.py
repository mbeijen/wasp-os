import math
import random

import pytest

# The simulated watch must be set up before ppg imports it
import wasp
import ppg


def measure(signal, seconds=30, rate=8, als=100):
    p = ppg.PPG(int(signal(0)), rate)
    for i in range(seconds * rate):
        p.preprocess(int(signal(i / rate)), als)
    return p.get_heart_rate()


@pytest.mark.parametrize('bpm', (45, 60, 72, 100, 140, 180))
def test_heart_rate(bpm):
    rng = random.Random(bpm)

    def signal(t):
        # A pulse, with noise and a slow drift, as the sensor sees it
        return (9000 + 40 * math.sin(2 * math.pi * bpm / 60 * t)
                + rng.gauss(0, 8) + 3 * t)
    assert abs(measure(signal) - bpm) <= 2


def test_noise_is_no_reading():
    rng = random.Random(1)
    assert measure(lambda t: 9000 + rng.gauss(0, 30)) == 0


def test_not_enough_data():
    # Eight seconds of samples are needed for the first reading
    assert measure(lambda t: 9000 + 40 * math.sin(2 * math.pi * t), seconds=7) is None


def test_ambient_light_starts_over():
    p = ppg.PPG(9000)
    for i in range(8 * 20):
        p.preprocess(int(9000 + 40 * math.sin(2 * math.pi * i / 8)), 100)
    assert p.get_heart_rate() == 60
    # Taken off the wrist: much more light reaches the sensor
    p.preprocess(9000, 1000)
    assert p.get_heart_rate() is None


def test_recording():
    # The simulator's recording, made with the Heart app at 24 Hz with the
    # old sensor settings. Its second harmonic is strong, so most windows
    # have two peaks and give no reading; any reading must be right.
    data = wasp.watch.HRS.DATA[::3]
    p = ppg.PPG(data[0])
    readings = set()
    for v in data:
        p.preprocess(v, 100)
        readings.add(p.get_heart_rate())
    assert all(r is None or r == 0 or 60 <= r <= 70 for r in readings)


def test_peak_search():
    spectrum = [0, 0, 1, 1, 1, 2, 8, 9, 3, 1, 1, 1, 0, 0]
    centre, width = ppg._peak(spectrum, 5.4, 2, 12)
    # Up from 2 to 8 crosses 5.4 at 5.57, down from 9 to 3 at 7.6
    assert centre == pytest.approx(6.583, abs=0.001)
    assert width == pytest.approx(2.033, abs=0.001)
    # Two peaks above the threshold: no reading
    spectrum[10] = 8
    assert ppg._peak(spectrum, 5.4, 2, 12) == (0, 0)
