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
- **Dragging sliders in Settings.** A `Slider` is tap-to-set by design: its
  `touch()` snaps the tapped x position to a step, and nothing follows a moving
  finger (as upstream). A drag across one is a horizontal swipe, which Settings
  doesn't subscribe to, so the system navigates back to the clock. To support
  it, Settings could request `SWIPE_LEFTRIGHT` and set a slider from a swipe
  that starts on its row; the chip only reports where the swipe ended, so the
  knob would jump there rather than track the finger.
- **Vibration strength.** Short pulses are 50% now. The old firmware's
  `duty=25` actually drove the motor about 75% of the time; set 75 to get
  exactly that feel back.

## Tools

- **Port pynus to bleak as well.** The console (`tools/pynus`) still uses
  dbus-python and pygobject, which compile against system headers. With bleak,
  like OTA updates now, the `ble` group would be pure pip, with no `apt install
  libdbus-1-dev …` step.
- **Untested ota-dfu paths.** The secure DFU path and the automatic app-to-DFU
  switch have not been tested after the bleak port: the PineTime bootloader
  speaks legacy DFU, and wasptool enters the bootloader through the console.
- **OTA speed.** Uploads take about 3 min 13 s now. With bleak, try a receipt
  interval above 20, measuring each step; a failure shows up as a checksum
  error at the end, not a bricked watch.

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
- **wasp-os/ota-dfu-python:** the switch to bleak plus the error reporting.
  The bleak 3 port and the legacy-controller fix would also suit
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
