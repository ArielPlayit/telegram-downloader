import hashlib
from pathlib import Path


def compute_file_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_download_integrity(file_path: Path, total_size: int, stream_sha256: str) -> str:
    if total_size > 0 and file_path.stat().st_size != total_size:
        raise RuntimeError(f"Integrity check failed for {file_path.name}: unexpected final size")

    disk_sha256 = compute_file_sha256(file_path)
    if stream_sha256 != disk_sha256:
        raise RuntimeError(f"Integrity check failed for {file_path.name}: sha256 mismatch")

    return disk_sha256
