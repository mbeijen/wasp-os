# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2020 Daniel Thompson

"""Heart rate monitor
~~~~~~~~~~~~~~~~~~~~~

A graphing heart rate monitor using a PPG sensor.

.. figure:: res/screenshots/HeartApp.png
    :width: 179

This program also implements some (entirely optional) debug features to
store the raw heart data to the filesystem so that the samples can be used
to further refine the heart rate detection algorithm.

To enable the logging feature select the heart rate application using the
watch UI and then run the following command via wasptool:

.. code-block:: sh

    wasptool eval 'wasp.system.app.debug = True'

Once debug has been enabled then the watch will automatically log heart
rate data whenever the heart rate application is running (and only
when it is running). Setting the debug flag to False will disable the
logging when the heart rate monitor next exits.

Finally to download the logs for analysis try:

.. code-block:: sh

    wasptool pull hrs.data

The log holds the raw samples, eight per second, in blocks of 30 seconds;
``tools/hrs2csv.py`` turns it into a CSV file.
"""

import wasp
import ppg

class HeartApp():
    """Heart rate monitor application."""
    NAME = 'Heart'

    def __init__(self):
        self._debug = False
        self._hrdata = None

    def foreground(self):
        """Activate the application."""
        wasp.watch.hrs.enable()

        # There is no delay after the enable because the redraw should
        # take long enough it is not needed
        draw = wasp.watch.drawable
        draw.fill()
        draw.set_color(wasp.system.theme('bright'))
        draw.string('Measuring...', 0, 6, width=240)

        wasp.system.request_tick(1000 // 8)

        self._bpm = None
        self._hrdata = ppg.PPG(wasp.watch.hrs.read_hrs())
        if self._debug:
            self._hrdata.enable_debug()
        self._x = 0

    def background(self):
        wasp.watch.hrs.disable()
        self._hrdata = None

    def tick(self, ticks):
        """Take a sample at each tick, eight times a second.

        If ticks were missed, the sample is repeated for each, to keep
        the timing of the signal right.
        """
        draw = wasp.watch.drawable
        hrs = wasp.watch.hrs
        spl = hrs.read_hrs()
        als = hrs.read_als()
        for _ in range(ticks):
            y = self._hrdata.preprocess(spl, als)
        wasp.system.keep_awake()

        bpm = self._hrdata.get_heart_rate()
        if bpm != self._bpm:
            self._bpm = bpm
            draw.set_color(wasp.system.theme('bright'))
            draw.string('{} bpm'.format(bpm) if bpm else
                        ('Measuring...' if bpm is None else '- bpm'),
                        0, 6, width=240)

        # Graph is orange by default...
        color = wasp.system.theme('spot1')
        # If the maths goes wrong lets show it in the chart!
        if y > 100 or y < -100:
            color = 0xffff
        if y > 104 or y < -104:
            y = 0
        y += 104
        x = self._x
        draw.fill(0, x, 32, 3, 208-y)
        draw.fill(color, x, 239-y, 3, y)
        if x < 237:
            draw.fill(0, x+3, 32, 3, 208)
        x += 3
        if x >= 240:
            x = 0
        self._x = x

    @property
    def debug(self):
        return self._debug

    @debug.setter
    def debug(self, value):
        self._debug = value
        if value and self._hrdata:
            self._hrdata.enable_debug()
