// SPDX-License-Identifier: LGPL-3.0-or-later
// A stand-in for a watch's console that speaks MicroPython's raw REPL,
// ported from wasptool's tests/fake_watch.py. It cannot run Python, so
// a test gives it a function that answers each piece of code with what
// it prints (or {err}). It throws if the page ever sends more than the
// watch's 128 byte receive buffer holds.

import {Console, Stream} from '../lib/console.js';

const BANNER = 'raw REPL; CTRL-B to exit\r\n>';
const RING = 128;
const bytes = s => new TextEncoder().encode(s);

export class FakeWatch {
  constructor(run, {paste = true, window = RING} = {}) {
    this.run = run;
    this.paste = paste;
    this.window = window;
    this.mode = 'friendly';
    this.code = [];
    this.unacked = 0;
    this.writes = [];
    this.ran = [];
    this.stream = new Stream();
    const write = response => async data => {
      this.writes.push({length: data.length, response});
      for (const b of data) this.byte(b);
    };
    this.rx = {writeValueWithResponse: write(true),
               writeValueWithoutResponse: write(false)};
    this.console = new Console(this.rx, this.stream);
  }

  feed(s) {
    const b = typeof s === 'string' ? bytes(s) : s;
    setTimeout(() => this.stream.feed(b), 0);
  }

  exec(prefix) {
    const code = new TextDecoder().decode(Uint8Array.from(this.code));
    this.code = [];
    this.ran.push(code);
    let reply = this.run(code) ?? '';
    if (typeof reply === 'string') reply = {out: reply};
    this.feed(prefix + (reply.out || '') + '\x04' + (reply.err || '') + '\x04>');
  }

  byte(b) {
    switch (this.mode) {
      case 'friendly':
        if (b === 1) { this.mode = 'raw'; this.feed(BANNER); }
        else if (b === 3) this.feed('\r\n>>> ');
        break;
      case 'raw':
        if (b === 1) { this.code = []; this.feed(BANNER); }
        else if (b === 2) { this.mode = 'friendly'; this.feed('\r\n>>> '); }
        else if (b === 4) this.exec('OK');
        else if (b === 5 && this.paste) this.mode = 'paste-request';
        else this.code.push(b);
        break;
      case 'paste-request':
        if (b === 0x41) this.mode = 'paste-request-A';
        break;
      case 'paste-request-A':
        this.mode = 'paste';
        this.unacked = 0;
        this.feed(Uint8Array.of(0x52, 1, this.window & 0xff, this.window >> 8, 1));
        break;
      case 'paste':
        if (b === 4) {
          this.mode = 'raw';
          this.feed('\x04');
          this.exec('');
          return;
        }
        this.code.push(b);
        if (++this.unacked > RING) {
          throw new Error(`${this.unacked} bytes sent before the watch could take them`);
        }
        if (this.unacked === this.window) {
          // The watch takes a window's worth from its buffer, but not
          // before the page has had a chance to send more
          setTimeout(() => { this.unacked -= this.window; this.stream.feed(Uint8Array.of(1)); }, 0);
        }
        break;
    }
  }
}
