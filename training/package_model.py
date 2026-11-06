"""Package a trained model reproducibly, checksum it, and/or publish it to object storage.

  pack:    training/out/v1 -> dist/model-v1.tar.gz + dist/model-v1.sha256
           (deterministic tar: sorted names, mtime 0, uid/gid 0, gzip mtime 0).
           model.sha256 = SHA-256 of that tarball, i.e. of the GitHub Release asset.
  upload:  extract tarball (verifying the checksum) and put every file under
           s3://models/<version>/, plus model.sha256 and the tarball itself.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pack(model_dir: Path, version: str, dist: Path) -> Path:
    dist.mkdir(parents=True, exist_ok=True)
    tar_path = dist / f"model-{version}.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for p in sorted(model_dir.rglob("*")):
            if p.is_file():
                info = tarfile.TarInfo(f"model-{version}/{p.relative_to(model_dir).as_posix()}")
                info.size, info.mtime, info.mode = p.stat().st_size, 0, 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                with p.open("rb") as f:
                    tar.addfile(info, f)
    with open(tar_path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write(buf.getvalue())
    digest = sha256(tar_path)
    (dist / f"model-{version}.sha256").write_text(f"{digest}  model-{version}.tar.gz\n")
    print(f"{tar_path}  sha256={digest}")
    return tar_path


def upload(tar_path: Path, version: str, bucket: str) -> None:
    from worker import s3util

    sha_file = tar_path.with_name(f"model-{version}.sha256")
    expected = sha_file.read_text().split()[0] if sha_file.exists() else None
    actual = sha256(tar_path)
    if expected and expected != actual:
        raise SystemExit(f"checksum mismatch: {actual} != {expected}")
    s3 = s3util.client()
    with tarfile.open(tar_path) as tar:
        for m in tar.getmembers():
            if m.isfile():
                rel = m.name.split("/", 1)[1]
                s3util.put_bytes(f"{bucket}/{version}/{rel}", tar.extractfile(m).read(), s3)
                print(f"put s3://{bucket}/{version}/{rel}")
    s3util.put_bytes(f"{bucket}/{version}/model.sha256", f"{actual}  {tar_path.name}\n".encode(), s3)
    s3util.put_bytes(f"{bucket}/{version}/{tar_path.name}", tar_path.read_bytes(), s3)
    print(f"put s3://{bucket}/{version}/model.sha256 ({actual})")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("--model-dir", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--dist", default="dist")
    u = sub.add_parser("upload")
    u.add_argument("--tar", required=True)
    u.add_argument("--version", required=True)
    u.add_argument("--bucket", default="models")
    a = ap.parse_args()
    if a.cmd == "pack":
        pack(Path(a.model_dir), a.version, Path(a.dist))
    else:
        upload(Path(a.tar), a.version, a.bucket)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("S3_ENDPOINT", "http://localhost:8333")
    sys.exit(main())
