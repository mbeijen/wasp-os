# SPDX-License-Identifier: LGPL-3.0-or-later

import argparse

import pytest

from wasptool import cli


@pytest.mark.parametrize('text, mask', (
    ('once', 0), ('daily', 0x7f), ('Weekdays', 0x1f), ('weekends', 0x60),
    ('mon,wed', 0x05), ('su', 0x40), ('tue,thu,sat', 0x2a),
))
def test_days(text, mask):
    assert cli.parse_days(text) == mask


@pytest.mark.parametrize('text', ('t', 'tu,x', 'someday', ''))
def test_bad_days(text):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_days(text)


@pytest.mark.parametrize('mask, text', (
    (0x80, 'once'), (0x9f, 'weekdays'), (0x05, 'Mon,Wed'), (0x7f, 'daily'),
))
def test_format_days(mask, text):
    assert cli.format_days(mask) == text


@pytest.mark.parametrize('text', ('7', '24:00', '7:60', 'x:30'))
def test_bad_time(text):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_time(text)


def test_face_names():
    assert cli._face_key('pixel_clock') == cli._face_key('PixelClock')
