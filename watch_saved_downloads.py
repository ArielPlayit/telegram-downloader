import asyncio
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

from telethon import TelegramClient

from src.services.download_engine import DownloadEngine, GlobalSpeedLimiter, has_media, target_name_for_message
from src.services.state_repository import WatcherStateRepository

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.py"
LEGACY_STATE_FILE = ROOT / "downloads" / ".saved_watcher_state.json"
STATE_DB_FILE = ROOT / "downloads" / ".saved_watcher_state.db"

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


def queue_message_for_retry(message_id: int) -> None:
    repo = WatcherStateRepository(STATE_DB_FILE, legacy_state_path=LEGACY_STATE_FILE)
    repo.add_pending_id(int(message_id))


def emit_log(on_log: Optional[Callable[[str], None]], text: str) -> None:
    if on_log:
        on_log(text)
    else:
        print(text)


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

    state_repo = WatcherStateRepository(STATE_DB_FILE, legacy_state_path=LEGACY_STATE_FILE)

    session_path = ROOT / cfg["session_name"]
    client = TelegramClient(str(session_path), cfg["api_id"], cfg["api_hash"])

    last_seen_id = state_repo.load_last_seen_id()
    pending_ids: Set[int] = set(state_repo.load_pending_ids())
    queued_ids: Set[int] = set()
    active_ids: Set[int] = set()

    queue: asyncio.Queue[Any] = asyncio.Queue()
    speed_limiter = GlobalSpeedLimiter(int(cfg["max_download_speed_kbps"]))
    engine = DownloadEngine(client=client, download_dir=download_dir, speed_limiter=speed_limiter)
    max_workers = max(1, int(cfg["max_concurrent_downloads"]))

    await client.start()
    emit_log(on_log, "[watcher] started. monitoring Saved Messages...")

    try:
        if last_seen_id == 0:
            recent = await client.get_messages("me", limit=1)
            if recent:
                last_seen_id = int(recent[0].id)
                state_repo.save_last_seen_id(last_seen_id)
                emit_log(on_log, f"[watcher] initialized at message id {last_seen_id}")

        async def enqueue_pending_from_state() -> None:
            nonlocal pending_ids
            persisted = set(state_repo.load_pending_ids())
            pending_ids.update(persisted)

            missing_ids = sorted(pending_ids.difference(queued_ids).difference(active_ids))
            if not missing_ids:
                return

            recovered_msgs = await client.get_messages("me", ids=missing_ids)
            for msg in recovered_msgs:
                if not msg or not has_media(msg):
                    continue
                msg_id = int(msg.id)
                if msg_id in queued_ids or msg_id in active_ids:
                    continue
                queued_ids.add(msg_id)
                await queue.put(msg)
                name = target_name_for_message(msg)
                emit_log(on_log, f"[watcher] recovered queued message {msg_id}")
                if on_download_queued:
                    on_download_queued(msg_id, name)

        async def enqueue_new_messages() -> None:
            nonlocal last_seen_id

            new_messages: list[Any] = []
            async for msg in client.iter_messages("me", min_id=last_seen_id, reverse=True):
                new_messages.append(msg)

            for msg in new_messages:
                msg_id = int(msg.id)
                if not has_media(msg):
                    last_seen_id = max(last_seen_id, msg_id)
                    continue
                if msg_id in queued_ids or msg_id in active_ids:
                    last_seen_id = max(last_seen_id, msg_id)
                    continue

                queued_ids.add(msg_id)
                pending_ids.add(msg_id)
                state_repo.add_pending_id(msg_id)
                await queue.put(msg)

                name = target_name_for_message(msg)
                emit_log(on_log, f"[watcher] queued message {msg_id}")
                if on_download_queued:
                    on_download_queued(msg_id, name)

                last_seen_id = max(last_seen_id, msg_id)

            state_repo.save_last_seen_id(last_seen_id)

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
                    path = await engine.download_message_media(
                        msg,
                        on_log=on_log,
                        on_progress=on_progress,
                    )
                    if on_download_done:
                        on_download_done(msg_id, path)

                    retry_counts.pop(msg_id, None)
                    pending_ids.discard(msg_id)
                    queued_ids.discard(msg_id)
                    state_repo.remove_pending_id(msg_id)
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
                        state_repo.remove_pending_id(msg_id)
                        if on_download_failed:
                            on_download_failed(msg_id, name, str(exc))
                finally:
                    active_ids.discard(msg_id)
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(max_workers)]
        emit_log(on_log, f"[watcher] workers: {max_workers}, speed cap: {cfg['max_download_speed_kbps']} KB/s")

        while True:
            if stop_check():
                emit_log(on_log, "[watcher] stop requested")
                break

            await enqueue_pending_from_state()
            await enqueue_new_messages()

            sleep_seconds = max(2, int(cfg["watch_poll_seconds"]))
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

        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        state_repo.save_last_seen_id(last_seen_id)
        state_repo.set_pending_ids(pending_ids)
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[watcher] stopped")
