#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Publish a build of wasp-os for the PineTime to the website.

Builds the firmware, copies it into a release folder of the site, adds
the release to releases.json and writes the landing page again. With
--upload, it first fetches releases.json from the server, so that the
releases published before are kept, then copies the site there.

    tools/publish.py --upload zerosum.x14.nl:/srv/wasp-os/www

The site is kept in build-site/; files on the server that are not there
are left alone, so old releases stay online.
"""

import argparse
import datetime
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_URL = 'https://wasp-os.x14.nl/'
SOURCE_URL = 'https://github.com/mbeijen/wasp-os'
UPSTREAM_URL = 'https://github.com/wasp-os/wasp-os'
DOCS_URL = 'https://wasp-os.readthedocs.io/en/latest/'

# What each file is for, in the order the landing page lists them. Only
# micropython.zip is required: the bootloader files change rarely and
# need the ARM toolchain to build.
FILES = (
    ('micropython.zip',
     'Update the firmware of a watch that runs wasp-os (wasptool ota)'),
    ('reloader-mcuboot.zip',
     'Install the wasp-os bootloader on a watch that runs InfiniTime'),
    ('reloader-factory.zip',
     'Install the wasp-os bootloader on a watch with the factory firmware'),
    ('bootloader-daflasher.zip',
     'Install the wasp-os bootloader with DaFlasher'),
    ('bootloader.hex',
     'The bootloader and SoftDevice, to flash with a debugger (SWD)'),
)

MANIFEST_FORMAT = 1


def run(*cmd, **kwargs):
    return subprocess.run(cmd, check=True, cwd=ROOT, text=True, **kwargs)


def git(*args, cwd=ROOT):
    return subprocess.run(('git',) + args, check=True, cwd=cwd, text=True,
                          capture_output=True).stdout.strip()


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def read_version():
    """The version the firmware reports, as written by the Makefile."""
    scope = {}
    with open(os.path.join(ROOT, 'wasp', 'version.py')) as f:
        exec(f.read(), scope)
    return scope['VERSION']


def default_notes(manifest, commit):
    """The commit subjects since the last release, if git knows it."""
    if not manifest['releases']:
        return ''
    last = manifest['releases'][0].get('commit')
    try:
        log = git('log', '--no-merges', '--format=%s', f'{last}..{commit}')
    except subprocess.CalledProcessError:
        return ''
    return '\n'.join('- ' + s for s in log.splitlines())


def add_release(manifest, version, commit, notes, build, release_dir):
    files = {}
    os.makedirs(release_dir, exist_ok=True)
    for name, _ in FILES:
        src = os.path.join(build, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(release_dir, name)
        shutil.copyfile(src, dst)
        files[name] = {
            'url': f'releases/{version}/{name}',
            'size': os.path.getsize(dst),
            'sha256': sha256(dst),
        }
    release = {
        'version': version,
        'date': datetime.date.today().isoformat(),
        'commit': commit,
        'notes': notes,
        'files': files,
    }
    if 'bootloader.hex' in files:
        release['bootloader'] = git('describe', '--tags', '--always',
                                    cwd=os.path.join(ROOT, 'bootloader'))
    manifest['releases'] = [release] + [
            r for r in manifest['releases'] if r['version'] != version]
    manifest['latest'] = version


def size(n):
    return f'{n / 1024:.0f} KiB'


def render_notes(notes):
    """Notes are plain text; lines that start with "- " become a list."""
    out, items = [], []
    for line in notes.splitlines() + ['']:
        if line.startswith('- '):
            items.append(f'<li>{html.escape(line[2:])}</li>')
            continue
        if items:
            out.append('<ul>' + ''.join(items) + '</ul>')
            items = []
        if line.strip():
            out.append(f'<p>{html.escape(line)}</p>')
    return '\n'.join(out)


def render_files(release):
    rows = []
    for name, purpose in FILES:
        f = release['files'].get(name)
        if not f:
            continue
        rows.append(
            f'<tr><td><a href="{html.escape(f["url"])}">{name}</a></td>'
            f'<td>{purpose}</td><td class="num">{size(f["size"])}</td></tr>'
            f'<tr class="sum"><td colspan="3">sha256 '
            f'<code>{f["sha256"]}</code></td></tr>')
    return '<table>' + ''.join(rows) + '</table>'


def render_index(manifest):
    with open(os.path.join(ROOT, 'tools', 'site', 'index.html.in')) as f:
        template = f.read()
    releases = manifest['releases']
    latest = releases[0]
    older = ''.join(
        f'<li><a href="releases/{html.escape(r["version"])}/">'
        f'{html.escape(r["version"])}</a> <span class="date">{r["date"]}'
        '</span></li>' for r in releases[1:])
    values = {
        'version': html.escape(latest['version']),
        'date': latest['date'],
        'commit_url': f'{SOURCE_URL}/commit/{latest["commit"]}',
        'commit': latest['commit'][:7],
        'notes': render_notes(latest['notes']) or '<p>No notes.</p>',
        'files': render_files(latest),
        'older': f'<h2>Older builds</h2><ul>{older}</ul>' if older else '',
        'source_url': SOURCE_URL,
        'upstream_url': UPSTREAM_URL,
        'docs_url': DOCS_URL,
    }
    for key, value in values.items():
        template = template.replace('{{' + key + '}}', value)
    return template


def render_release_index(release):
    """A plain list of the files of one release, for releases/<v>/."""
    v = html.escape(release['version'])
    rows = ''.join(
        f'<li><a href="{name}">{name}</a> ({size(f["size"])}, sha256 '
        f'<code>{f["sha256"]}</code>)</li>'
        for name, f in release['files'].items())
    return (f'<!doctype html><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width">'
            f'<title>wasp-os {v}</title>'
            f'<h1>wasp-os {v}</h1><p>Built {release["date"]}. '
            f'<a href="../../">All builds</a></p><ul>{rows}</ul>\n')


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--upload', metavar='HOST:DIR',
                   help='copy the site there with rsync over ssh')
    p.add_argument('--notes', help='release notes (default: the commit '
                   'subjects since the last release)')
    p.add_argument('--notes-file', type=argparse.FileType('r'),
                   help='read the release notes from this file')
    p.add_argument('--no-build', action='store_true',
                   help='publish build-pinetime/ as it is')
    p.add_argument('--allow-dirty', action='store_true',
                   help='publish a build with uncommitted changes')
    p.add_argument('--site', default=os.path.join(ROOT, 'build-site'),
                   help='where to keep the site (default: build-site/)')
    args = p.parse_args()

    if git('status', '--porcelain', '--untracked-files=no') and \
            not args.allow_dirty:
        sys.exit('There are uncommitted changes; commit them first, or '
                 'pass --allow-dirty')

    build = os.path.join(ROOT, 'build-pinetime')
    if not args.no_build:
        run('make', '-j8', 'BOARD=pinetime', f'PYTHON={sys.executable}',
            'micropython')
    version = read_version()
    if not os.path.exists(os.path.join(build, 'micropython.zip')):
        sys.exit(f'{build}/micropython.zip is missing: build it first')
    if os.path.getmtime(os.path.join(build, 'micropython.zip')) < \
            os.path.getmtime(os.path.join(ROOT, 'wasp', 'version.py')):
        sys.exit(f'micropython.zip is older than version {version}: '
                 'build it again')
    if not args.allow_dirty:
        if version.endswith('-dirty'):
            sys.exit(f'{version} was built with uncommitted changes')
        if not git('rev-parse', 'HEAD').startswith(
                version.rsplit('-g', 1)[-1]):
            sys.exit(f'{version} was not built from this commit')

    site = args.site
    os.makedirs(site, exist_ok=True)
    manifest_path = os.path.join(site, 'releases.json')
    if args.upload:
        # Start from the releases on the server; it may not have any yet
        host_dir = args.upload.rstrip('/')
        fetch = subprocess.run(('rsync', '-t', host_dir + '/releases.json',
                                manifest_path), cwd=ROOT, text=True,
                               capture_output=True)
        if fetch.returncode:
            if 'No such file' not in fetch.stderr:
                sys.exit(fetch.stderr)
            print('There is no releases.json on the server yet')
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except FileNotFoundError:
        manifest = {'format': MANIFEST_FORMAT, 'releases': []}

    commit = git('rev-parse', 'HEAD')
    if args.notes_file:
        notes = args.notes_file.read().strip()
    elif args.notes is not None:
        notes = args.notes
    else:
        notes = default_notes(manifest, commit)

    release_dir = os.path.join(site, 'releases', version)
    add_release(manifest, version, commit, notes, build, release_dir)
    with open(os.path.join(release_dir, 'index.html'), 'w') as f:
        f.write(render_release_index(manifest['releases'][0]))
    with open(manifest_path + '.tmp', 'w') as f:
        json.dump(manifest, f, indent=1)
        f.write('\n')
    os.replace(manifest_path + '.tmp', manifest_path)
    with open(os.path.join(site, 'index.html'), 'w') as f:
        f.write(render_index(manifest))
    print(f'Added {version} to {site}')

    if args.upload:
        # Not --delete: the server keeps releases this site does not have.
        # releases.json and the page go last, so that they never point at
        # files that are not there yet.
        run('rsync', '-rt', '--chmod=D755,F644', '--exclude=releases.json',
            '--exclude=/index.html', site + '/', host_dir + '/')
        run('rsync', '-t', '--chmod=F644', manifest_path,
            os.path.join(site, 'index.html'), host_dir + '/')
        print(f'Uploaded to {args.upload}; see {SITE_URL}')


if __name__ == '__main__':
    main()
