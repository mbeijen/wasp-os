# wasptool

Talk to a [wasp-os](https://github.com/wasp-os/wasp-os) smart watch over
Bluetooth: update its firmware, set its clock, send it notifications, copy
files to and from it, or open a MicroPython prompt on it. It runs on
Linux, macOS and Windows, and needs nothing but Python and
[bleak](https://github.com/hbldh/bleak).

## Install

From a wasp-os checkout:

```sh
uv tool install ./tools/wasptool
```

## Use

```sh
wasptool scan                       # the watches in range
wasptool info                       # version, battery, memory, ...
wasptool info --json                # the same, for scripts
wasptool rtc                        # how far off is the watch's clock?
wasptool rtc set                    # set it to this computer's time
wasptool notify "Build" "Passed"    # show a notification
wasptool ota micropython.zip        # update the firmware
wasptool push apps/snake.py         # copy a file to the watch
wasptool pull alarms.txt            # and back
wasptool eval "print(wasp.watch.battery.voltage_mv())"
wasptool exec script.py
wasptool console                    # a MicroPython prompt (Ctrl-X exits)
wasptool reset [--bootloader]
```

With more than one watch around, pick one with `--device NAME` or
`--device ADDRESS`. Connecting is retried (`--retries`, 3 by default):
some radios, especially ones shared with Wi-Fi, fail the first attempt
now and again.

Commands exit with status 0 on success and 1 on failure; `eval` and
`exec` also exit with 1 when the code raises, with the traceback on
stderr.

## How it works

The watch's console is the Nordic UART Service. wasptool runs Python on it
through MicroPython's raw REPL, using raw-paste mode for flow control
where the firmware has it (MicroPython 1.14 and later), and paced writes
where it does not. Firmware updates use Nordic's legacy DFU protocol,
which the PineTime bootloader speaks.
