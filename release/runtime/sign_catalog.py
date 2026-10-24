"""Public Actions signer: only a role-limited delegate key enters CI secrets."""
import argparse
import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import serialization

ROOT_SPKI = base64.b64decode('MCowBQYDK2VwAyEA+y7lFS+6SRnoZdtmg3pmXR5BlxeMGaulCGgJLw8Cezk=')
DOMAIN = b'MobilePilot/runtime-catalog/v1\n'
CERT_DOMAIN = b'MobilePilot/runtime-publisher/v1\n'


def canonical(value):
  return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def checked_key(cert):
  import time
  raw = base64.b64decode(cert['payload'], validate=True)
  serialization.load_der_public_key(ROOT_SPKI).verify(base64.b64decode(cert['signature'], validate=True), CERT_DOMAIN + raw)
  body = json.loads(raw)
  if (body['role'] != 'mobilepilot-oneplus9-runtime' or body['schema'] != 1
      or body['repository'] != 'sunyu1235/mobilepilot-updates' or body['expires'] <= time.time()):
    raise ValueError('Out-of-scope/expired delegate')
  return serialization.load_der_public_key(base64.b64decode(body['spki'], validate=True))


def sign(profile, cert, sequence, output):
  key = serialization.load_pem_private_key(base64.b64decode(os.environ['RUNTIME_PUBLISHER_KEY'], validate=True), None)
  public = checked_key(cert)
  profiles = []
  try:
    request = urllib.request.Request('https://github.com/sunyu1235/mobilepilot-updates/releases/download/runtime-stable/runtime-catalog.json')
    old = json.loads(urllib.request.urlopen(request, timeout=30).read(1024 * 1024))
    raw = base64.b64decode(old['payload'], validate=True)
    checked_key(old['certificate']).verify(base64.b64decode(old['signature'], validate=True), DOMAIN + raw)
    data = json.loads(raw)
    if data['product'] != 'mobilepilot-oneplus9-runtime' or data['sequence'] >= sequence:
      raise ValueError('Catalog sequence must increase')
    profiles = data['profiles']
  except urllib.error.HTTPError as exc:
    if exc.code != 404:
      raise
  if any(p['id'] == profile['id'] for p in profiles):
    raise ValueError('Runtime release identity is immutable')
  raw = canonical({'schema': 1, 'product': 'mobilepilot-oneplus9-runtime', 'sequence': sequence,
                   'profiles': [*profiles[-15:], profile]})
  signature = key.sign(DOMAIN + raw)
  public.verify(signature, DOMAIN + raw)
  output.write_bytes(canonical({'payload': base64.b64encode(raw).decode(),
                               'signature': base64.b64encode(signature).decode(), 'certificate': cert}))


if __name__ == '__main__':
  p = argparse.ArgumentParser()
  p.add_argument('--profile', type=Path, required=True)
  p.add_argument('--certificate', type=Path, required=True)
  p.add_argument('--sequence', type=int, required=True)
  p.add_argument('--output', type=Path, required=True)
  a = p.parse_args(); sign(json.loads(a.profile.read_text()), json.loads(a.certificate.read_text()), a.sequence, a.output)
