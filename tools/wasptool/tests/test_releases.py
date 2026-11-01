# SPDX-License-Identifier: LGPL-3.0-or-later

import hashlib
import json

import pytest

from wasptool import releases

FIRMWARE = b'firmware' * 100


def release(version, data=FIRMWARE):
    return {
        'version': version, 'date': '2026-11-01', 'commit': 'abc',
        'notes': f'- {version}',
        'files': {'micropython.zip': {
            'url': f'releases/{version}/micropython.zip', 'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}},
    }


MANIFEST = {'format': 1, 'latest': '0.4-250-gccccccc', 'releases': [
    release('0.4-250-gccccccc'), release('0.4-247-gbbbbbbb'),
    release('0.4-200-gaaaaaaa'),
]}


@pytest.fixture
def server(monkeypatch):
    """Serve MANIFEST and its files; returns the URLs fetched."""
    files = {'https://example.org/wasp/releases.json': json.dumps(MANIFEST).encode()}
    for r in MANIFEST['releases']:
        files['https://example.org/wasp/' + r['files']['micropython.zip']['url']] = FIRMWARE
    fetched = []

    def get(url, timeout=30):
        fetched.append(url)
        if url not in files:
            raise releases.ReleaseError(f'cannot fetch {url}: 404')
        return files[url]
    monkeypatch.setattr(releases, '_get', get)
    return files, fetched


@pytest.mark.parametrize('version, parsed', (
    ('0.4-247-gb3c27a9', (0, 4, 247)),
    ('v0.4', (0, 4, 0)),
    ('0.4.1-3-g1234567', (0, 4, 1, 3)),
    ('0.4-245-gf34b6c5-dirty', None),
    ('b3c27a9', None),
    (None, None),
))
def test_parse_version(version, parsed):
    assert releases.parse_version(version) == parsed


def test_newer():
    names = lambda rs: [r['version'] for r in rs]
    assert names(releases.newer(MANIFEST, '0.4-247-gbbbbbbb')) == ['0.4-250-gccccccc']
    assert names(releases.newer(MANIFEST, '0.4-250-gccccccc')) == []
    assert names(releases.newer(MANIFEST, '0.4-300-gddddddd')) == []
    # Older than all, unknown, or a local build: everything is news
    assert len(releases.newer(MANIFEST, '0.3')) == 3
    assert len(releases.newer(MANIFEST, None)) == 3
    assert len(releases.newer(MANIFEST, '0.4-249-gf34b6c5-dirty')) == 3


def test_fetch_and_download(server):
    files, fetched = server
    m = releases.fetch('https://example.org/wasp/releases.json')
    assert releases.latest(m)['version'] == '0.4-250-gccccccc'
    assert releases.download(m, releases.latest(m)) == FIRMWARE
    # File links are relative to releases.json
    assert fetched[-1] == ('https://example.org/wasp/releases/'
                           '0.4-250-gccccccc/micropython.zip')


def test_download_checks_sha256(server):
    files, _ = server
    m = releases.fetch('https://example.org/wasp/releases.json')
    files['https://example.org/wasp/releases/0.4-250-gccccccc/'
          'micropython.zip'] = b'tampered' * 100
    with pytest.raises(releases.ReleaseError, match='sha256'):
        releases.download(m, releases.latest(m))


@pytest.mark.parametrize('body', (b'<html>', b'{"format": 2, "releases": [1]}',
                                  b'{"format": 1, "releases": []}'))
def test_fetch_rejects(monkeypatch, body):
    monkeypatch.setattr(releases, '_get', lambda url, timeout=30: body)
    with pytest.raises(releases.ReleaseError):
        releases.fetch('https://example.org/releases.json')
