import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Optional

from telethon import TelegramClient

from src.services.integrity_service import verify_download_integrity

ProgressCallback = Callable[[int, str, int, int, float, float, float], None]


class DownloadPausedError(Exception):
    pass


class DownloadCancelledError(Exception):
    pass


def has_media(message: Any) -> bool:
    return bool(getattr(message, "file", None) or getattr(message, "media", None))


def target_name_for_message(message: Any) -> str:
    file_obj = getattr(message, "file", None)
    if file_obj and getattr(file_obj, "name", None):
        return str(file_obj.name)
    return f"telegram_{message.id}"


class GlobalSpeedLimiter:
    def __init__(self, speed_kbps: int) -> None:
        self.speed_bps = max(0, int(speed_kbps)) * 1024
        self._lock = asyncio.Lock()
        self._next_at = time.monotonic()

    async def throttle(self, chunk_size: int) -> None:
        if self.speed_bps <= 0 or chunk_size <= 0:
            return

        async with self._lock:
            now = time.monotonic()
            available_at = max(now, self._next_at)
            self._next_at = available_at + (float(chunk_size) / float(self.speed_bps))
            delay = available_at - now

        if delay > 0:
            await asyncio.sleep(delay)


class DownloadEngine:
    def __init__(self, client: TelegramClient, download_dir: Path, speed_limiter: Optional[GlobalSpeedLimiter] = None) -> None:
        self.client = client
        self.download_dir = download_dir
        self.speed_limiter = speed_limiter

    @staticmethod
    def _emit_log(on_log: Optional[Callable[[str], None]], text: str) -> None:
        if on_log:
            on_log(text)
        else:
            print(text)

    @staticmethod
    def _emit_progress(
        message_id: int,
        name: str,
        current: int,
        total: int,
        started_at: float,
        base_downloaded: int,
        on_progress: Optional[ProgressCallback],
    ) -> None:
        elapsed = max(0.001, time.monotonic() - started_at)
        transferred_now = max(0, current - base_downloaded)
        speed_bps = transferred_now / elapsed

        pct = 0.0
        eta_seconds = -1.0
        if total > 0:
            pct = (current / total) * 100
            remaining = max(0, total - current)
            if speed_bps > 0:
                eta_seconds = remaining / speed_bps

        if on_progress:
            on_progress(message_id, name, current, total, pct, speed_bps / 1024.0, eta_seconds)
        else:
            if total > 0:
                print(f"\r[watcher] {name} {pct:.1f}%", end="", flush=True)
            else:
                done_mb = current / (1024 * 1024)
                print(f"\r[watcher] {name} {done_mb:.2f} MB", end="", flush=True)

    async def download_message_media(
        self,
        message: Any,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[ProgressCallback] = None,
        should_pause: Optional[Callable[[int], bool]] = None,
        should_cancel: Optional[Callable[[int], bool]] = None,
    ) -> Path:
        target = self.download_dir / target_name_for_message(message)
        if getattr(message, "media", None) and getattr(message.media, "document", None):
            return await self._resumable_download_document(
                message,
                target,
                on_log=on_log,
                on_progress=on_progress,
                should_pause=should_pause,
                should_cancel=should_cancel,
            )

        return await self._resumable_download_generic(
            message,
            target,
            on_log=on_log,
            on_progress=on_progress,
            should_pause=should_pause,
            should_cancel=should_cancel,
        )

    async def _resumable_download_document(
        self,
        message: Any,
        final_path: Path,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[ProgressCallback] = None,
        should_pause: Optional[Callable[[int], bool]] = None,
        should_cancel: Optional[Callable[[int], bool]] = None,
    ) -> Path:
        message_id = int(message.id)
        doc = message.media.document
        total = int(getattr(doc, "size", 0) or 0)

        if final_path.exists() and total > 0 and final_path.stat().st_size == total:
            self._emit_log(on_log, f"[watcher] already complete: {final_path.name}")
            return final_path

        part_path = final_path.with_suffix(final_path.suffix + ".part")
        downloaded = part_path.stat().st_size if part_path.exists() else 0

        if total > 0 and downloaded > total:
            part_path.unlink(missing_ok=True)
            downloaded = 0

        if downloaded > 0:
            mb_done = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024) if total else 0
            self._emit_log(on_log, f"[watcher] resuming {final_path.name}: {mb_done:.2f}/{mb_total:.2f} MB")

        mode = "ab" if downloaded > 0 else "wb"
        started = time.monotonic()
        stream_hasher = hashlib.sha256()

        if downloaded > 0 and part_path.exists():
            with part_path.open("rb") as existing_fh:
                while True:
                    existing_chunk = existing_fh.read(1024 * 1024)
                    if not existing_chunk:
                        break
                    stream_hasher.update(existing_chunk)

        try:
            with part_path.open(mode) as fh:
                current = downloaded
                async for chunk in self.client.iter_download(doc, offset=downloaded):
                    if should_cancel and should_cancel(message_id):
                        raise DownloadCancelledError(f"Cancelled message {message_id}")
                    if should_pause and should_pause(message_id):
                        raise DownloadPausedError(f"Paused message {message_id}")

                    fh.write(chunk)
                    stream_hasher.update(chunk)
                    current += len(chunk)
                    self._emit_progress(
                        message_id,
                        final_path.name,
                        current,
                        total,
                        started_at=started,
                        base_downloaded=downloaded,
                        on_progress=on_progress,
                    )
                    if self.speed_limiter:
                        await self.speed_limiter.throttle(len(chunk))
        except DownloadCancelledError:
            part_path.unlink(missing_ok=True)
            raise

        if total and part_path.stat().st_size != total:
            raise RuntimeError(f"Incomplete download for {final_path.name}")

        if final_path.exists():
            final_path.unlink()
        part_path.rename(final_path)

        sha256 = verify_download_integrity(final_path, total, stream_hasher.hexdigest())
        self._emit_log(on_log, f"[watcher] integrity ok: {final_path.name} sha256={sha256}")
        self._emit_log(on_log, f"[watcher] downloaded: {final_path}")
        return final_path

    async def _resumable_download_generic(
        self,
        message: Any,
        target: Path,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[ProgressCallback] = None,
        should_pause: Optional[Callable[[int], bool]] = None,
        should_cancel: Optional[Callable[[int], bool]] = None,
    ) -> Path:
        message_id = int(message.id)
        total = int(getattr(getattr(message, "file", None), "size", 0) or 0)
        if target.exists() and total > 0 and target.stat().st_size == total:
            self._emit_log(on_log, f"[watcher] already complete: {target.name}")
            return target

        part_path = target.with_suffix(target.suffix + ".part")
        downloaded = part_path.stat().st_size if part_path.exists() else 0
        if total > 0 and downloaded > total:
            part_path.unlink(missing_ok=True)
            downloaded = 0

        started = time.monotonic()
        mode = "ab" if downloaded > 0 else "wb"
        media_ref = getattr(message, "media", None)
        if not media_ref:
            raise RuntimeError("No media found in message")

        stream_hasher = hashlib.sha256()
        if downloaded > 0 and part_path.exists():
            with part_path.open("rb") as existing_fh:
                while True:
                    existing_chunk = existing_fh.read(1024 * 1024)
                    if not existing_chunk:
                        break
                    stream_hasher.update(existing_chunk)

        try:
            with part_path.open(mode) as fh:
                current = downloaded
                async for chunk in self.client.iter_download(media_ref, offset=downloaded):
                    if should_cancel and should_cancel(message_id):
                        raise DownloadCancelledError(f"Cancelled message {message_id}")
                    if should_pause and should_pause(message_id):
                        raise DownloadPausedError(f"Paused message {message_id}")

                    fh.write(chunk)
                    stream_hasher.update(chunk)
                    current += len(chunk)
                    self._emit_progress(
                        message_id,
                        target.name,
                        current,
                        total,
                        started_at=started,
                        base_downloaded=downloaded,
                        on_progress=on_progress,
                    )
                    if self.speed_limiter:
                        await self.speed_limiter.throttle(len(chunk))
        except DownloadCancelledError:
            part_path.unlink(missing_ok=True)
            raise

        if total and part_path.stat().st_size != total:
            raise RuntimeError(f"Incomplete download for {target.name}")

        if target.exists():
            target.unlink()
        part_path.rename(target)

        sha256 = verify_download_integrity(target, total, stream_hasher.hexdigest())
        self._emit_log(on_log, f"[watcher] integrity ok: {target.name} sha256={sha256}")
        self._emit_log(on_log, f"[watcher] downloaded: {target}")
        return target
