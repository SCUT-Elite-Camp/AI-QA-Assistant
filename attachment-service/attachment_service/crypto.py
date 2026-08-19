from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


MAGIC = b"CP2ATT01"


def encrypt_file(source: Path, target: Path, key: bytes, aad: bytes) -> None:
    nonce = os.urandom(12)
    target.parent.mkdir(parents=True, exist_ok=True)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    with source.open("rb") as src, target.open("wb") as dst:
        dst.write(MAGIC)
        dst.write(nonce)
        dst.write(b"\0" * 16)
        while chunk := src.read(1024 * 1024):
            dst.write(encryptor.update(chunk))
        dst.write(encryptor.finalize())
        dst.seek(len(MAGIC) + len(nonce))
        dst.write(encryptor.tag)


def decrypt_file(source: Path, target: Path, key: bytes, aad: bytes) -> None:
    with source.open("rb") as src:
        if src.read(len(MAGIC)) != MAGIC:
            raise ValueError("invalid encrypted attachment")
        nonce = src.read(12)
        tag = src.read(16)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(aad)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(decryptor.update(chunk))
                dst.write(decryptor.finalize())
        except Exception:
            target.unlink(missing_ok=True)
            raise


def decrypt_bytes(source: Path, key: bytes, aad: bytes) -> bytes:
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(delete=False) as handle:
        temporary = Path(handle.name)
    try:
        decrypt_file(source, temporary, key, aad)
        return temporary.read_bytes()
    finally:
        temporary.unlink(missing_ok=True)
