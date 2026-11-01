# SPDX-License-Identifier: LGPL-3.0-or-later
"""The firmware builds published on a website, listed in releases.json."""

import hashlib
import json
import re
import urllib.parse
import urllib.request

from wasptool import __version__

URL = 'https://wasp-os.x14.nl/releases.json'
FIRMWARE = 'micropython.zip'
FORMAT = 1


class ReleaseError(Exception):
    """The releases could not be fetched, or a file is not what it says."""


def _get(url, timeout=30):
    req = urllib.request.Request(
            url, headers={'User-Agent': f'wasptool/{__version__}'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except OSError as e:
        raise ReleaseError(f'cannot fetch {url}: {e}') from None


def fetch(url=URL):
    """The manifest at url, with the url kept to resolve file links."""
    try:
        manifest = json.loads(_get(url))
    except ValueError:
        raise ReleaseError(f'{url} is not a list of releases') from None
    if manifest.get('format') != FORMAT or not manifest.get('releases'):
        raise ReleaseError(f'{url} is not a list of releases that this '
                           'wasptool understands: update wasptool')
    manifest['url'] = url
    return manifest


def parse_version(version):
    """A version from git describe as a tuple to compare, or None.

    "0.4-247-gb3c27a9" is (0, 4, 247): release 0.4 plus 247 commits.
    Builds with uncommitted changes (-dirty) cannot be ordered.
    """
    m = re.fullmatch(r'v?(\d+(?:\.\d+)*)(?:-(\d+)-g[0-9a-f]+)?', version or '')
    if not m:
        return None
    return tuple(int(n) for n in m[1].split('.')) + (int(m[2] or 0),)


def latest(manifest):
    return manifest['releases'][0]


def newer(manifest, version):
    """The releases newer than version, newest first.

    All of them if version cannot be ordered (unknown or a local build).
    """
    current = parse_version(version)
    if current is None:
        return list(manifest['releases'])
    return [r for r in manifest['releases']
            if (parse_version(r['version']) or ()) > current]


def download(manifest, release, name=FIRMWARE):
    """A file of a release, as bytes, checked against its sha256."""
    try:
        f = release['files'][name]
    except KeyError:
        raise ReleaseError(f'{release["version"]} has no {name}') from None
    url = urllib.parse.urljoin(manifest['url'], f['url'])
    data = _get(url)
    if len(data) != f['size'] or hashlib.sha256(data).hexdigest() != f['sha256']:
        raise ReleaseError(f'{url} does not match its sha256 in releases.json')
    return data
