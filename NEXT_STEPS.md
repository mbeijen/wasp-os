# Next steps for the upstream-MicroPython PineTime port

State as of 2026-10-03, branch `pinetime-upstream-micropython` on
`mbeijen/wasp-os`. Everything below is optional; the watch is fully usable as
it is. Within each section, items are roughly in order of value.

## Waiting on others

- **MicroPython v1.30.0.** PRs #19729 (frozen native code), #19731 (PWM
  allocation) and #19733 (ADC `sample_ns`) were merged on 2026-10-10, so the
  `micropython` submodule now points at upstream master itself, with no fork.
  They are targeted for v1.30.0, scheduled for December; move the submodule to
  that tag once it is out.

## Firmware

- **Heap headroom.** Free at boot is about 12.4 KB (it was 7.1 KB). The next
  lever is apps building their widgets in `foreground()` instead of
  `__init__()`, an estimated 2–4 KB, then importing fonts lazily (1–1.5 KB).
  Measure each change with the unix-port harness before flashing. The 8 KB
  stack is about right: it peaks at 4.1 KB, plus the SoftDevice's needs.
- **Touch release latch fallback.** The CST816S driver now writes `0xFA =
  0x30` (interrupt on touch state change and on gesture) and `0xFB = 0` (no
  auto-reset) after every chip reset. Tested on hardware (2026-10-25), only
  `0x30` makes lifting the finger raise an interrupt: the default and
  InfiniTime's `0x70` don't. The registers read back as zero, so the writes
  can't be verified directly. Once swiping has proven reliable in use, drop the
  300 ms fallback in `get_touch_data()` and rely on the release.
- **Vibration strength.** Short pulses are 50% now. The old firmware's
  `duty=25` actually drove the motor about 75% of the time; set 75 to get
  exactly that feel back.

## MicroPython bugs found with wasptool (2026-10-31)

Both make the watch reset into its bootloader after a console session, because
the main loop stops calling `alive()` and the watchdog fires. Fix upstream.

- **`ports/nrf/drivers/bluetooth/ble_drv.c`:** `ble_drv_attr_s_notify()`
  busy-waits while `m_tx_in_progress` is above the limit, and nothing resets
  that count on `BLE_GAP_EVT_DISCONNECTED`. Hanging up while the watch prints
  hangs its main loop for good. Reset the count on disconnect and stop waiting
  when there is no connection. wasptool now waits for the output to settle
  before it hangs up: 10 out of 10 sessions instead of 1 out of 8.
- **`ports/nrf/modules/machine/rtcounter.c`:** the callback runs in the
  interrupt without `mp_sched_lock()` or an nlr handler (unlike
  `mp_irq_dispatch()` for hard IRQs, and the port's own `pin.c`). A pending
  KeyboardInterrupt (Ctrl-C on the console) or any exception escapes the
  interrupt before the RTC is re-armed, so wasp's 8 Hz tick and watchdog feed
  stop. Not reproduced yet; wasptool only sends Ctrl-C when the REPL does not
  answer.

## Tools

- **Publish wasptool on PyPI,** so `uv tool install wasptool` works without a
  checkout. Check the name is free first.
- **wasptool on macOS and Windows:** written for both (bleak, and `msvcrt` for
  the console) but only tested on GNU/Linux.
- **OTA speed.** Uploads take about 3 min 11 s. Try a packet receipt interval
  above 20 (`RECEIPT_INTERVAL` in `tools/wasptool/src/wasptool/dfu.py`),
  measuring each step; a failure shows up as an error from the bootloader at
  the end, not a bricked watch.
- **Update check:** compare `wasptool info`'s version with the latest GitHub
  release, and offer to download and install it.

## CI and packaging (converted, not yet run)

- **GitHub Actions on the fork.** Click "I understand my workflows, go ahead
  and enable them" once at https://github.com/mbeijen/wasp-os/actions, then
  run both workflows on the branch:
  `gh workflow run sim.yml --repo mbeijen/wasp-os --ref pinetime-upstream-micropython`
  (and the same for `main.yml`). The same build steps already pass locally.
- **Read the Docs, the Dockerfile and the Nix shell** were converted to uv (or,
  for Nix, nixpkgs' `adafruit-nrfutil` and `intelhex`) but have not been
  built.

## Upstreaming to wasp-os (when you decide to)

Nothing has gone to wasp-os yet; all changes are on `mbeijen` forks.

- **wasp-os itself:** the whole branch, best as a short series of PRs. The
  repository's README asks for exactly this MicroPython uplift.
- **wasp-os/bma42x-upy:** the port to the current MicroPython C API
  (`67e8184`). Only makes sense together with the move to upstream MicroPython.
- **ota-dfu-python:** no longer used here; its legacy DFU code now lives in
  wasptool. The bleak 3 port and the legacy-controller fix on
  `mbeijen/ota-dfu-python` could still go to wasp-os/ota-dfu-python or
  positron96/ota-dfu-python, where the bleak port came from.

## Hardware support

- **Colmi P8 and Senbono K9** need a board definition for upstream MicroPython,
  modelled on `wasp/boards/pinetime/micropython/`, plus the new flash driver
  and an RTC other than RTC1. Not doable without the hardware.
- **Bootloader:** the wasp-os fork of the Adafruit nRF52 bootloader is 575
  commits behind Adafruit. Leave it unless there is a concrete need: updating a
  bootloader risks bricking the watch.

## Releases

The README notes that the binary releases (up to 0.4) were withdrawn because
they don't support the third-generation PineTime. A release from this branch
would need someone to own release testing, and the CI runs above first.
