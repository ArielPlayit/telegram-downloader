import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

from telethon import TelegramClient

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.py"
STATE_FILE = ROOT / "downloads" / ".saved_watcher_state.json"


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
        return {"last_id": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_id": 0}


def save_state(last_id: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"last_id": last_id}, ensure_ascii=True), encoding="utf-8")


def print_progress(name: str, current: int, total: int) -> None:
    if total <= 0:
        return
    pct = (current / total) * 100
    print(f"\r[watcher] {name} {pct:.1f}%", end="", flush=True)


async def resumable_download_document(client: TelegramClient, message: Any, final_path: Path) -> Path:
    doc = message.media.document
    total = int(getattr(doc, "size", 0) or 0)

    if final_path.exists() and total > 0 and final_path.stat().st_size == total:
        print(f"[watcher] already complete: {final_path.name}")
        return final_path

    part_path = final_path.with_suffix(final_path.suffix + ".part")
    downloaded = part_path.stat().st_size if part_path.exists() else 0

    if total > 0 and downloaded > total:
        part_path.unlink(missing_ok=True)
        downloaded = 0

    if downloaded > 0:
        mb_done = downloaded / (1024 * 1024)
        mb_total = total / (1024 * 1024) if total else 0
        print(f"[watcher] resuming {final_path.name}: {mb_done:.2f}/{mb_total:.2f} MB")

    mode = "ab" if downloaded > 0 else "wb"
    with part_path.open(mode) as fh:
        current = downloaded
        async for chunk in client.iter_download(doc, offset=downloaded):
            fh.write(chunk)
            current += len(chunk)
            print_progress(final_path.name, current, total)

    if total and part_path.stat().st_size != total:
        raise RuntimeError(f"Incomplete download for {final_path.name}")

    if final_path.exists():
        final_path.unlink()
    part_path.rename(final_path)
    print(f"\n[watcher] downloaded: {final_path}")
    return final_path


async def download_message_media(client: TelegramClient, message: Any, download_dir: Path) -> Path:
    target = download_dir / target_name_for_message(message)

    if getattr(message, "media", None) and getattr(message.media, "document", None):
        return await resumable_download_document(client, message, target)

    # Photos and other media types use Telethon default downloader.
    total = int(getattr(getattr(message, "file", None), "size", 0) or 0)

    def progress_callback(current: int, total_size: int) -> None:
        effective_total = total_size or total
        print_progress(target.name, current, effective_total)

    result = await client.download_media(message, file=str(target), progress_callback=progress_callback)
    if not result:
        raise RuntimeError("Download failed")
    if total > 0:
        print_progress(target.name, total, total)
    print()
    return Path(result).resolve()


async def run() -> None:
    cfg = load_config()
    if not cfg["watch_enabled"]:
        raise RuntimeError("WATCH_SAVED_MESSAGES is disabled in config.py")

    download_dir = Path(os.path.expandvars(cfg["download_path"]).strip()).expanduser().resolve()
    download_dir.mkdir(parents=True, exist_ok=True)

    session_path = ROOT / cfg["session_name"]
    client = TelegramClient(str(session_path), cfg["api_id"], cfg["api_hash"])

    state = load_state()
    last_id = int(state.get("last_id", 0))

    await client.start()
    print("[watcher] started. monitoring Saved Messages...")

    try:
        if last_id == 0:
            recent = await client.get_messages("me", limit=1)
            if recent:
                last_id = recent[0].id
                save_state(last_id)
                print(f"[watcher] initialized at message id {last_id}")

        while True:
            msgs = await client.get_messages("me", limit=50)
            pending = [m for m in reversed(msgs) if m.id > last_id and has_media(m)]

            for msg in pending:
                print(f"[watcher] processing message {msg.id}")
                await download_message_media(client, msg, download_dir)
                last_id = max(last_id, msg.id)
                save_state(last_id)

            await asyncio.sleep(max(2, cfg["watch_poll_seconds"]))
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[watcher] stopped")
