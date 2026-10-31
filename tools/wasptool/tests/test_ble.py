# SPDX-License-Identifier: LGPL-3.0-or-later

from types import SimpleNamespace as NS

from wasptool.ble import NUS_SERVICE, matches


def device(address='DD:ED:1A:F1:F1:7A', name='mpus', uuids=(NUS_SERVICE,)):
    return (NS(address=address, name=name),
            NS(local_name=name, service_uuids=list(uuids)))


def test_any_watch():
    assert matches(*device())
    # BlueZ sometimes leaves out the service UUIDs: the name will do
    assert matches(*device(uuids=()))
    assert matches(*device(name='MyWatch'))
    assert not matches(*device(name='MX Master 3S', uuids=()))


def test_by_address_or_name():
    assert matches(*device(), target='dd:ed:1a:f1:f1:7a')
    assert not matches(*device(), target='DD:ED:1A:F1:F1:7B')
    assert matches(*device(name='MyWatch'), target='MyWatch')
    assert not matches(*device(), target='MyWatch')
