"""Ed25519 (RFC 8032) signatures for the update manifest, in plain Python.

The app only verifies, which involves no secret, so a big-integer reference
implementation is safe and avoids bundling a native crypto library. Signing
runs once per release on CI with the key from the `UPDATE_SIGNING_KEY` secret.

Create a key pair (keep the printed private file out of Git and backed up):
    python update_signing.py keygen local/update-signing-key.txt
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, -1, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _add(a, b):
    """Point addition in extended coordinates (X, Y, Z, T)."""
    x = (a[1] - a[0]) * (b[1] - b[0]) % P
    y = (a[1] + a[0]) * (b[1] + b[0]) % P
    c = 2 * a[3] * b[3] * D % P
    z = 2 * a[2] * b[2] % P
    e, f, g, h = y - x, z - c, z + c, y + x
    return e * f % P, g * h % P, f * g % P, e * h % P


def _multiply(scalar, point):
    result = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _equal(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, -1, P) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    return P - x if (x & 1) != sign else x


_BASE_Y = 4 * pow(5, -1, P) % P
_BASE_X = _recover_x(_BASE_Y, 0)
BASE = (_BASE_X, _BASE_Y, 1, _BASE_X * _BASE_Y % P)


def _compress(point):
    z = pow(point[2], -1, P)
    x, y = point[0] * z % P, point[1] * z % P
    return (y | (x & 1) << 255).to_bytes(32, 'little')


def _decompress(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, 'little')
    x = _recover_x(y & (1 << 255) - 1, y >> 255)
    if x is None:
        return None
    y &= (1 << 255) - 1
    return x, y, 1, x * y % P


def _hash(data):
    return int.from_bytes(hashlib.sha512(data).digest(), 'little')


def _expand(seed):
    if len(seed) != 32:
        raise ValueError('Ed25519 private key must be 32 bytes')
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], 'little') & (1 << 254) - 8 | 1 << 254
    return scalar, digest[32:]


def public_key(seed):
    return _compress(_multiply(_expand(seed)[0], BASE))


def sign(seed, message):
    scalar, prefix = _expand(seed)
    public = _compress(_multiply(scalar, BASE))
    r = _hash(prefix + message) % L
    point = _compress(_multiply(r, BASE))
    s = (r + _hash(point + public + message) % L * scalar) % L
    return point + s.to_bytes(32, 'little')


def verify(public, message, signature):
    """True only for a valid signature; malformed input is simply invalid."""
    if len(public) != 32 or len(signature) != 64:
        return False
    key, point = _decompress(public), _decompress(signature[:32])
    s = int.from_bytes(signature[32:], 'little')
    if key is None or point is None or s >= L:
        return False
    h = _hash(signature[:32] + public + message) % L
    return _equal(_multiply(s, BASE), _add(point, _multiply(h, key)))


def keygen(path):
    """Write a new private key (hex) to `path` and return the public key (hex)."""
    import secrets
    path = Path(path)
    if path.exists():
        raise SystemExit(f'{path} already exists; refusing to overwrite a signing key.')
    seed = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(seed.hex() + '\n', encoding='ascii')
    return public_key(seed).hex()


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != 'keygen':
        raise SystemExit(__doc__)
    print('public key:', keygen(sys.argv[2]))
