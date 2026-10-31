# SPDX-License-Identifier: LGPL-3.0-or-later

import asyncio
import types

import pytest

from fake_watch import FakeWatch, Overflow
from wasptool import watch
from wasptool.repl import Repl, ReplError


def run(coro):
    return asyncio.run(coro)


async def session(fake):
    repl = Repl(fake)
    await repl.enter()
    return repl


@pytest.mark.parametrize('paste', (True, False))
def test_exec(paste):
    async def go():
        fake = FakeWatch(paste=paste)
        repl = await session(fake)
        assert await repl.exec('print(6 * 7)') == '42\n'
        # Again, to check the prompt was consumed
        assert await repl.exec('x = 1\nprint(x + 1)') == '2\n'
        return fake
    fake = run(go())
    # Without raw-paste, everything is written with response
    assert paste or all(response for _, response in fake.writes)


@pytest.mark.parametrize('paste', (True, False))
def test_exec_error(paste):
    async def go():
        repl = await session(FakeWatch(paste=paste))
        with pytest.raises(ReplError) as e:
            await repl.exec('1 / 0')
        assert 'ZeroDivisionError' in str(e.value)
        assert 'Traceback' in e.value.traceback
        # The REPL is still usable afterwards
        assert await repl.exec('print("ok")') == 'ok\n'
    run(go())


def test_raw_paste_flow_control():
    # Far more than the 128 byte buffer, so it only fits with flow control
    code = 'x = 0\n' + 'x += 1\n' * 400 + 'print(x)'

    async def go():
        repl = await session(FakeWatch())
        assert await repl.exec(code) == '400\n'
    run(go())


def test_fake_catches_overflow():
    # Sending two windows at once, as the protocol allows, would overflow
    # the watch: make sure the fake notices, so the test above means something
    async def go():
        fake = FakeWatch()
        await Repl(fake).enter()
        await fake.write(b'\x05A\x01')
        await fake.write(b'#' * 129, response=False)
    with pytest.raises(Overflow):
        run(go())


def test_push_pull(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = bytes(range(256)) * 7 + b'tail'
    seen = []

    async def go():
        repl = await session(FakeWatch())
        await watch.push(repl, data, 'apps/blob.bin',
                         lambda done, total: seen.append((done, total)))
        assert (tmp_path / 'apps' / 'blob.bin').read_bytes() == data
        assert await watch.pull(repl, 'apps/blob.bin') == data
    run(go())
    assert seen[-1] == (len(data), len(data))


def test_notify_quotes(monkeypatch):
    fake_wasp = types.SimpleNamespace(
            system=types.SimpleNamespace(notifications={}, notify_duration=50),
            watch=types.SimpleNamespace(
                vibrator=types.SimpleNamespace(pulse=lambda ms: None)))
    fake_wasp.system.notify = fake_wasp.system.notifications.__setitem__
    monkeypatch.setitem(__import__('sys').modules, 'wasp', fake_wasp)
    title, body = 'It\'s "quoted"', 'Line\nbreak, ünïcode'

    async def go():
        await watch.notify(await session(FakeWatch()), title, body, id=7)
    run(go())
    assert fake_wasp.system.notifications == {7: {'title': title, 'body': body}}


def test_resume_when_running_in_background(monkeypatch):
    fake_wasp = types.SimpleNamespace(system=types.SimpleNamespace(
            run=lambda: print('Watch already running in the background')))
    monkeypatch.setitem(__import__('sys').modules, 'wasp', fake_wasp)

    async def go():
        fake = FakeWatch()
        repl = await session(fake)
        await watch.resume(repl)
        assert fake.mode == 'friendly'
    run(go())


def test_chunks():
    source = 'import x\n\nclass A:\n    pass\n\nclass B:\n    y = 1\n'
    assert watch.chunks(source) == [
        'import x\n\n', 'class A:\n    pass\n\n', 'class B:\n    y = 1\n']
    assert watch.chunks('class A:\n    pass\n') == ['class A:\n    pass\n']


def test_exec_chunks_share_globals():
    source = 'class A:\n    n = 2\n\nclass B:\n    n = A.n * 21\nprint(B.n)\n'

    async def go():
        repl = await session(FakeWatch())
        return [await repl.exec(c) for c in watch.chunks(source)]
    assert run(go())[-1] == '42\n'
