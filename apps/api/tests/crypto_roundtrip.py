#!/usr/bin/env python3
"""FieldCipher round trips, nonce freshness, blind-index determinism, key handling and
account masking, with no database. Prints CRYPTO_ROUNDTRIP_PASS."""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.crypto import FieldCipher, KeyError_, load_key, mask_account  # noqa: E402

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(f"{name}: {detail}")


KEY = os.urandom(32)
OTHER = os.urandom(32)
cipher = FieldCipher(KEY)
other = FieldCipher(OTHER)

SAMPLES = ["28203305911193", "HDFCH3166652372", "8cd0326074aaf340997a20be63cc537b==",
           "मुंबई खाता ₹ 1234", "naïve café", "a", " leading and trailing ", "x" * 5000, ""]
for s in SAMPLES:
    token = cipher.encrypt(s)
    check(f"round trip {s[:16]!r}", cipher.decrypt(token) == s)
    if s:
        check(f"ciphertext differs from plaintext {s[:16]!r}", token != s and s not in token)
        check(f"ciphertext is base64 {s[:16]!r}", base64.b64decode(token, validate=True) is not None)
    else:
        check("empty string encrypts to empty", token == "")

t1, t2 = cipher.encrypt("28203305911193"), cipher.encrypt("28203305911193")
check("two encryptions of one value differ (fresh nonce)", t1 != t2)
check("nonces differ", base64.b64decode(t1)[:12] != base64.b64decode(t2)[:12])
check("both decrypt to the same value", cipher.decrypt(t1) == cipher.decrypt(t2) == "28203305911193")

h = cipher.blind_index("8cd0326074aaf340997a20be63cc537b==")
check("blind index is deterministic", h == cipher.blind_index("8cd0326074aaf340997a20be63cc537b=="))
check("blind index is case-normalised", h == cipher.blind_index("8CD0326074AAF340997A20BE63CC537B=="))
check("blind index ignores whitespace", h == cipher.blind_index(" 8cd0 3260 74aaf340997a20be63cc537b== \n"))
check("blind index is 64 hex chars", len(h) == 64 and all(c in "0123456789abcdef" for c in h))
check("blind index differs for a different value", h != cipher.blind_index("8cd0326074aaf340997a20be63cc537c=="))
check("blind index differs under a different key", h != other.blind_index("8cd0326074aaf340997a20be63cc537b=="))
check("blind index of blank is empty", cipher.blind_index("   ") == "" and cipher.blind_index("") == "")
check("blind index never equals the plaintext", h != "8cd0326074aaf340997a20be63cc537b==")

try:
    other.decrypt(t1)
    check("wrong key decrypt raises", False, "decrypted under the wrong key")
except ValueError:
    check("wrong key decrypt raises", True)

blob = bytearray(base64.b64decode(t1))
blob[-1] ^= 0x01
try:
    cipher.decrypt(base64.b64encode(bytes(blob)).decode())
    check("tampered tag raises", False, "tampered ciphertext decrypted")
except ValueError:
    check("tampered tag raises", True)
blob = bytearray(base64.b64decode(t1))
blob[12] ^= 0x80
try:
    cipher.decrypt(base64.b64encode(bytes(blob)).decode())
    check("tampered body raises", False, "tampered ciphertext decrypted")
except ValueError:
    check("tampered body raises", True)
for junk in ("not base64!!", "AAAA", base64.b64encode(b"short").decode()):
    try:
        cipher.decrypt(junk)
        check(f"garbage token raises {junk!r}", False, "decrypted garbage")
    except ValueError:
        check(f"garbage token raises {junk!r}", True)

for bad in ("", "abc", "0" * 63, "0" * 65, "g" * 64, "0" * 128):
    try:
        load_key(bad)
        check(f"load_key rejects {bad[:8]!r} (len {len(bad)})", False, "accepted")
    except KeyError_:
        check(f"load_key rejects {bad[:8]!r} (len {len(bad)})", True)
good = "0123456789abcdef" * 4
check("load_key accepts 64 hex chars", load_key(good) == bytes.fromhex(good))
check("load_key strips whitespace", load_key(f"  {good}\n") == bytes.fromhex(good))
os.environ["TBX_DATA_KEY"] = good
check("load_key reads the environment", load_key() == bytes.fromhex(good))
check("FieldCipher.from_env works", FieldCipher.from_env().decrypt(
    FieldCipher(bytes.fromhex(good)).encrypt("x")) == "x")
for n in (16, 31, 33):
    try:
        FieldCipher(os.urandom(n))
        check(f"FieldCipher rejects {n}-byte key", False, "accepted")
    except KeyError_:
        check(f"FieldCipher rejects {n}-byte key", True)

check("mask_account keeps last four", mask_account("28203305911193") == "XXXXXXXXXX1193")
check("mask_account strips whitespace", mask_account(" 12345678 ") == "XXXX5678")
check("mask_account of short value is all X", mask_account("1234") == "XXXX" and mask_account("12") == "XX")
check("mask_account of empty is empty", mask_account("") == "")
check("mask_account never contains the full number",
      all("28203305911193" not in mask_account("28203305911193") for _ in range(1)))

print(f"crypto checks run: {checks}")
if failures:
    print(f"FAILURES ({len(failures)}):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("CRYPTO_ROUNDTRIP_PASS")
