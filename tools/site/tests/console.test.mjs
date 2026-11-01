// SPDX-License-Identifier: LGPL-3.0-or-later
// Run with: node --test tools/site/tests
import assert from 'node:assert/strict';
import test from 'node:test';

import {FakeWatch} from './fake_watch.mjs';

const VERSION = code => code.includes('VERSION') ? '"0.4-247-gb3c27a9"\r\n' : '';

for (const paste of [true, false]) {
  const mode = paste ? 'raw-paste' : 'without raw-paste';

  test(`exec and version (${mode})`, async () => {
    const fake = new FakeWatch(code => code.endsWith('print(6 * 7)') ? '42\r\n' : VERSION(code),
                               {paste});
    const c = fake.console;
    await c.enter();
    assert.equal(await c.exec('print(6 * 7)'), '42\r\n');
    assert.equal(await c.version(), '0.4-247-gb3c27a9');
    // Every write fits a BLE packet
    assert.ok(fake.writes.every(w => w.length <= 20));
    // Without raw-paste, everything is written with response
    assert.ok(paste || fake.writes.every(w => w.response));
  });

  test(`long code (${mode})`, async () => {
    const code = 'x = 1\n'.repeat(200);
    const fake = new FakeWatch(c => c === code ? 'done' : '', {paste, window: 32});
    await fake.console.enter();
    assert.equal(await fake.console.exec(code), 'done');
  });
}

test('exec throws the traceback', async () => {
  const fake = new FakeWatch(() => ({err: 'Traceback (most recent call last):\r\n' +
                                          'NameError: name \'x\' isn\'t defined\r\n'}));
  await fake.console.enter();
  await assert.rejects(fake.console.exec('x'), /NameError/);
  // And it can go on
  fake.run = () => 'ok';
  assert.equal(await fake.console.exec('1'), 'ok');
});

test('json', async () => {
  const fake = new FakeWatch(() => '{"battery": 80, "time": [2026, 11, 1]}\r\n');
  await fake.console.enter();
  assert.deepEqual(await fake.console.json('print(1)'),
                   {battery: 80, time: [2026, 11, 1]});
  assert.ok(fake.ran.at(-1).startsWith('import json\n'));
});
