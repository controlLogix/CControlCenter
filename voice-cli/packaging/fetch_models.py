"""Put the Whisper models the app ships with into <dest>/<name>/, verified by SHA-256.

    uv run python packaging/fetch_models.py dist/VoiceCLI/models

Each model is pinned to a Hugging Face commit and every file to a checksum, so a build
never ships something different from what was reviewed. Files already in the local
Hugging Face cache are reused; anything else is downloaded at the pinned revision.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

MODELS = {
    "small.en": ("Systran/faster-whisper-small.en", "d1d751a5f8271d482d14ca55d9e2deeebbae577f", {
        "config.json": "666a9605530ac1f61fa8177f3702b4dacec9966749e42610839fcc32661d5fae",
        "model.bin": "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a",
        "tokenizer.json": "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df",
        "vocabulary.txt": "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf",
    }),
    "base.en": ("Systran/faster-whisper-base.en", "3d3d5dee26484f91867d81cb899cfcf72b96be6c", {
        "config.json": "f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb",
        "model.bin": "2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef",
        "tokenizer.json": "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df",
        "vocabulary.txt": "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf",
    }),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name: str, dest: Path) -> None:
    from huggingface_hub import snapshot_download

    repo, revision, files = MODELS[name]
    out = dest / name
    if out.is_dir() and all((out / f).is_file() and sha256(out / f) == digest for f, digest in files.items()):
        print(f"{name}: already in place")
        return
    try:
        src = Path(snapshot_download(repo, revision=revision, allow_patterns=list(files), local_files_only=True))
        print(f"{name}: from the local cache")
    except Exception:
        print(f"{name}: downloading {repo}@{revision[:10]}")
        src = Path(snapshot_download(repo, revision=revision, allow_patterns=list(files)))
    out.mkdir(parents=True, exist_ok=True)
    for f, digest in files.items():
        shutil.copyfile(src / f, out / f)
        actual = sha256(out / f)
        if actual != digest:
            raise SystemExit(f"{name}/{f}: checksum {actual} does not match the pinned {digest}")
    print(f"{name}: verified")


def main() -> None:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "models")
    for name in MODELS:
        fetch(name, dest)


if __name__ == "__main__":
    main()
