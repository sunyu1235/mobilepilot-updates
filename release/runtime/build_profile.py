#!/usr/bin/env python3
"""Public GitHub Actions builder for relocatable Ubuntu ARM64 userspace only.

Does not contain MobilePilot adapters, device credentials or model artifacts.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import urllib.request

INTERFACES = ['android.camera.v1', 'android.display.v1', 'android.platform.v1',
              'android.sensors.v1', 'android.audio.v1', 'panda.usb.v1', 'panda.f4-guard.v1']
UV_VERSION = '0.13.5'
UV_SHA256 = '4bb69cf95ed13f23713bb7bc09f241896ea0c75b7c557e615a20604b82f9c403'


def canonical(value):
  return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def build(identity, output, clang=20):
  if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,79}', identity):
    raise ValueError('Invalid immutable release identity')
  if platform.machine() not in ('aarch64', 'arm64'):
    raise RuntimeError('Use a native ARM64 GitHub runner')
  output.mkdir(parents=True, exist_ok=True)
  with tempfile.TemporaryDirectory(prefix='oneplus-runtime-') as temporary:
    root = Path(temporary) / 'prefix'; root.mkdir()
    (root / 'bin').mkdir(); (root / 'lib').mkdir(); (root / 'usr/bin').mkdir(parents=True)
    libraries = set()

    def copy_binary(source, target):
      source, target = Path(source), Path(target)
      target.parent.mkdir(parents=True, exist_ok=True)
      shutil.copyfile(source.resolve(), target)
      target.chmod(0o755)
      found = subprocess.run(['ldd', str(source)], capture_output=True, text=True, check=True).stdout
      for value in re.findall(r'(?:=>\s+|^\s*)(/[^\s]+)', found, re.M):
        path = Path(value)
        if path.name.startswith(('ld-linux', 'libc.so', 'libm.so', 'libpthread.so', 'libdl.so', 'librt.so', 'libresolv.so')):
          continue  # Shared Ubuntu glibc is an explicit minimum ABI, not replaced.
        if path.name in libraries:
          continue
        libraries.add(path.name)
        copy_binary(path, root / 'lib' / path.name)

    py = Path(sys.executable).resolve()
    copy_binary(py, root / 'usr/bin' / py.name)
    stdlib = Path(sysconfig.get_path('stdlib'))
    shutil.copytree(stdlib, root / 'usr/lib' / stdlib.name,
                    ignore=shutil.ignore_patterns('dist-packages', 'site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'tkinter'))
    for shared in (root / 'usr/lib' / stdlib.name).rglob('*.so'):
      # Discover transitive dependencies without changing extension modules.
      found = subprocess.run(['ldd', str(shared)], capture_output=True, text=True)
      if found.returncode == 0:
        for value in re.findall(r'=>\s+(/[^\s]+)', found.stdout):
          path = Path(value)
          if not path.name.startswith(('ld-linux', 'libc.so', 'libm.so', 'libpthread.so', 'libdl.so', 'librt.so')) and path.name not in libraries:
            libraries.add(path.name); copy_binary(path, root / 'lib' / path.name)
    compiler = shutil.which(f'clang-{clang}')
    if not compiler:
      raise RuntimeError(f'clang-{clang} is unavailable; refusing an incomplete profile')
    copy_binary(compiler, root / f'usr/bin/clang-{clang}')
    resources = subprocess.check_output([compiler, '-print-resource-dir'], text=True).strip()
    shutil.copytree(resources, root / f'usr/lib/clang/{clang}')
    for name, mode in [('clang', ''), ('clang++', '--driver-mode=g++')]:
      (root / 'bin' / name).write_text('#!/bin/sh\nROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
          f'exec "$ROOT/usr/bin/clang-{clang}" -resource-dir "$ROOT/usr/lib/clang/{clang}" {mode} "$@"\n')
      (root / 'bin' / name).chmod(0o755)
    for library in ('libdrm.so.2', 'libgbm.so.1', 'libdbus-1.so.3', 'libportaudio.so.2'):
      listing = subprocess.check_output(['ldconfig', '-p'], text=True)
      match = re.search(r'^\s*' + re.escape(library) + r'\s.*=>\s+(\S+)', listing, re.M)
      if not match:
        raise RuntimeError('Required userspace library is missing: ' + library)
      copy_binary(match[1], root / 'lib' / library)
      libraries.add(library)
    url = f'https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz'
    raw = urllib.request.urlopen(url, timeout=60).read()
    if hashlib.sha256(raw).hexdigest() != UV_SHA256:
      raise RuntimeError('Pinned UV artifact SHA-256 mismatch')
    import io
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
      member = archive.getmember('uv-aarch64-unknown-linux-gnu/uv')
      with archive.extractfile(member) as source, (root / 'bin/uv').open('wb') as target:
        shutil.copyfileobj(source, target)
    (root / 'bin/uv').chmod(0o755)
    metadata = {'id': identity, 'arch': 'aarch64', 'python': platform.python_version(), 'glibc_min': '2.39',
                'clang': clang, 'runtime_abi': 1, 'interfaces': sorted(INTERFACES),
                'libraries': sorted(libraries), 'python_path': 'usr/bin/' + py.name, 'uv_path': 'bin/uv'}
    (root / 'profile.json').write_bytes(canonical(metadata))
    packages = subprocess.check_output(['dpkg-query', '-W', '-f=${Package}\t${Version}\n'], text=True)
    (root / 'provenance.json').write_bytes(canonical({'ubuntu': platform.freedesktop_os_release(),
       'packages': packages.splitlines(), 'uv': {'version': UV_VERSION, 'sha256': UV_SHA256},
       'github_run': os.environ.get('GITHUB_RUN_ID'), 'builder_commit': os.environ.get('GITHUB_SHA'),
       'contains_adapters': False, 'contains_models': False, 'contains_rootfs': False}))
    # Redistribution notices accompany the public Ubuntu/toolchain libraries.
    for name in ('python3.12', f'clang-{clang}', f'libllvm{clang}', 'libgbm1', 'libdrm2', 'libdbus-1-3', 'libportaudio2', 'libssl3t64'):
      notice = Path('/usr/share/doc') / name / 'copyright'
      if notice.exists():
        target = root / 'share/licenses' / (name + '.copyright'); target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(notice, target)
    bundle = output / (identity + '.tar.gz')
    unpacked = 0
    with bundle.open('wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w') as archive:
      for file in sorted(root.rglob('*')):
        if not file.is_file():
          continue
        info = archive.gettarinfo(str(file), str(file.relative_to(root)))
        info.uid = info.gid = info.mtime = 0; info.uname = info.gname = ''
        with file.open('rb') as source:
          archive.addfile(info, source)
        unpacked += info.size
    artifact = {'url': f'https://github.com/sunyu1235/mobilepilot-updates/releases/download/{identity}/{bundle.name}',
                'bytes': bundle.stat().st_size, 'unpacked_bytes': unpacked,
                'sha256': hashlib.sha256(bundle.read_bytes()).hexdigest()}
    (output / 'profile.json').write_bytes(canonical({**metadata, 'artifact': artifact}))
    print(json.dumps({'bundle': str(bundle), **artifact}))


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--id', required=True)
  parser.add_argument('--output', required=True, type=Path)
  parser.add_argument('--clang', default=20, type=int)
  args = parser.parse_args(); build(args.id, args.output, args.clang)
