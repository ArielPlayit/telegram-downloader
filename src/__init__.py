"""
Telegram Downloader
Herramienta para descargar archivos de Telegram usando Telethon
"""

__version__ = '1.0.0'
__author__ = 'ArielPlayit'

from .telegram_downloader import TelegramFileDownloader, download_from_telegram

__all__ = ['TelegramFileDownloader', 'download_from_telegram']