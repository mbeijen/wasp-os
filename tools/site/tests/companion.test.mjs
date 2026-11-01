// SPDX-License-Identifier: LGPL-3.0-or-later
// Run with: node --test tools/site/tests
import assert from 'node:assert/strict';
import test from 'node:test';

import * as watch from '../companion/companion.js';
import {FakeWatch} from './fake_watch.mjs';

async function connected(run) {
  const fake = new FakeWatch(run);
  await fake.console.enter();
  return fake;
}

test('info', async () => {
  const fake = await connected(code => code.includes('json.dumps(_i)') ?
      '{"version": "0.4-247-gb3c27a9", "battery": 80, "time": [2026, 11, 1, 9, 30, 5, 6, 305]}' : '');
  const i = await watch.info(fake.console);
  assert.equal(i.version, '0.4-247-gb3c27a9');
  assert.deepEqual(i.time.slice(0, 3), [2026, 11, 1]);
  // Small pieces, so they compile on a fragmented heap
  assert.ok(fake.ran.every(code => code.length < 200));
});

test('localtime is like Python', () => {
  // Sunday 1 November 2026: weekday 6, day 305 of the year
  assert.deepEqual(watch.localtime(new Date(2026, 10, 1, 21, 5, 9)),
                   [2026, 11, 1, 21, 5, 9, 6, 305]);
  assert.deepEqual(watch.localtime(new Date(2027, 0, 1, 0, 0, 0)).slice(6), [4, 1]);
});

test('setTime sends the next whole second', async () => {
  const fake = await connected(() => '');
  await watch.setTime(fake.console);
  const m = fake.ran.at(-1).match(/set_localtime\(\((.*)\)\)/);
  const t = m[1].split(', ').map(Number);
  const sent = new Date(t[0], t[1] - 1, t[2], t[3], t[4], t[5]);
  assert.ok(Math.abs(sent - Date.now()) < 1500);
});

test('drift', async () => {
  const t = watch.localtime(new Date(Date.now() - 42000));
  const fake = await connected(() => JSON.stringify(t));
  assert.ok(Math.abs(await watch.drift(fake.console) + 42) <= 1);
});

test('alarms', async () => {
  let saved = null;
  const fake = await connected(code => {
    if (code.includes('_a is not None')) return 'True\r\n';
    if (code.includes('get_alarms')) return '[[7, 30, 159], [9, 0, 128]]';
    const m = code.match(/set_alarms\((.*)\)/);
    if (m) saved = m[1];
    return '';
  });
  assert.deepEqual(await watch.alarms(fake.console), [[7, 30, 159], [9, 0, 128]]);
  await watch.setAlarms(fake.console, [[6, 45, 0x80 | 0x60]]);
  assert.equal(saved, '[(6, 45, 224)]');
  await assert.rejects(watch.setAlarms(fake.console, Array(5).fill([7, 0, 0])), /room for 4/);
});

test('alarms without the Alarm app', async () => {
  const fake = await connected(code => code.includes('_a is not None') ? 'False\r\n' : '');
  await assert.rejects(watch.alarms(fake.console), watch.NotAvailable);
});

test('formatDays', () => {
  assert.equal(watch.formatDays(0x80), 'once');
  assert.equal(watch.formatDays(0x9f), 'weekdays');
  assert.equal(watch.formatDays(0x05), 'Mon, Wed');
});

test('faces', async () => {
  const fake = await connected(code => code.includes('faces_list], ') ?
      '[["Clock", "PixelClock", "Word"], "PixelClock"]' : '');
  assert.deepEqual(await watch.faces(fake.console),
                   {labels: ['Clock', 'PixelClock', 'Word'], current: 'PixelClock'});
  await watch.setFace(fake.console, 'Word');
  assert.ok(fake.ran.some(code => code.includes('f[1] == "Word"')));
  assert.ok(fake.ran.at(-1).includes('save_settings(face=_f)'));
});
