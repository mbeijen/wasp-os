# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michiel W. Beijen

"""Digital clock with Dutch weekday
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shows a time (as HH:MM) together with a battery meter, and the date with
the weekday in Dutch.

.. figure:: res/screenshots/DutchClockApp.png
    :width: 179
"""

from apps.user.clock import ClockApp

MONTH = 'janfebmrtaprmeijunjulaugsepoktnovdec'
WDAY = 'madiwodovrzazo'

class DutchClockApp(ClockApp):
    NAME = 'NLClk'

    def _day_string(self, now):
        """Produce a string representing the current day"""
        # Format the month as text
        month = now[1] - 1
        month = MONTH[month*3:(month+1)*3]

        # Format the weekday as text
        wday = now[6]
        wday = WDAY[wday*2:(wday+1)*2]

        return '{} {} {} {}'.format(wday, now[2], month, now[0])
