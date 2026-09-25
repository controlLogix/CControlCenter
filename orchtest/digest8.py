"""Deterministic eight-character digests using only the standard library.

TM-090 criterion 3 cannot be satisfied: eight hex characters provide only
2**32 outputs, so distinct arbitrary-length byte inputs must collide by the
pigeonhole principle. This digest does not guarantee uniqueness and must not
be used where collision resistance is required.

For example, the distinct inputs 000000000000c66f and 000000000000e658
(hexadecimal bytes) both return "7357966a". A longer fixed-length digest
reduces collision risk but still cannot guarantee uniqueness for all bytes.
"""

import hashlib


def digest8(data: bytes) -> str:
    """Return the first eight lowercase hex characters of SHA-256(data)."""
    return hashlib.sha256(data).hexdigest()[:8]
