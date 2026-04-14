import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from watch_saved_downloads import (
    CONFIG_FILE,
    queue_message_for_retry,
    request_cancel_for_message,
    request_pause_for_message,
    run,
)
from src.services.history_repository import DownloadHistoryRepository
from src.services.i18n_service import DEFAULT_LANGUAGE, load_translations, normalize_language

ROOT = Path(__file__).resolve().parent
HISTORY_DB_FILE = ROOT / "downloads" / ".download_history.db"
LEGACY_HISTORY_FILE = ROOT / "downloads" / ".download_history.json"
LOCALES_DIR = ROOT / "locales"


class WatcherThread(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(object, str, object, object, float, float, float)
    queued_signal = Signal(object, str)
    start_signal = Signal(object, str)
    done_signal = Signal(object, str)
    paused_signal = Signal(object, str)
    cancelled_signal = Signal(object, str)
    failed_signal = Signal(object, str, str)
    status_signal = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        import asyncio

        async def _runner() -> None:
            self.status_signal.emit("running")
            try:
                await run(
                    on_log=self._on_log,
                    on_progress=self._on_progress,
                    on_download_queued=self._on_queued,
                    on_download_start=self._on_start,
                    on_download_done=self._on_done,
                    on_download_paused=self._on_paused,
                    on_download_cancelled=self._on_cancelled,
                    on_download_failed=self._on_failed,
                    should_stop=self._should_stop,
                )
            except Exception as exc:
                self.log_signal.emit(f"[gui] error: {exc}")
            finally:
                self.status_signal.emit("stopped")

        asyncio.run(_runner())

    def _should_stop(self) -> bool:
        return self._stop_requested

    def _on_log(self, text: str) -> None:
        self.log_signal.emit(text)

    def _on_progress(
        self,
        message_id: int,
        name: str,
        current: int,
        total: int,
        pct: float,
        speed_kbps: float,
        eta_seconds: float,
    ) -> None:
        self.progress_signal.emit(message_id, name, current, total, pct, speed_kbps, eta_seconds)

    def _on_queued(self, message_id: int, name: str) -> None:
        self.queued_signal.emit(message_id, name)

    def _on_start(self, message_id: int, name: str) -> None:
        self.start_signal.emit(message_id, name)

    def _on_done(self, message_id: int, path: Path) -> None:
        self.done_signal.emit(message_id, str(path))

    def _on_paused(self, message_id: int, name: str) -> None:
        self.paused_signal.emit(message_id, name)

    def _on_cancelled(self, message_id: int, name: str) -> None:
        self.cancelled_signal.emit(message_id, name)

    def _on_failed(self, message_id: int, name: str, error: str) -> None:
        self.failed_signal.emit(message_id, name, error)


class MainWindow(QMainWindow):
    COL_FILE = 0
    COL_PROGRESS = 1
    COL_SPEED = 2
    COL_ETA = 3
    COL_STATUS = 4
    COL_MESSAGE = 5
    COL_ERROR = 6
    COL_UPDATED = 7
    COL_ACTION = 8

    def __init__(self) -> None:
        super().__init__()
        self.resize(1180, 760)

        self.translations = load_translations(LOCALES_DIR)
        cfg = self._load_config_from_file()
        self.language = normalize_language(str(cfg.get("LANGUAGE", DEFAULT_LANGUAGE)))
        if self.language not in self.translations:
            self.language = DEFAULT_LANGUAGE

        self.watcher_thread: WatcherThread | None = None
        self.active_rows: Dict[int, int] = {}
        self.history_repo = DownloadHistoryRepository(
            HISTORY_DB_FILE,
            legacy_json_path=LEGACY_HISTORY_FILE,
            max_rows=1000,
        )

        self.tray = QSystemTrayIcon(self)
        if self.tray.isSystemTrayAvailable():
            self.tray.setToolTip("Telegram Downloader")

        self.title = QLabel()
        self.title.setFont(QFont("Bahnschrift", 22, QFont.DemiBold))
        self.title.setObjectName("TitleLabel")

        self.subtitle = QLabel()
        self.subtitle.setObjectName("SubtitleLabel")

        self.tabs = QTabWidget()
        self.monitor_tab = self._build_monitor_tab()
        self.history_tab = self._build_history_tab()
        self.settings_tab = self._build_settings_tab()

        self.tabs.addTab(self.monitor_tab, "")
        self.tabs.addTab(self.history_tab, "")
        self.tabs.addTab(self.settings_tab, "")

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.tabs)
        self.setCentralWidget(root)

        self._apply_theme()
        self.apply_language(initial=True)
        self.load_history_table()

    def _build_monitor_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        controls = QHBoxLayout()
        self.start_btn = QPushButton()
        self.stop_btn = QPushButton()
        self.stop_btn.setEnabled(False)

        self.start_btn.clicked.connect(self.start_watcher)
        self.stop_btn.clicked.connect(self.stop_watcher)

        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch()

        self.active_table = QTableWidget(0, 9)
        active_header = self.active_table.horizontalHeader()
        active_header.setSectionResizeMode(QHeaderView.Interactive)
        active_header.setStretchLastSection(True)
        self.active_table.setAlternatingRowColors(True)
        self.active_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.active_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.active_table.customContextMenuRequested.connect(self._show_active_table_menu)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.events_label = QLabel()

        layout.addLayout(controls)
        layout.addWidget(self.active_table)
        layout.addWidget(self.events_label)
        layout.addWidget(self.log_box)
        return container

    def _build_history_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        self.history_table = QTableWidget(0, 4)
        history_header = self.history_table.horizontalHeader()
        history_header.setSectionResizeMode(QHeaderView.Interactive)
        history_header.setStretchLastSection(True)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.clear_btn = QPushButton()
        self.clear_btn.clicked.connect(self.clear_history)

        layout.addWidget(self.history_table)
        layout.addWidget(self.clear_btn)
        return container

    def _build_settings_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        form = QFormLayout()

        cfg = self._load_config_from_file()

        self.api_id_input = QLineEdit(str(cfg.get("API_ID", "")))
        self.api_hash_input = QLineEdit(str(cfg.get("API_HASH", "")))
        self.download_path_input = QLineEdit(str(cfg.get("DOWNLOAD_PATH", "./downloads/")))
        self.session_name_input = QLineEdit(str(cfg.get("SESSION_NAME", "telegram_downloader")))

        self.watch_enabled_input = QComboBox()
        self._populate_watch_enabled_combo(bool(cfg.get("WATCH_SAVED_MESSAGES", True)))

        self.poll_seconds_input = QSpinBox()
        self.poll_seconds_input.setRange(2, 3600)
        self.poll_seconds_input.setValue(int(cfg.get("WATCH_POLL_SECONDS", 5)))

        self.concurrent_downloads_input = QSpinBox()
        self.concurrent_downloads_input.setRange(1, 32)
        self.concurrent_downloads_input.setValue(int(cfg.get("MAX_CONCURRENT_DOWNLOADS", 1)))

        self.speed_limit_input = QSpinBox()
        self.speed_limit_input.setRange(0, 1024 * 1024)
        self.speed_limit_input.setValue(int(cfg.get("MAX_DOWNLOAD_SPEED_KBPS", 0)))

        self.pick_path_btn = QPushButton()
        self.pick_path_btn.clicked.connect(self.pick_download_folder)
        self.save_btn = QPushButton()
        self.save_btn.clicked.connect(self.save_config)
        self.language_btn = QPushButton()
        self.language_btn.clicked.connect(self.choose_language)
        self.language_value = QLabel()

        self.api_id_label = QLabel()
        self.api_hash_label = QLabel()
        self.download_path_label = QLabel()
        self.session_label = QLabel()
        self.watch_enabled_label = QLabel()
        self.poll_label = QLabel()
        self.concurrent_label = QLabel()
        self.speed_label = QLabel()
        self.language_label = QLabel()

        form.addRow(self.api_id_label, self.api_id_input)
        form.addRow(self.api_hash_label, self.api_hash_input)
        form.addRow(self.download_path_label, self.download_path_input)
        form.addRow("", self.pick_path_btn)
        form.addRow(self.session_label, self.session_name_input)
        form.addRow(self.watch_enabled_label, self.watch_enabled_input)
        form.addRow(self.poll_label, self.poll_seconds_input)
        form.addRow(self.concurrent_label, self.concurrent_downloads_input)
        form.addRow(self.speed_label, self.speed_limit_input)
        form.addRow(self.language_label, self.language_value)
        form.addRow("", self.language_btn)

        layout.addLayout(form)
        layout.addWidget(self.save_btn)
        layout.addStretch()
        return container

    def _load_config_from_file(self) -> Dict[str, object]:
        if not CONFIG_FILE.exists():
            return {}
        namespace: Dict[str, object] = {}
        exec(CONFIG_FILE.read_text(encoding="utf-8"), namespace)
        return namespace

    def _populate_watch_enabled_combo(self, enabled: bool) -> None:
        self.watch_enabled_input.clear()
        self.watch_enabled_input.addItem(self.t("watch_enabled_true"), True)
        self.watch_enabled_input.addItem(self.t("watch_enabled_false"), False)
        index = 0 if enabled else 1
        self.watch_enabled_input.setCurrentIndex(index)

    def t(self, key: str) -> str:
        current = self.translations.get(self.language, {})
        if key in current:
            return current[key]
        fallback = self.translations.get(DEFAULT_LANGUAGE, {})
        return fallback.get(key, key)

    def language_display_name(self) -> str:
        return self.t("lang_en") if self.language == "en" else self.t("lang_es")

    def pick_download_folder(self) -> None:
        current = self.download_path_input.text().strip() or str(ROOT / "downloads")
        folder = QFileDialog.getExistingDirectory(self, self.t("msg_select_folder"), current)
        if folder:
            self.download_path_input.setText(folder)

    def choose_language(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(self.t("msg_language_title"))
        dialog.setText(self.t("msg_language_body"))
        es_btn = dialog.addButton(self.t("lang_es"), QMessageBox.AcceptRole)
        en_btn = dialog.addButton(self.t("lang_en"), QMessageBox.AcceptRole)
        dialog.addButton(QMessageBox.Cancel)
        dialog.exec()

        selected = dialog.clickedButton()
        if selected == es_btn:
            self.language = "es"
        elif selected == en_btn:
            self.language = "en"
        else:
            return

        current_enabled = bool(self.watch_enabled_input.currentData())
        self._populate_watch_enabled_combo(current_enabled)
        self.apply_language()
        self.append_log(self.t("lang_changed").format(language=self.language_display_name()))

    def save_config(self) -> None:
        try:
            api_id = int(self.api_id_input.text().strip())
            api_hash = self.api_hash_input.text().strip()
            if not api_hash:
                raise ValueError(self.t("msg_invalid_api_hash"))

            content = self.build_config_content(
                api_id=api_id,
                api_hash=api_hash,
                download_path=self.download_path_input.text().strip() or "./downloads/",
                session_name=self.session_name_input.text().strip() or "telegram_downloader",
                watch_enabled=bool(self.watch_enabled_input.currentData()),
                poll_seconds=int(self.poll_seconds_input.value()),
                max_concurrent_downloads=int(self.concurrent_downloads_input.value()),
                max_download_speed_kbps=int(self.speed_limit_input.value()),
            )

            CONFIG_FILE.write_text(content, encoding="utf-8")
            self.append_log(self.t("msg_config_saved_log"))
            QMessageBox.information(self, self.t("title_settings"), self.t("msg_config_saved"))
        except Exception as exc:
            QMessageBox.critical(self, self.t("msg_error"), self.t("msg_config_error").format(error=exc))

    def build_config_content(
        self,
        api_id: int,
        api_hash: str,
        download_path: str,
        session_name: str,
        watch_enabled: bool,
        poll_seconds: int,
        max_concurrent_downloads: int,
        max_download_speed_kbps: int,
    ) -> str:
        if self.language == "en":
            header = (
                '"""\nLocal Telegram Downloader configuration\n"""\n\n'
                '# Telegram API credentials\n'
                '# Get them at: https://my.telegram.org/apps\n'
            )
            sections = (
                '# Download settings\n'
                f"DOWNLOAD_PATH = r'{download_path}'\n"
                f"SESSION_NAME = '{session_name}'\n\n"
                '# Saved Messages watcher\n'
                f'WATCH_SAVED_MESSAGES = {"True" if watch_enabled else "False"}\n'
                f'WATCH_POLL_SECONDS = {poll_seconds}\n\n'
                '# Queue settings\n'
                f'MAX_CONCURRENT_DOWNLOADS = {max_concurrent_downloads}\n'
                f'MAX_DOWNLOAD_SPEED_KBPS = {max_download_speed_kbps}\n\n'
                f"LANGUAGE = '{self.language}'\n"
            )
        else:
            header = (
                '"""\nConfiguracion local de Telegram Downloader\n"""\n\n'
                '# Credenciales de Telegram API\n'
                '# Obtenerlas en: https://my.telegram.org/apps\n'
            )
            sections = (
                '# Configuracion de descarga\n'
                f"DOWNLOAD_PATH = r'{download_path}'\n"
                f"SESSION_NAME = '{session_name}'\n\n"
                '# Monitor de Saved Messages\n'
                f'WATCH_SAVED_MESSAGES = {"True" if watch_enabled else "False"}\n'
                f'WATCH_POLL_SECONDS = {poll_seconds}\n\n'
                '# Configuracion de cola\n'
                f'MAX_CONCURRENT_DOWNLOADS = {max_concurrent_downloads}\n'
                f'MAX_DOWNLOAD_SPEED_KBPS = {max_download_speed_kbps}\n\n'
                f"LANGUAGE = '{self.language}'\n"
            )

        return header + f"API_ID = {api_id}\n" + f"API_HASH = '{api_hash}'\n\n" + sections

    def append_log(self, text: str) -> None:
        translated = self._translate_runtime_log(text)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{timestamp}] {translated}")

    def _translate_runtime_log(self, text: str) -> str:
        if self.language == "en":
            return text

        if text.startswith("[gui] error: "):
            return self.t("gui_error").format(error=text.split(": ", 1)[1])

        if text == "[watcher] started. monitoring Saved Messages...":
            return self.t("watcher_started")
        if text == "[watcher] stop requested":
            return self.t("watcher_stop_requested")
        if text == "[watcher] waiting queued downloads to finish...":
            return self.t("watcher_waiting_queue")

        m = re.match(r"^\[watcher\] initialized at message id (\d+)$", text)
        if m:
            return self.t("watcher_initialized").format(id=m.group(1))

        m = re.match(r"^\[watcher\] recovered queued message (\d+)$", text)
        if m:
            return self.t("watcher_recovered").format(id=m.group(1))

        m = re.match(r"^\[watcher\] queued message (\d+)$", text)
        if m:
            return self.t("watcher_queued").format(id=m.group(1))

        m = re.match(r"^\[watcher\] workers: (\d+), speed cap: (\d+) KB/s$", text)
        if m:
            return self.t("watcher_workers").format(workers=m.group(1), speed=m.group(2))

        m = re.match(r"^\[watcher\] downloaded: (.+)$", text)
        if m:
            return self.t("watcher_downloaded").format(path=m.group(1))

        m = re.match(r"^\[watcher\] already complete: (.+)$", text)
        if m:
            return self.t("watcher_complete").format(name=m.group(1))

        m = re.match(r"^\[watcher\] resuming (.+): ([0-9.]+)/([0-9.]+) MB$", text)
        if m:
            return self.t("watcher_resuming").format(name=m.group(1), done=m.group(2), total=m.group(3))

        m = re.match(r"^\[watcher\] failed message (\d+): (.+)$", text)
        if m:
            return self.t("watcher_failed").format(id=m.group(1), error=m.group(2))

        m = re.match(r"^\[watcher\] retrying message (\d+) \(attempt (\d+)/3\)$", text)
        if m:
            return self.t("watcher_retry").format(id=m.group(1), attempt=m.group(2))

        m = re.match(r"^\[watcher\] giving up message (\d+) after retries$", text)
        if m:
            return self.t("watcher_giving_up").format(id=m.group(1))

        m = re.match(r"^\[watcher\] paused message (\d+)$", text)
        if m:
            return self.t("watcher_paused").format(id=m.group(1))

        m = re.match(r"^\[watcher\] cancelled message (\d+)$", text)
        if m:
            return self.t("watcher_cancelled").format(id=m.group(1))

        return text

    def start_watcher(self) -> None:
        if self.watcher_thread and self.watcher_thread.isRunning():
            return

        self.watcher_thread = WatcherThread()
        self.watcher_thread.log_signal.connect(self.append_log)
        self.watcher_thread.progress_signal.connect(self.on_progress)
        self.watcher_thread.queued_signal.connect(self.on_download_queued)
        self.watcher_thread.start_signal.connect(self.on_download_start)
        self.watcher_thread.done_signal.connect(self.on_download_done)
        self.watcher_thread.paused_signal.connect(self.on_download_paused)
        self.watcher_thread.cancelled_signal.connect(self.on_download_cancelled)
        self.watcher_thread.failed_signal.connect(self.on_download_failed)
        self.watcher_thread.status_signal.connect(self.on_status_change)

        self.watcher_thread.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.append_log(self.t("msg_watcher_starting"))

    def stop_watcher(self) -> None:
        if not self.watcher_thread:
            return
        self.watcher_thread.request_stop()
        self.append_log(self.t("msg_watcher_stopping"))

    def on_status_change(self, status: str) -> None:
        if status == "stopped":
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.append_log(self.t("msg_watcher_stopped"))

    def _ensure_active_row(self, message_id: int, name: str) -> int:
        if message_id in self.active_rows:
            row = self.active_rows[message_id]
            self.active_table.setItem(row, self.COL_FILE, QTableWidgetItem(name))
            if self.active_table.cellWidget(row, self.COL_ACTION) is None:
                self._set_actions_button(row)
            return row

        row = self.active_table.rowCount()
        self.active_table.insertRow(row)
        self.active_rows[message_id] = row

        self.active_table.setItem(row, self.COL_FILE, QTableWidgetItem(name))
        self.active_table.setItem(row, self.COL_PROGRESS, QTableWidgetItem("0.0%"))
        self.active_table.setItem(row, self.COL_SPEED, QTableWidgetItem(self.t("text_not_available")))
        self.active_table.setItem(row, self.COL_ETA, QTableWidgetItem(self.t("text_not_available")))
        self.active_table.setItem(row, self.COL_STATUS, QTableWidgetItem(self.t("status_pending")))
        self.active_table.setItem(row, self.COL_MESSAGE, QTableWidgetItem(str(message_id)))
        self.active_table.setItem(row, self.COL_ERROR, QTableWidgetItem(""))
        self.active_table.setItem(row, self.COL_UPDATED, QTableWidgetItem(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self._set_actions_button(row)
        return row

    def _set_status(self, row: int, status_text: str) -> None:
        self.active_table.setItem(row, self.COL_STATUS, QTableWidgetItem(status_text))
        self.active_table.setItem(row, self.COL_UPDATED, QTableWidgetItem(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    def _set_actions_button(self, row: int) -> None:
        btn = QPushButton("...")
        btn.setObjectName("ActionCellButton")
        btn.setToolTip(self.t("header_action"))
        btn.setFixedWidth(42)
        btn.clicked.connect(lambda _checked=False, r=row, b=btn: self._show_row_actions_menu(r, b.mapToGlobal(b.rect().bottomLeft())))

        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(btn, 0, Qt.AlignCenter)
        self.active_table.setCellWidget(row, self.COL_ACTION, container)

    def _get_message_id_from_row(self, row: int) -> int | None:
        item = self.active_table.item(row, self.COL_MESSAGE)
        if not item:
            return None
        try:
            return int(item.text())
        except (TypeError, ValueError):
            return None

    def _get_name_for_message_id(self, message_id: int) -> str:
        row = self.active_rows.get(message_id)
        if row is not None:
            item = self.active_table.item(row, self.COL_FILE)
            if item and item.text().strip():
                return item.text().strip()
        return f"telegram_{message_id}"

    def _show_active_table_menu(self, pos) -> None:
        row = self.active_table.rowAt(pos.y())
        if row < 0:
            return

        self._show_row_actions_menu(row, self.active_table.viewport().mapToGlobal(pos))

    def _show_row_actions_menu(self, row: int, global_pos=None) -> None:
        if row < 0 or row >= self.active_table.rowCount():
            return

        message_id = self._get_message_id_from_row(row)

        menu = QMenu(self)
        retry_action = menu.addAction(self.t("btn_retry"))
        pause_action = menu.addAction(self.t("btn_pause"))
        cancel_action = menu.addAction(self.t("btn_cancel"))
        retry_action.setEnabled(message_id is not None)
        pause_action.setEnabled(message_id is not None)
        cancel_action.setEnabled(message_id is not None)

        if global_pos is None:
            action_widget = self.active_table.cellWidget(row, self.COL_ACTION)
            if action_widget:
                global_pos = action_widget.mapToGlobal(action_widget.rect().center())
            else:
                global_pos = self.active_table.viewport().mapToGlobal(self.active_table.rect().center())

        selected = menu.exec(global_pos)
        if selected == retry_action and message_id is not None:
            self.retry_download(message_id)
        elif selected == pause_action and message_id is not None:
            self.pause_download(message_id)
        elif selected == cancel_action and message_id is not None:
            self.cancel_download(message_id)

    def retry_download(self, message_id: int) -> None:
        try:
            queue_message_for_retry(message_id)
            row = self._ensure_active_row(message_id, self._get_name_for_message_id(message_id))
            self._set_status(row, self.t("status_queued"))
            self.active_table.setItem(row, self.COL_ERROR, QTableWidgetItem(""))
            self._set_actions_button(row)
            self.append_log(self.t("msg_retry_queued").format(id=message_id))
        except Exception as exc:
            QMessageBox.critical(self, self.t("msg_error"), str(exc))

    def pause_download(self, message_id: int) -> None:
        try:
            request_pause_for_message(message_id)
            row = self._ensure_active_row(message_id, self._get_name_for_message_id(message_id))
            self._set_status(row, self.t("status_paused"))
            self.active_table.setItem(row, self.COL_SPEED, QTableWidgetItem(self.t("text_not_available")))
            self.active_table.setItem(row, self.COL_ETA, QTableWidgetItem(self.t("text_not_available")))
            self.append_log(self.t("msg_pause_requested").format(id=message_id))
        except Exception as exc:
            QMessageBox.critical(self, self.t("msg_error"), str(exc))

    def cancel_download(self, message_id: int) -> None:
        try:
            confirmation = QMessageBox.question(
                self,
                self.t("msg_cancel_confirm_title"),
                self.t("msg_cancel_confirm_body").format(id=message_id),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirmation != QMessageBox.Yes:
                return

            request_cancel_for_message(message_id)
            row = self._ensure_active_row(message_id, self._get_name_for_message_id(message_id))
            self._set_status(row, self.t("status_cancelled"))
            self.active_table.setItem(row, self.COL_SPEED, QTableWidgetItem(self.t("text_not_available")))
            self.active_table.setItem(row, self.COL_ETA, QTableWidgetItem(self.t("text_not_available")))
            self.append_log(self.t("msg_cancel_requested").format(id=message_id))
        except Exception as exc:
            QMessageBox.critical(self, self.t("msg_error"), str(exc))

    def on_download_queued(self, message_id: int, name: str) -> None:
        row = self._ensure_active_row(message_id, name)
        self._set_status(row, self.t("status_queued"))
        self.active_table.setItem(row, self.COL_MESSAGE, QTableWidgetItem(str(message_id)))

    def on_download_start(self, message_id: int, name: str) -> None:
        row = self._ensure_active_row(message_id, name)
        self._set_status(row, self.t("status_downloading"))
        self.active_table.setItem(row, self.COL_ERROR, QTableWidgetItem(""))
        self._set_actions_button(row)

    def on_progress(
        self,
        message_id: int,
        name: str,
        current: object,
        total: object,
        pct: float,
        speed_kbps: float,
        eta_seconds: float,
    ) -> None:
        row = self._ensure_active_row(message_id, name)
        status_item = self.active_table.item(row, self.COL_STATUS)
        if status_item and status_item.text() in {self.t("status_paused"), self.t("status_cancelled")}:
            return

        try:
            current_value = int(current)
        except (TypeError, ValueError):
            current_value = 0

        try:
            total_value = int(total)
        except (TypeError, ValueError):
            total_value = 0

        if total_value > 0:
            progress_text = f"{pct:.1f}% ({self._format_size_value(current_value)}/{self._format_size_value(total_value)})"
        else:
            progress_text = self._format_size_value(current_value)

        self.active_table.setItem(row, self.COL_PROGRESS, QTableWidgetItem(progress_text))
        self.active_table.setItem(row, self.COL_SPEED, QTableWidgetItem(self._format_speed(speed_kbps)))
        self.active_table.setItem(row, self.COL_ETA, QTableWidgetItem(self._format_eta(eta_seconds)))
        self._set_status(row, self.t("status_downloading"))

    def on_download_done(self, message_id: int, path: str) -> None:
        name = Path(path).name
        row = self._ensure_active_row(message_id, name)

        self.active_table.setItem(row, self.COL_PROGRESS, QTableWidgetItem("100.0%"))
        self.active_table.setItem(row, self.COL_SPEED, QTableWidgetItem(self.t("text_not_available")))
        self.active_table.setItem(row, self.COL_ETA, QTableWidgetItem(self.t("text_not_available")))
        self.active_table.setItem(row, self.COL_MESSAGE, QTableWidgetItem(str(message_id)))
        self.active_table.setItem(row, self.COL_ERROR, QTableWidgetItem(""))
        self._set_actions_button(row)
        self._set_status(row, self.t("status_done"))

        self.add_history_entry(name=name, path=path, message_id=message_id)
        self.append_log(self.t("msg_download_done").format(name=name))

        if self.tray.isSystemTrayAvailable():
            self.tray.showMessage(self.t("tray_done_title"), self.t("tray_done_body").format(name=name))

    def on_download_paused(self, message_id: int, name: str) -> None:
        row = self._ensure_active_row(message_id, name)
        self._set_status(row, self.t("status_paused"))
        self.active_table.setItem(row, self.COL_SPEED, QTableWidgetItem(self.t("text_not_available")))
        self.active_table.setItem(row, self.COL_ETA, QTableWidgetItem(self.t("text_not_available")))
        self._set_actions_button(row)
        self.append_log(self.t("msg_download_paused").format(id=message_id))

    def on_download_cancelled(self, message_id: int, name: str) -> None:
        row = self._ensure_active_row(message_id, name)
        self._set_status(row, self.t("status_cancelled"))
        self.active_table.setItem(row, self.COL_PROGRESS, QTableWidgetItem("0.0%"))
        self.active_table.setItem(row, self.COL_SPEED, QTableWidgetItem(self.t("text_not_available")))
        self.active_table.setItem(row, self.COL_ETA, QTableWidgetItem(self.t("text_not_available")))
        self.active_table.setItem(row, self.COL_ERROR, QTableWidgetItem(""))
        self._set_actions_button(row)
        self.append_log(self.t("msg_download_cancelled").format(id=message_id))

    def on_download_failed(self, message_id: int, name: str, error: str) -> None:
        row = self._ensure_active_row(message_id, name)
        self._set_status(row, self.t("status_failed"))
        self.active_table.setItem(row, self.COL_ERROR, QTableWidgetItem(error))
        self.active_table.setItem(row, self.COL_SPEED, QTableWidgetItem(self.t("text_not_available")))
        self.active_table.setItem(row, self.COL_ETA, QTableWidgetItem(self.t("text_not_available")))
        self._set_actions_button(row)

    def _format_speed(self, speed_kbps: float) -> str:
        if speed_kbps <= 0:
            return self.t("text_not_available")
        if speed_kbps >= 1024:
            return f"{speed_kbps / 1024.0:.2f} MB/s"
        return f"{speed_kbps:.1f} KB/s"

    def _format_size_value(self, bytes_value: int) -> str:
        mb = 1024 * 1024
        gb = 1024 * 1024 * 1024
        if bytes_value >= gb:
            return f"{bytes_value / gb:.2f} GB"
        return f"{bytes_value / mb:.2f} MB"

    def _format_eta(self, eta_seconds: float) -> str:
        if eta_seconds <= 0:
            return self.t("eta_unknown")
        if eta_seconds < 60:
            return self.t("eta_seconds").format(value=int(eta_seconds))
        if eta_seconds < 3600:
            return self.t("eta_minutes").format(value=int(eta_seconds // 60))
        return self.t("eta_hours").format(value=int(eta_seconds // 3600))

    def _load_history(self) -> List[Dict[str, str]]:
        return self.history_repo.list_entries(limit=1000)

    def _save_history(self, entries: List[Dict[str, str]]) -> None:
        self.history_repo.clear()
        for item in reversed(entries):
            self.history_repo.add_entry(
                timestamp=str(item.get("timestamp", "")),
                name=str(item.get("name", "")),
                path=str(item.get("path", "")),
                message_id=str(item.get("message_id", "")),
            )

    def add_history_entry(self, name: str, path: str, message_id: int) -> None:
        self.history_repo.add_entry(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name=name,
            path=path,
            message_id=str(message_id),
        )
        self.load_history_table()

    def load_history_table(self) -> None:
        entries = self._load_history()
        self.history_table.setRowCount(0)
        for item in entries:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self.history_table.setItem(row, 0, QTableWidgetItem(item.get("timestamp", "")))
            self.history_table.setItem(row, 1, QTableWidgetItem(item.get("name", "")))
            self.history_table.setItem(row, 2, QTableWidgetItem(item.get("path", "")))
            self.history_table.setItem(row, 3, QTableWidgetItem(item.get("message_id", "")))

    def clear_history(self) -> None:
        self.history_repo.clear()
        self.load_history_table()
        self.append_log(self.t("msg_history_cleared"))

    def apply_language(self, initial: bool = False) -> None:
        self.setWindowTitle(self.t("app_title"))
        self.title.setText(self.t("app_title"))
        self.subtitle.setText(self.t("subtitle"))

        self.tabs.setTabText(0, self.t("tab_monitor"))
        self.tabs.setTabText(1, self.t("tab_history"))
        self.tabs.setTabText(2, self.t("tab_settings"))

        self.start_btn.setText(self.t("btn_start"))
        self.stop_btn.setText(self.t("btn_stop"))
        self.events_label.setText(self.t("label_events"))

        self.active_table.setHorizontalHeaderLabels(
            [
                self.t("header_file"),
                self.t("header_progress"),
                self.t("header_speed"),
                self.t("header_eta"),
                self.t("header_status"),
                self.t("header_message"),
                self.t("header_error"),
                self.t("header_updated"),
                self.t("header_action"),
            ]
        )
        self.history_table.setHorizontalHeaderLabels(
            [self.t("header_date"), self.t("header_file"), self.t("header_path"), self.t("header_message")]
        )

        self.clear_btn.setText(self.t("btn_clear_history"))
        self.pick_path_btn.setText(self.t("btn_pick_folder"))
        self.save_btn.setText(self.t("btn_save_config"))
        self.language_btn.setText(self.t("btn_language"))
        self.language_value.setText(self.language_display_name())

        self.api_id_label.setText(self.t("field_api_id"))
        self.api_hash_label.setText(self.t("field_api_hash"))
        self.download_path_label.setText(self.t("field_download_path"))
        self.session_label.setText(self.t("field_session"))
        self.watch_enabled_label.setText(self.t("field_watch_enabled"))
        self.poll_label.setText(self.t("field_poll"))
        self.concurrent_label.setText(self.t("field_concurrent"))
        self.speed_label.setText(self.t("field_speed"))
        self.language_label.setText(self.t("label_language"))

        self._translate_existing_rows()

        if not initial:
            current_enabled = bool(self.watch_enabled_input.currentData())
            self._populate_watch_enabled_combo(current_enabled)

    def _translate_existing_rows(self) -> None:
        status_map = {
            "Pendiente": "status_pending",
            "Pending": "status_pending",
            "En cola": "status_queued",
            "Queued": "status_queued",
            "Descargando": "status_downloading",
            "Downloading": "status_downloading",
            "Completado": "status_done",
            "Completed": "status_done",
            "Pausado": "status_paused",
            "Paused": "status_paused",
            "Cancelado": "status_cancelled",
            "Cancelled": "status_cancelled",
            "Error": "status_failed",
            "Failed": "status_failed",
        }

        for row in range(self.active_table.rowCount()):
            status_item = self.active_table.item(row, self.COL_STATUS)
            if status_item:
                key = status_map.get(status_item.text())
                if key:
                    status_item.setText(self.t(key))

            action_widget = self.active_table.cellWidget(row, self.COL_ACTION)
            if isinstance(action_widget, QPushButton):
                action_widget.setText("...")
                action_widget.setToolTip(self.t("header_action"))
            elif action_widget:
                action_btn = action_widget.findChild(QPushButton)
                if action_btn:
                    action_btn.setText("...")
                    action_btn.setToolTip(self.t("header_action"))

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #f4f7fb;
                color: #19212a;
                font-family: 'Bahnschrift';
                font-size: 10.5pt;
            }
            #TitleLabel {
                color: #0f2742;
                letter-spacing: 0.5px;
                margin-top: 6px;
            }
            #SubtitleLabel {
                color: #3f5a76;
                margin-bottom: 10px;
            }
            QTabWidget::pane {
                border: 1px solid #c9d7e6;
                border-radius: 10px;
                background: #ffffff;
                top: -1px;
            }
            QTabBar::tab {
                background: #dfe9f5;
                color: #24384d;
                padding: 10px 16px;
                margin-right: 6px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background: #1b7f8f;
                color: #ffffff;
            }
            QPushButton {
                background: #1b7f8f;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #136874;
            }
            QPushButton:disabled {
                background: #b8c7d6;
                color: #f8fbff;
            }
            QPushButton#ActionCellButton {
                padding: 3px 8px;
                min-width: 34px;
            }
            QLineEdit, QSpinBox, QComboBox, QTextEdit {
                background: #fbfdff;
                border: 1px solid #c8d5e3;
                border-radius: 8px;
                padding: 6px;
            }
            QTableWidget {
                background: #ffffff;
                border: 1px solid #c8d5e3;
                border-radius: 8px;
                gridline-color: #e5edf5;
                selection-background-color: #d5f0f4;
            }
            QHeaderView::section {
                background: #ecf4fb;
                color: #2e4a63;
                font-weight: 700;
                border: none;
                border-right: 1px solid #d7e3ef;
                border-bottom: 1px solid #d7e3ef;
                padding: 8px;
            }
            QHeaderView::section:last {
                border-right: none;
            }
            """
        )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.watcher_thread and self.watcher_thread.isRunning():
            self.watcher_thread.request_stop()
            self.watcher_thread.wait(3000)
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
