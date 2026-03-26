# Telegram Downloader

Descargador de archivos de Telegram desde terminal usando Telethon.

## Caracteristicas

- Descarga por URL de mensaje de Telegram
- Soporta enlaces publicos y privados (`t.me/c/...`)
- Reanudacion de descargas de documentos si cierras la terminal
- Watcher para `Saved Messages` (sin enlace)

## Requisitos

- Python 3.8+
- Cuenta de Telegram

## Instalacion

```powershell
python -m pip install -r requirements.txt
```

## Configuracion

Edita `config.py`:

```python
API_ID = 12345678
API_HASH = 'tu_api_hash'
DOWNLOAD_PATH = './downloads/'
SESSION_NAME = 'telegram_downloader'
WATCH_SAVED_MESSAGES = True
WATCH_POLL_SECONDS = 5
```

## Uso por URL

```powershell
python examples/download_example.py
```

## Uso sin enlace (Saved Messages)

Este modo detecta nuevos archivos en `Saved Messages` y los descarga automaticamente.

```powershell
run_saved_watcher.bat
```

### Como funciona la reanudacion

- Si cierras la terminal durante una descarga de documento, se guarda un archivo parcial `.part`.
- Al volver a ejecutar `run_saved_watcher.bat`, la descarga continua desde el ultimo byte descargado.
- El estado del ultimo mensaje procesado se guarda en `downloads/.saved_watcher_state.json`.

## Notas importantes

- Puedes cerrar la app de Telegram Desktop: no afecta al watcher.
- Lo importante es mantener acceso de red y la sesion de Telethon (`*.session`).
- Si cierras la terminal, al abrirla y ejecutar de nuevo, reanuda donde se quedo.

## Licencia

MIT. Ver `LICENSE`.
