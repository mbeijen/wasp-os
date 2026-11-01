// SPDX-License-Identifier: LGPL-3.0-or-later
// Run Python on a wasp-os watch from the browser, over Web Bluetooth.
//
// A port of wasptool's ble.py and repl.py. The console is the Nordic UART
// Service; the watch sends and takes at most 20 bytes at a time and keeps
// only 128 received bytes, so code goes through MicroPython's raw REPL in
// raw-paste mode, which has flow control, or in short writes on firmware
// without it.

export const NUS = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
const NUS_RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';   // to the watch
const NUS_TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';   // from the watch
const CHUNK = 20;
const RAW_BANNER = 'raw REPL; CTRL-B to exit\r\n>';

export const sleep = ms => new Promise(r => setTimeout(r, ms));
const encode = s => new TextEncoder().encode(s);
const decode = b => new TextDecoder().decode(b);

// Items, such as notifications, waited for one at a time
export class Queue {
  constructor() { this.items = []; this.waiters = []; }
  put(item) {
    const waiter = this.waiters.shift();
    if (waiter) waiter(item); else this.items.push(item);
  }
  get(ms, what) {
    if (this.items.length) return Promise.resolve(this.items.shift());
    return new Promise((resolve, reject) => {
      const waiter = item => { clearTimeout(timer); resolve(item); };
      const timer = setTimeout(() => {
        this.waiters.splice(this.waiters.indexOf(waiter), 1);
        reject(new Error(what));
      }, ms);
      this.waiters.push(waiter);
    });
  }
}

export async function listen(characteristic, onData) {
  characteristic.addEventListener('characteristicvaluechanged', e => {
    const v = e.target.value;
    onData(new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength)));
  });
  await characteristic.startNotifications();
}

// Bytes from the watch, until a reader asks for them
export class Stream {
  constructor() {
    this.buf = new Uint8Array(0);
    this.more = new Queue();
    this.connected = true;
  }
  feed(bytes) {
    const buf = new Uint8Array(this.buf.length + bytes.length);
    buf.set(this.buf);
    buf.set(bytes, this.buf.length);
    this.buf = buf;
    this.more.put(1);
  }
  close() { this.connected = false; this.more.put(1); }
  discard() { this.buf = new Uint8Array(0); }
  pending() { return this.buf.length; }

  async wait(deadline, what) {
    if (!this.connected) throw new Error('The watch disconnected');
    const left = deadline - Date.now();
    if (left <= 0) throw new Error(`The watch did not answer (${what})`);
    try { await this.more.get(left, 'timeout'); } catch { /* checked next time */ }
  }

  take(n, skip = 0) {
    const out = this.buf.slice(0, n);
    this.buf = this.buf.slice(n + skip);
    return out;
  }

  // Everything up to marker, as text, dropping the marker
  async readUntil(marker, ms = 10000) {
    const m = encode(marker);
    const deadline = Date.now() + ms;
    for (;;) {
      const i = find(this.buf, m);
      if (i >= 0) return decode(this.take(i, m.length));
      await this.wait(deadline, JSON.stringify(marker));
    }
  }

  // Exactly n bytes
  async read(n, ms = 10000) {
    const deadline = Date.now() + ms;
    while (this.buf.length < n) await this.wait(deadline, `${n} bytes`);
    return this.take(n);
  }
}

function find(haystack, needle) {
  outer: for (let i = 0; i + needle.length <= haystack.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return i;
  }
  return -1;
}

export class Console {
  constructor(rx, stream) {
    this.rx = rx;
    this.stream = stream;
    this.paste = true;
  }

  static async open(server) {
    const service = await server.getPrimaryService(NUS);
    const stream = new Stream();
    await listen(await service.getCharacteristic(NUS_TX), b => stream.feed(b));
    return new Console(await service.getCharacteristic(NUS_RX), stream);
  }

  async write(data, response = true) {
    const bytes = typeof data === 'string' ? encode(data) : data;
    for (let i = 0; i < bytes.length; i += CHUNK) {
      const piece = bytes.subarray(i, i + CHUNK);
      if (response) await this.rx.writeValueWithResponse(piece);
      else await this.rx.writeValueWithoutResponse(piece);
    }
  }

  // Enter the raw REPL. The system runs in the background, so the REPL is
  // normally idle; only interrupt it if something runs in the foreground.
  async enter() {
    this.stream.discard();
    await this.write('\x01');
    try {
      await this.stream.readUntil(RAW_BANNER, 2000);
      return;
    } catch { /* busy: interrupt it */ }
    await this.write('\r\x03\x03');
    await sleep(200);
    this.stream.discard();
    await this.write('\x01');
    await this.stream.readUntil(RAW_BANNER);
  }

  async leave() {
    await this.write('\x02');
    await this.stream.readUntil('>>> ', 5000);
  }

  // Send code in raw-paste mode; false if the watch lacks it
  async pasteMode(code) {
    const s = this.stream;
    await this.write('\x05A\x01');
    const reply = decode(await s.read(2));
    if (reply === 'R\x00') return false;
    if (reply !== 'R\x01') {
      // Old firmware took the \x01 as a request to enter the raw REPL
      // again, and printed its banner (the "ra" of which we just read)
      await s.readUntil(RAW_BANNER.slice(2));
      return false;
    }
    const w = await s.read(2);
    const window = w[0] | (w[1] << 8);
    // The watch offers two windows, but upstream MicroPython's console
    // only buffers 128 bytes: use one, so it can never overflow
    await s.read(1);
    let credit = window;
    let i = 0;
    let ended = false;
    while (i < code.length && !ended) {
      while (credit === 0 || s.pending()) {
        const flag = (await s.read(1))[0];
        if (flag === 1) {
          credit += window;
        } else if (flag === 4) {
          // The watch hit a syntax error and wants no more
          ended = true;
          break;
        } else {
          throw new Error(`Unexpected ${flag} in raw-paste mode`);
        }
      }
      if (!ended) {
        const piece = code.subarray(i, i + credit);
        await this.write(piece, false);
        credit -= piece.length;
        i += piece.length;
      }
    }
    await this.write('\x04');
    if (!ended) await s.readUntil('\x04');
    return true;
  }

  async send(code) {
    const bytes = encode(code);
    if (this.paste) {
      if (await this.pasteMode(bytes)) return;
      this.paste = false;
    }
    // Writes with response, one piece at a time: slow but safe
    await this.write(bytes);
    await this.write('\x04');
    const ok = decode(await this.stream.read(2));
    if (ok !== 'OK') throw new Error(`Unexpected reply ${JSON.stringify(ok)} from the watch`);
  }

  // Run code and return what it prints; throws the last line of the
  // traceback if the code raises
  async exec(code, ms = 10000) {
    await this.send(code);
    const out = await this.stream.readUntil('\x04', ms);
    const err = await this.stream.readUntil('\x04', ms);
    await this.stream.readUntil('>', ms);
    if (err) {
      const e = new Error(err.trim().split('\n').pop());
      e.traceback = err;
      throw e;
    }
    return out;
  }

  // Run code that prints one JSON value, and return that value
  async json(code, ms) {
    return JSON.parse(await this.exec('import json\n' + code, ms));
  }

  async version() {
    return this.json('try:\n from version import VERSION as _v\n' +
                     'except ImportError:\n _v = None\nprint(json.dumps(_v))\ndel _v');
  }
}
