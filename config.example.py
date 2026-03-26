"""
Archivo de configuración de ejemplo
Copia este archivo como 'config.py' y añade tus credenciales
NO SUBAS config.py a GitHub
"""

# Credenciales de Telegram API
# Obtenerlas en: https://my.telegram.org/apps
API_ID = 0  # Reemplaza con tu API ID (número)
API_HASH = 'YOUR_API_HASH_HERE'  # Reemplaza con tu API Hash

# Configuración de descarga
DOWNLOAD_PATH = './downloads/'  # Carpeta de descargas por defecto
SESSION_NAME = 'telegram_downloader'   # Nombre del archivo de sesión

# Watcher de Saved Messages (modo terminal)
WATCH_SAVED_MESSAGES = False
WATCH_POLL_SECONDS = 5