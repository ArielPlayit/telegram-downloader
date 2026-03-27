import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
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

from watch_saved_downloads import CONFIG_FILE, queue_message_for_retry, run

ROOT = Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "downloads" / ".download_history.json"

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "es": {
        "app_title": "Telegram Downloader",
        "subtitle": "Centro de descargas de Telegram con cola inteligente",
        "tab_monitor": "Monitor",
        "tab_history": "Historial",
        "tab_settings": "Configuracion",
        "btn_start": "Iniciar monitor",
        "btn_stop": "Detener monitor",
        "btn_clear_history": "Limpiar historial",
        "btn_save_config": "Guardar configuracion",
        "btn_pick_folder": "Elegir carpeta",
        "btn_language": "Cambiar idioma",
        "btn_retry": "Reintentar",
        "label_events": "Eventos",
        "label_language": "Idioma",
        "lang_es": "Espanol",
        "lang_en": "Ingles",
        "header_file": "Archivo",
        "header_progress": "Progreso",
        "header_speed": "Velocidad",
        "header_eta": "ETA",
        "header_status": "Estado",
        "header_message": "ID mensaje",
        "header_error": "Ultimo error",
        "header_updated": "Actualizado",
        "header_action": "Accion",
        "header_date": "Fecha",
        "header_path": "Ruta",
        "status_pending": "Pendiente",
        "status_queued": "En cola",
        "status_downloading": "Descargando",
        "status_done": "Completado",
        "status_failed": "Error",
        "text_not_available": "--",
        "field_api_id": "ID de API de Telegram",
        "field_api_hash": "Hash de API de Telegram",
        "field_download_path": "Carpeta de descargas",
        "field_session": "Nombre de sesion local",
        "field_watch_enabled": "Activar monitor de Mensajes guardados",
        "field_poll": "Intervalo de verificacion (segundos)",
        "field_concurrent": "Descargas simultaneas maximas",
        "field_speed": "Limite global de velocidad (KB/s, 0 = sin limite)",
        "watch_enabled_true": "Si",
        "watch_enabled_false": "No",
        "title_settings": "Configuracion",
        "msg_select_folder": "Seleccionar carpeta de descargas",
        "msg_language_title": "Seleccionar idioma",
        "msg_language_body": "Elige el idioma para toda la interfaz",
        "msg_config_saved": "Configuracion guardada correctamente",
        "msg_config_saved_log": "[gui] configuracion guardada en config.py",
        "msg_error": "Error",
        "msg_config_error": "No se pudo guardar config.py: {error}",
        "msg_invalid_api_hash": "El hash de API no puede estar vacio",
        "msg_watcher_starting": "[gui] iniciando monitor...",
        "msg_watcher_stopping": "[gui] deteniendo monitor...",
        "msg_watcher_stopped": "[gui] monitor detenido",
        "msg_download_done": "[gui] descarga completada: {name}",
        "msg_history_cleared": "[gui] historial limpiado",
        "msg_retry_queued": "[gui] reintento encolado para mensaje {id}",
        "tray_done_title": "Telegram Downloader",
        "tray_done_body": "Descarga completada: {name}",
        "lang_changed": "[gui] idioma cambiado a {language}",
        "eta_unknown": "Sin ETA",
        "eta_seconds": "{value}s",
        "eta_minutes": "{value}m",
        "eta_hours": "{value}h",
        "watcher_started": "[watcher] iniciado. monitoreando Mensajes Guardados...",
        "watcher_initialized": "[watcher] inicializado en mensaje id {id}",
        "watcher_recovered": "[watcher] mensaje recuperado en cola {id}",
        "watcher_workers": "[watcher] workers: {workers}, limite global: {speed} KB/s",
        "watcher_stop_requested": "[watcher] detencion solicitada",
        "watcher_queued": "[watcher] mensaje en cola {id}",
        "watcher_waiting_queue": "[watcher] esperando terminar la cola pendiente...",
        "watcher_downloaded": "[watcher] descargado: {path}",
        "watcher_complete": "[watcher] ya completo: {name}",
        "watcher_resuming": "[watcher] reanudando {name}: {done}/{total} MB",
        "watcher_failed": "[watcher] fallo mensaje {id}: {error}",
        "watcher_retry": "[watcher] reintentando mensaje {id} (intento {attempt}/3)",
        "watcher_giving_up": "[watcher] descartando mensaje {id} tras reintentos",
        "gui_error": "[gui] error: {error}",
    },
    "en": {
        "app_title": "Telegram Downloader",
        "subtitle": "Telegram download center with smart queue",
        "tab_monitor": "Monitor",
        "tab_history": "History",
        "tab_settings": "Settings",
        "btn_start": "Start monitor",
        "btn_stop": "Stop monitor",
        "btn_clear_history": "Clear history",
        "btn_save_config": "Save settings",
        "btn_pick_folder": "Choose folder",
        "btn_language": "Change language",
        "btn_retry": "Retry",
        "label_events": "Events",
        "label_language": "Language",
        "lang_es": "Spanish",
        "lang_en": "English",
        "header_file": "File",
        "header_progress": "Progress",
        "header_speed": "Speed",
        "header_eta": "ETA",
        "header_status": "Status",
        "header_message": "Message ID",
        "header_error": "Last error",
        "header_updated": "Updated",
        "header_action": "Action",
        "header_date": "Date",
        "header_path": "Path",
        "status_pending": "Pending",
        "status_queued": "Queued",
        "status_downloading": "Downloading",
        "status_done": "Completed",
        "status_failed": "Failed",
        "text_not_available": "--",
        "field_api_id": "Telegram API ID",
        "field_api_hash": "Telegram API Hash",
        "field_download_path": "Download folder",
        "field_session": "Local session name",
        "field_watch_enabled": "Enable Saved Messages watcher",
        "field_poll": "Polling interval (seconds)",
        "field_concurrent": "Max concurrent downloads",
        "field_speed": "Global speed cap (KB/s, 0 = unlimited)",
        "watch_enabled_true": "Yes",
        "watch_enabled_false": "No",
        "title_settings": "Settings",
        "msg_select_folder": "Select download folder",
        "msg_language_title": "Select language",
        "msg_language_body": "Choose the language for the full interface",
        "msg_config_saved": "Settings saved successfully",
        "msg_config_saved_log": "[gui] settings saved in config.py",
        "msg_error": "Error",
        "msg_config_error": "Could not save config.py: {error}",
        "msg_invalid_api_hash": "API hash cannot be empty",
        "msg_watcher_starting": "[gui] starting monitor...",
        "msg_watcher_stopping": "[gui] stopping monitor...",
        "msg_watcher_stopped": "[gui] monitor stopped",
        "msg_download_done": "[gui] download completed: {name}",
        "msg_history_cleared": "[gui] history cleared",
        "msg_retry_queued": "[gui] queued retry for message {id}",
        "tray_done_title": "Telegram Downloader",
        "tray_done_body": "Download completed: {name}",
        "lang_changed": "[gui] language changed to {language}",
        "eta_unknown": "No ETA",
        "eta_seconds": "{value}s",
        "eta_minutes": "{value}m",
        "eta_hours": "{value}h",
        "watcher_started": "[watcher] started. monitoring Saved Messages...",
        "watcher_initialized": "[watcher] initialized at message id {id}",
        "watcher_recovered": "[watcher] recovered queued message {id}",
        "watcher_workers": "[watcher] workers: {workers}, global cap: {speed} KB/s",
        "watcher_stop_requested": "[watcher] stop requested",
        "watcher_queued": "[watcher] queued message {id}",
        "watcher_waiting_queue": "[watcher] waiting queued downloads to finish...",
        "watcher_downloaded": "[watcher] downloaded: {path}",
        "watcher_complete": "[watcher] already complete: {name}",
        "watcher_resuming": "[watcher] resuming {name}: {done}/{total} MB",
        "watcher_failed": "[watcher] failed message {id}: {error}",
        "watcher_retry": "[watcher] retrying message {id} (attempt {attempt}/3)",
        "watcher_giving_up": "[watcher] giving up message {id} after retries",
        "gui_error": "[gui] error: {error}",
    },
}


class WatcherThread(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int, str, int, int, float, float, float)
    queued_signal = Signal(int, str)
    start_signal = Signal(int, str)
    done_signal = Signal(int, str)
    failed_signal = Signal(int, str, str)
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

        cfg = self._load_config_from_file()
        self.language = str(cfg.get("LANGUAGE", "es")).strip().lower()
        if self.language not in TRANSLATIONS:
            self.language = "es"

        self.watcher_thread: WatcherThread | None = None
        self.active_rows: Dict[int, int] = {}

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
        self.active_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.active_table.setAlternatingRowColors(True)

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
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setAlternatingRowColors(True)

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
        return TRANSLATIONS[self.language].get(key, key)

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
        self.active_table.setCellWidget(row, self.COL_ACTION, None)
        return row

    def _set_status(self, row: int, status_text: str) -> None:
        self.active_table.setItem(row, self.COL_STATUS, QTableWidgetItem(status_text))
        self.active_table.setItem(row, self.COL_UPDATED, QTableWidgetItem(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    def _set_retry_button(self, row: int, message_id: int) -> None:
        btn = QPushButton(self.t("btn_retry"))
        btn.clicked.connect(lambda: self.retry_download(message_id))
        self.active_table.setCellWidget(row, self.COL_ACTION, btn)

    def retry_download(self, message_id: int) -> None:
        try:
            queue_message_for_retry(message_id)
            row = self._ensure_active_row(message_id, self.active_table.item(self.active_rows[message_id], self.COL_FILE).text())
            self._set_status(row, self.t("status_queued"))
            self.active_table.setItem(row, self.COL_ERROR, QTableWidgetItem(""))
            self.active_table.setCellWidget(row, self.COL_ACTION, None)
            self.append_log(self.t("msg_retry_queued").format(id=message_id))
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
        self.active_table.setCellWidget(row, self.COL_ACTION, None)

    def on_progress(
        self,
        message_id: int,
        name: str,
        current: int,
        total: int,
        pct: float,
        speed_kbps: float,
        eta_seconds: float,
    ) -> None:
        row = self._ensure_active_row(message_id, name)

        if total > 0:
            progress_text = f"{pct:.1f}% ({current}/{total})"
        else:
            progress_text = f"{current} bytes"

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
        self.active_table.setCellWidget(row, self.COL_ACTION, None)
        self._set_status(row, self.t("status_done"))

        self.add_history_entry(name=name, path=path, message_id=message_id)
        self.append_log(self.t("msg_download_done").format(name=name))

        if self.tray.isSystemTrayAvailable():
            self.tray.showMessage(self.t("tray_done_title"), self.t("tray_done_body").format(name=name))

    def on_download_failed(self, message_id: int, name: str, error: str) -> None:
        row = self._ensure_active_row(message_id, name)
        self._set_status(row, self.t("status_failed"))
        self.active_table.setItem(row, self.COL_ERROR, QTableWidgetItem(error))
        self.active_table.setItem(row, self.COL_SPEED, QTableWidgetItem(self.t("text_not_available")))
        self.active_table.setItem(row, self.COL_ETA, QTableWidgetItem(self.t("text_not_available")))
        self._set_retry_button(row, message_id)

    def _format_speed(self, speed_kbps: float) -> str:
        if speed_kbps <= 0:
            return self.t("text_not_available")
        if speed_kbps >= 1024:
            return f"{speed_kbps / 1024.0:.2f} MB/s"
        return f"{speed_kbps:.1f} KB/s"

    def _format_eta(self, eta_seconds: float) -> str:
        if eta_seconds <= 0:
            return self.t("eta_unknown")
        if eta_seconds < 60:
            return self.t("eta_seconds").format(value=int(eta_seconds))
        if eta_seconds < 3600:
            return self.t("eta_minutes").format(value=int(eta_seconds // 60))
        return self.t("eta_hours").format(value=int(eta_seconds // 3600))

    def _load_history(self) -> List[Dict[str, str]]:
        if not HISTORY_FILE.exists():
            return []
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_history(self, entries: List[Dict[str, str]]) -> None:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(entries, ensure_ascii=True, indent=2), encoding="utf-8")

    def add_history_entry(self, name: str, path: str, message_id: int) -> None:
        entries = self._load_history()
        entries.insert(
            0,
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "name": name,
                "path": path,
                "message_id": str(message_id),
            },
        )
        self._save_history(entries[:1000])
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
        self._save_history([])
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
                action_widget.setText(self.t("btn_retry"))

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
                border-bottom: 1px solid #d7e3ef;
                padding: 8px;
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
