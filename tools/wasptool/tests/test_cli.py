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


class _Stream:
    name, address = 'mpus', 'DD:ED:1A:F1:F1:7A'


@pytest.fixture
def update(monkeypatch):
    """Run "wasptool update" against a fake watch and fake releases."""
    import contextlib
    import types
    from test_releases import MANIFEST, FIRMWARE
    from wasptool import releases, watch

    @contextlib.asynccontextmanager
    async def session(args, resume=True):
        yield types.SimpleNamespace(stream=_Stream)
    flashed = []

    async def ota(args, package):
        flashed.append((args.device, package.read()))
    monkeypatch.setattr(cli, 'session', session)
    monkeypatch.setattr(cli, '_ota', ota)
    monkeypatch.setattr(releases, 'fetch', lambda url: dict(MANIFEST, url=url))
    monkeypatch.setattr(releases, 'download', lambda m, r: FIRMWARE)

    def run(on_watch, *argv):
        async def version(repl):
            return on_watch
        monkeypatch.setattr(watch, 'version', version)
        with pytest.raises(SystemExit) as e:
            cli.main(['update', *argv])
        return e.value.code, flashed
    return run


def test_update(update, capsys):
    code, flashed = update('0.4-200-gaaaaaaa', '--yes')
    out = capsys.readouterr().out
    assert code == 0
    assert flashed[0][0] == _Stream.address and flashed[0][1].startswith(b'firm')
    # The notes of both newer builds, not of the one on the watch
    assert '- 0.4-250-gccccccc' in out and '- 0.4-247-gbbbbbbb' in out
    assert '- 0.4-200-gaaaaaaa' not in out


@pytest.mark.parametrize('on_watch, says', (
    ('0.4-250-gccccccc', 'up to date'),
    ('0.4-300-gddddddd', 'newer build'),
))
def test_update_nothing_to_do(update, capsys, on_watch, says):
    code, flashed = update(on_watch, '--yes')
    assert code == 0 and not flashed
    assert says in capsys.readouterr().out


def test_update_check_and_force(update):
    assert update('0.4-200-gaaaaaaa', '--check')[1] == []
    assert len(update('0.4-250-gccccccc', '--yes', '--force')[1]) == 1


def test_update_asks(update, monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda q: 'n')
    code, flashed = update('0.4-200-gaaaaaaa')
    assert code == 1 and not flashed
    # Without a terminal to ask on, it needs --yes
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert update('0.4-200-gaaaaaaa')[0] == 1
