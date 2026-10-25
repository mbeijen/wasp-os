# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2020-21 Daniel Thompson

"""Settings application
~~~~~~~~~~~~~~~~~~~~~~~

Allows a very small set of user preferences (including the date and
time) to be set on the device itself.

.. figure:: res/screenshots/SettingsApp.png
    :width: 179

.. note::

    The settings tool is not expected to comprehensively present every
    user configurable preference. Some are better presented via a
    companion app and some particular exotic ones are perhaps best
    managed with a user-provided ``main.py``.
"""


import wasp
import fonts
import icons

class SettingsApp():
    """Settings application."""
    NAME = 'Settings'
    ICON = icons.settings

    def __init__(self):
        self._slider = wasp.widgets.Slider(3, 10, 90)
        self._nfy_slider = wasp.widgets.Slider(3, 10, 90)
        self._scroll_indicator = wasp.widgets.ScrollIndicator()
        self._HH = wasp.widgets.Spinner(50, 60, 0, 23, 2)
        self._MM = wasp.widgets.Spinner(130, 60, 0, 59, 2)
        self._dd = wasp.widgets.Spinner(20, 60, 1, 31, 1)
        self._mm = wasp.widgets.Spinner(90, 60, 1, 12, 1)
        self._yy = wasp.widgets.Spinner(160, 60, 20, 60, 2)
        self._units = ['Metric', 'Imperial']
        self._units_toggle = wasp.widgets.Button(32, 90, 176, 48, "Change")
        self._settings = ['Brightness', 'Notification Level', 'Time', 'Date', 'Units']
        self._sett_index = 0
        self._current_setting = self._settings[0]

    def foreground(self):
        self._slider.value = wasp.system.brightness - 1
        self._draw()
        wasp.system.request_event(wasp.EventMask.TOUCH)
        wasp.system.request_event(wasp.EventMask.SWIPE_UPDOWN)
        wasp.system.request_event(wasp.EventMask.SWIPE_LEFTRIGHT)

    def touch(self, event):
        if self._current_setting == 'Brightness':
            self._slider.touch(event)
            wasp.system.brightness = self._slider.value + 1
        elif self._current_setting == 'Notification Level':
            self._nfy_slider.touch(event)
            wasp.system.notify_level = self._nfy_slider.value + 1
        elif self._current_setting == 'Time':
            if self._HH.touch(event) or self._MM.touch(event):
                now = list(wasp.watch.rtc.get_localtime())
                now[3] = self._HH.value
                now[4] = self._MM.value
                wasp.watch.rtc.set_localtime(now)
        elif self._current_setting == 'Date':
            if self._yy.touch(event) or self._mm.touch(event) \
                    or self._dd.touch(event):
                now = list(wasp.watch.rtc.get_localtime())
                now[0] = self._yy.value + 2000
                now[1] = self._mm.value
                now[2] = self._dd.value
                wasp.watch.rtc.set_localtime(now)
        elif self._current_setting == 'Units':
            if self._units_toggle.touch(event):
                wasp.system.units = self._units[(self._units.index(wasp.system.units) + 1) % len(self._units)]
        self._update()

    def swipe(self, event):
        """Handle swipes.

        Up and down move between settings. A left or right swipe along a
        slider moves it one step in that direction: the touch controller
        reports a drag as a swipe. Any other left or right swipe navigates
        away as usual.
        """
        if event[0] == wasp.EventType.UP:
            self._sett_index += 1
            self._draw()
        elif event[0] == wasp.EventType.DOWN:
            self._sett_index -= 1
            self._draw()
        elif self._current_setting in ('Brightness', 'Notification Level') \
                and 60 <= event[2] < 160:
            # Along the slider row (the knob is drawn at y 90-130). The
            # swipe is reported close to where it started, so step in its
            # direction rather than jumping to its position.
            step = 1 if event[0] == wasp.EventType.RIGHT else -1
            if self._current_setting == 'Brightness':
                wasp.system.brightness = min(max(wasp.system.brightness + step, 1), 3)
                self._slider.value = wasp.system.brightness - 1
            else:
                wasp.system.notify_level = min(max(wasp.system.notify_level + step, 1), 3)
                self._nfy_slider.value = wasp.system.notify_level - 1
            self._update()
        else:
            return True

    def _draw(self):
        """Redraw the display from scratch."""
        draw = wasp.watch.drawable
        mute = wasp.watch.display.mute
        self._current_setting = self._settings[self._sett_index % len(self._settings)]
        mute(True)
        draw.fill()
        draw.set_color(wasp.system.theme('bright'))
        draw.set_font(fonts.sans24)
        draw.string(self._current_setting, 0, 6, width=240)
        if self._current_setting == 'Brightness':
            self._slider.value = wasp.system.brightness - 1
        elif self._current_setting == 'Notification Level':
            self._nfy_slider.value = wasp.system.notify_level - 1
        elif self._current_setting == 'Time':
            now = wasp.watch.rtc.get_localtime()
            self._HH.value = now[3]
            self._MM.value = now[4]
            draw.set_font(fonts.sans28)
            draw.string(':', 110, 120-14, width=20)
            self._HH.draw()
            self._MM.draw()
        elif self._current_setting == 'Date':
            now = wasp.watch.rtc.get_localtime()
            self._yy.value = now[0] - 2000
            self._mm.value = now[1]
            self._dd.value = now[2]
            self._yy.draw()
            self._mm.draw()
            self._dd.draw()
            draw.set_font(fonts.sans24)
            draw.string('DD    MM    YY',0,180, width=240)
        elif self._current_setting == 'Units':
            self._units_toggle.draw()
        self._scroll_indicator.draw()
        self._update()
        mute(False)

    def _update(self):
        draw = wasp.watch.drawable
        draw.set_color(wasp.system.theme('bright'))
        if self._current_setting == 'Brightness':
            if wasp.system.brightness == 3:
                say = "High"
            elif wasp.system.brightness == 2:
                say = "Mid"
            else:
                say = "Low"
            self._slider.update()
            draw.string(say, 0, 150, width=240)
        elif self._current_setting == 'Notification Level':
            if wasp.system.notify_level == 3:
                say = "High"
            elif wasp.system.notify_level == 2:
                say = "Mid"
            else:
                say = "Silent"
            self._nfy_slider.update()
            draw.string(say, 0, 150, width=240)
        elif self._current_setting == 'Units':
            draw.string(wasp.system.units, 0, 150, width=240)
