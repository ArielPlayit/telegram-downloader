import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

from telethon import TelegramClient

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.py"
STATE_FILE = ROOT / "downloads" / ".saved_watcher_state.json"

ProgressCallback = Callable[[int, str, int, int, float, float, float], None]


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise RuntimeError("Missing config.py")

    namespace: Dict[str, Any] = {}
    exec(CONFIG_FILE.read_text(encoding="utf-8"), namespace)

    api_id = int(namespace.get("API_ID", 0))
    api_hash = str(namespace.get("API_HASH", "")).strip()
    if not api_id or not api_hash or api_hash == "YOUR_API_HASH_HERE":
        raise RuntimeError("Invalid API credentials in config.py")

    return {
        "api_id": api_id,
        "api_hash": api_hash,
        "session_name": str(namespace.get("SESSION_NAME", "telegram_downloader")).strip() or "telegram_downloader",
        "download_path": str(namespace.get("DOWNLOAD_PATH", "./downloads/")).strip() or "./downloads/",
        "watch_poll_seconds": int(namespace.get("WATCH_POLL_SECONDS", 5)),
        "watch_enabled": bool(namespace.get("WATCH_SAVED_MESSAGES", True)),
        "max_concurrent_downloads": max(1, int(namespace.get("MAX_CONCURRENT_DOWNLOADS", 1))),
        "max_download_speed_kbps": max(0, int(namespace.get("MAX_DOWNLOAD_SPEED_KBPS", 0))),
    }


def has_media(message: Any) -> bool:
    return bool(getattr(message, "file", None) or getattr(message, "media", None))


def target_name_for_message(message: Any) -> str:
    file_obj = getattr(message, "file", None)
    if file_obj and getattr(file_obj, "name", None):
        return str(file_obj.name)
    return f"telegram_{message.id}"


def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {"last_seen_id": 0, "pending_ids": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if "last_seen_id" not in data:
            # Backward compatibility with old state shape.
            data = {
                "last_seen_id": int(data.get("last_id", 0)),
                "pending_ids": list(data.get("pending_ids", [])),
            }
        data["last_seen_id"] = int(data.get("last_seen_id", 0))
        data["pending_ids"] = [int(x) for x in data.get("pending_ids", [])]
        return data
    except Exception:
        return {"last_seen_id": 0, "pending_ids": []}


def save_state(last_seen_id: int, pending_ids: Set[int]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_seen_id": int(last_seen_id),
        "pending_ids": sorted(int(x) for x in pending_ids),
    }
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def queue_message_for_retry(message_id: int) -> None:
    state = load_state()
    last_seen_id = int(state.get("last_seen_id", 0))
    pending_ids = set(int(x) for x in state.get("pending_ids", []))
    pending_ids.add(int(message_id))
    save_state(last_seen_id, pending_ids)


def emit_log(on_log: Optional[Callable[[str], None]], text: str) -> None:
    if on_log:
        on_log(text)
    else:
        print(text)


def compute_file_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


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


def print_progress(
    message_id: int,
    name: str,
    current: int,
    total: int,
    started_at: float,
    base_downloaded: int,
    on_progress: Optional[ProgressCallback] = None,
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


async def resumable_download_document(
    client: TelegramClient,
    message: Any,
    final_path: Path,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[ProgressCallback] = None,
    speed_limiter: Optional[GlobalSpeedLimiter] = None,
) -> Path:
    doc = message.media.document
    total = int(getattr(doc, "size", 0) or 0)

    if final_path.exists() and total > 0 and final_path.stat().st_size == total:
        emit_log(on_log, f"[watcher] already complete: {final_path.name}")
        return final_path

    part_path = final_path.with_suffix(final_path.suffix + ".part")
    downloaded = part_path.stat().st_size if part_path.exists() else 0

    if total > 0 and downloaded > total:
        part_path.unlink(missing_ok=True)
        downloaded = 0

    if downloaded > 0:
        mb_done = downloaded / (1024 * 1024)
        mb_total = total / (1024 * 1024) if total else 0
        emit_log(on_log, f"[watcher] resuming {final_path.name}: {mb_done:.2f}/{mb_total:.2f} MB")

    mode = "ab" if downloaded > 0 else "wb"
    started = time.monotonic()
    stream_hasher = hashlib.sha256()

    if downloaded > 0 and part_path.exists():
        # Rebuild the rolling hash with already downloaded bytes before appending.
        with part_path.open("rb") as existing_fh:
            while True:
                existing_chunk = existing_fh.read(1024 * 1024)
                if not existing_chunk:
                    break
                stream_hasher.update(existing_chunk)

    with part_path.open(mode) as fh:
        current = downloaded
        async for chunk in client.iter_download(doc, offset=downloaded):
            fh.write(chunk)
            stream_hasher.update(chunk)
            current += len(chunk)
            print_progress(
                int(message.id),
                final_path.name,
                current,
                total,
                started_at=started,
                base_downloaded=downloaded,
                on_progress=on_progress,
            )
            if speed_limiter:
                await speed_limiter.throttle(len(chunk))

    if total and part_path.stat().st_size != total:
        raise RuntimeError(f"Incomplete download for {final_path.name}")

    if final_path.exists():
        final_path.unlink()
    part_path.rename(final_path)

    if total > 0 and final_path.stat().st_size != total:
        raise RuntimeError(f"Integrity check failed for {final_path.name}: unexpected final size")

    stream_sha256 = stream_hasher.hexdigest()
    file_sha256 = compute_file_sha256(final_path)
    if stream_sha256 != file_sha256:
        raise RuntimeError(f"Integrity check failed for {final_path.name}: sha256 mismatch")

    emit_log(on_log, f"[watcher] integrity ok: {final_path.name} sha256={file_sha256}")
    emit_log(on_log, f"[watcher] downloaded: {final_path}")
    return final_path


async def download_message_media(
    client: TelegramClient,
    message: Any,
    download_dir: Path,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[ProgressCallback] = None,
    speed_limiter: Optional[GlobalSpeedLimiter] = None,
) -> Path:
    target = download_dir / target_name_for_message(message)

    if getattr(message, "media", None) and getattr(message.media, "document", None):
        return await resumable_download_document(
            client,
            message,
            target,
            on_log=on_log,
            on_progress=on_progress,
            speed_limiter=speed_limiter,
        )

    # Generic resumable download path for photos/other media.
    total = int(getattr(getattr(message, "file", None), "size", 0) or 0)
    if target.exists() and total > 0 and target.stat().st_size == total:
        emit_log(on_log, f"[watcher] already complete: {target.name}")
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

    with part_path.open(mode) as fh:
        current = downloaded
        async for chunk in client.iter_download(media_ref, offset=downloaded):
            fh.write(chunk)
            stream_hasher.update(chunk)
            current += len(chunk)
            print_progress(
                int(message.id),
                target.name,
                current,
                total,
                started_at=started,
                base_downloaded=downloaded,
                on_progress=on_progress,
            )
            if speed_limiter:
                await speed_limiter.throttle(len(chunk))

    if total and part_path.stat().st_size != total:
        raise RuntimeError(f"Incomplete download for {target.name}")

    if target.exists():
        target.unlink()
    part_path.rename(target)

    if total > 0 and target.stat().st_size != total:
        raise RuntimeError(f"Integrity check failed for {target.name}: unexpected final size")

    stream_sha256 = stream_hasher.hexdigest()
    file_sha256 = compute_file_sha256(target)
    if stream_sha256 != file_sha256:
        raise RuntimeError(f"Integrity check failed for {target.name}: sha256 mismatch")

    emit_log(on_log, f"[watcher] integrity ok: {target.name} sha256={file_sha256}")
    emit_log(on_log, f"[watcher] downloaded: {target}")
    return target


async def run(
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[ProgressCallback] = None,
    on_download_queued: Optional[Callable[[int, str], None]] = None,
    on_download_start: Optional[Callable[[int, str], None]] = None,
    on_download_done: Optional[Callable[[int, Path], None]] = None,
    on_download_failed: Optional[Callable[[int, str, str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> None:
    stop_check = should_stop or (lambda: False)
    cfg = load_config()
    if not cfg["watch_enabled"]:
        raise RuntimeError("WATCH_SAVED_MESSAGES is disabled in config.py")

    download_dir = Path(os.path.expandvars(cfg["download_path"]).strip()).expanduser().resolve()
    download_dir.mkdir(parents=True, exist_ok=True)

    session_path = ROOT / cfg["session_name"]
    client = TelegramClient(str(session_path), cfg["api_id"], cfg["api_hash"])

    state = load_state()
    last_seen_id = int(state.get("last_seen_id", 0))
    pending_ids: Set[int] = set(int(x) for x in state.get("pending_ids", []))
    active_ids: Set[int] = set()
    queued_ids: Set[int] = set()
    queue: asyncio.Queue[Any] = asyncio.Queue()
    max_workers = max(1, int(cfg["max_concurrent_downloads"]))
    speed_limit_kbps = max(0, int(cfg["max_download_speed_kbps"]))
    speed_limiter = GlobalSpeedLimiter(speed_limit_kbps)

    await client.start()
    emit_log(on_log, "[watcher] started. monitoring Saved Messages...")

    try:
        if last_seen_id == 0:
            recent = await client.get_messages("me", limit=1)
            if recent:
                last_seen_id = recent[0].id
                save_state(last_seen_id, pending_ids)
                emit_log(on_log, f"[watcher] initialized at message id {last_seen_id}")

        if pending_ids:
            recovered_msgs = await client.get_messages("me", ids=list(sorted(pending_ids)))
            for msg in recovered_msgs:
                if msg and has_media(msg):
                    queued_ids.add(int(msg.id))
                    await queue.put(msg)
                    name = target_name_for_message(msg)
                    emit_log(on_log, f"[watcher] recovered queued message {msg.id}")
                    if on_download_queued:
                        on_download_queued(msg.id, name)

        async def enqueue_missing_pending() -> None:
            missing_ids = sorted(pending_ids.difference(queued_ids).difference(active_ids))
            if not missing_ids:
                return
            recovered = await client.get_messages("me", ids=missing_ids)
            for msg in recovered:
                if msg and has_media(msg):
                    msg_id = int(msg.id)
                    if msg_id in queued_ids or msg_id in active_ids:
                        continue
                    queued_ids.add(msg_id)
                    await queue.put(msg)
                    name = target_name_for_message(msg)
                    emit_log(on_log, f"[watcher] recovered queued message {msg_id}")
                    if on_download_queued:
                        on_download_queued(msg_id, name)

        retry_counts: Dict[int, int] = {}

        async def worker() -> None:
            while True:
                if stop_check() and queue.empty():
                    return
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                msg_id = int(msg.id)
                name = target_name_for_message(msg)
                active_ids.add(msg_id)
                if on_download_start:
                    on_download_start(msg_id, name)
                try:
                    path = await download_message_media(
                        client,
                        msg,
                        download_dir,
                        on_log=on_log,
                        on_progress=on_progress,
                        speed_limiter=speed_limiter,
                    )
                    if on_download_done:
                        on_download_done(msg_id, path)
                    retry_counts.pop(msg_id, None)
                    pending_ids.discard(msg_id)
                    queued_ids.discard(msg_id)
                    save_state(last_seen_id, pending_ids)
                except Exception as exc:
                    emit_log(on_log, f"[watcher] failed message {msg_id}: {exc}")
                    attempts = retry_counts.get(msg_id, 0) + 1
                    retry_counts[msg_id] = attempts
                    if attempts <= 3 and not stop_check():
                        emit_log(on_log, f"[watcher] retrying message {msg_id} (attempt {attempts}/3)")
                        await asyncio.sleep(2)
                        await queue.put(msg)
                    else:
                        emit_log(on_log, f"[watcher] giving up message {msg_id} after retries")
                        pending_ids.discard(msg_id)
                        queued_ids.discard(msg_id)
                        save_state(last_seen_id, pending_ids)
                        if on_download_failed:
                            on_download_failed(msg_id, name, str(exc))
                finally:
                    active_ids.discard(msg_id)
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(max_workers)]
        emit_log(on_log, f"[watcher] workers: {max_workers}, speed cap: {speed_limit_kbps} KB/s")

        while True:
            if stop_check():
                emit_log(on_log, "[watcher] stop requested")
                break

            external_state = load_state()
            for ext_id in external_state.get("pending_ids", []):
                pending_ids.add(int(ext_id))
            await enqueue_missing_pending()

            msgs = await client.get_messages("me", limit=50)
            previous_seen = last_seen_id
            for msg in reversed(msgs):
                msg_id = int(msg.id)
                if msg_id > previous_seen and has_media(msg):
                    if msg_id in queued_ids or msg_id in active_ids:
                        continue
                    queued_ids.add(msg_id)
                    pending_ids.add(msg_id)
                    await queue.put(msg)
                    name = target_name_for_message(msg)
                    emit_log(on_log, f"[watcher] queued message {msg_id}")
                    if on_download_queued:
                        on_download_queued(msg_id, name)
                last_seen_id = max(last_seen_id, msg_id)

            if last_seen_id != previous_seen:
                save_state(last_seen_id, pending_ids)

            sleep_seconds = max(2, cfg["watch_poll_seconds"])
            for _ in range(sleep_seconds):
                if stop_check():
                    break
                await asyncio.sleep(1)

            if stop_check():
                emit_log(on_log, "[watcher] stop requested")
                break

        if not queue.empty():
            emit_log(on_log, "[watcher] waiting queued downloads to finish...")
            await queue.join()

        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        save_state(last_seen_id, pending_ids)
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[watcher] stopped")
