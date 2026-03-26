"""
Telegram File Downloader
Descargador de archivos de Telegram usando Telethon
Versión para GitHub - Sin credenciales hardcodeadas
"""

import re
import os
from typing import Optional, Callable, Dict, Any

try:
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    print("⚠️  Telethon no está instalado.")
    print("📦 Instala con: pip install telethon")


class TelegramFileDownloader:
    """
    Descargador de archivos de Telegram usando Telethon
    
    Uso:
        downloader = TelegramFileDownloader(api_id, api_hash)
        await downloader.connect()
        await downloader.download_file(url, output_path)
        await downloader.disconnect()
    """
    
    def __init__(self, api_id: int, api_hash: str, session_name: str = 'telegram_downloader'):
        """
        Inicializa el cliente de Telegram
        
        Args:
            api_id: Tu API ID de Telegram (obtener en my.telegram.org)
            api_hash: Tu API Hash de Telegram
            session_name: Nombre del archivo de sesión (default: 'telegram_downloader')
        
        Raises:
            ImportError: Si Telethon no está instalado
            ValueError: Si las credenciales no son válidas
        """
        if not TELETHON_AVAILABLE:
            raise ImportError(
                "Telethon no está instalado. "
                "Instala con: pip install telethon"
            )
        
        if not api_id or not api_hash:
            raise ValueError(
                "API_ID y API_HASH son requeridos. "
                "Obtén tus credenciales en https://my.telegram.org/apps"
            )
            
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.connected = False
        
    async def connect(self) -> bool:
        """
        Conecta al cliente de Telegram
        
        Returns:
            True si la conexión fue exitosa
        """
        try:
            await self.client.start()
            self.connected = True
            print("✅ Conectado a Telegram")
            return True
        except Exception as e:
            print(f"❌ Error al conectar: {e}")
            return False
        
    async def disconnect(self):
        """Desconecta del cliente de Telegram"""
        if self.connected:
            await self.client.disconnect()
            self.connected = False
            print("✅ Desconectado de Telegram")
        
    def parse_telegram_url(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Parsea una URL de Telegram para extraer información
        
        Formatos soportados:
        - https://t.me/channel_name/123
        - https://t.me/c/1234567890/123
        - t.me/channel_name/123
        
        Args:
            url: URL del mensaje de Telegram
            
        Returns:
            Dict con información parseada o None si es inválida
        """
        # Patrón para canales privados: t.me/c/channel_id/message_id
        private_pattern = r't\.me/c/(\d+)/(\d+)'
        # Patrón para canales públicos: t.me/channel_name/message_id
        public_pattern = r't\.me/([^/]+)/(\d+)'

        private_match = re.search(private_pattern, url)
        if private_match:
            return {
                'type': 'private',
                'channel_id': int(private_match.group(1)),
                'message_id': int(private_match.group(2))
            }

        public_match = re.search(public_pattern, url)
        if public_match:
            channel = public_match.group(1)
            if channel == 'c':
                return None

            return {
                'type': 'public',
                'channel': channel,
                'message_id': int(public_match.group(2))
            }
            
        return None
        
    async def get_message(self, parsed_info: Dict[str, Any]):
        """
        Obtiene el mensaje de Telegram
        
        Args:
            parsed_info: Información parseada de la URL
            
        Returns:
            Objeto Message de Telegram o None si falla
        """
        if not self.connected:
            print("❌ No estás conectado. Ejecuta connect() primero")
            return None
            
        try:
            if parsed_info['type'] == 'public':
                entity = await self.client.get_entity(parsed_info['channel'])
                message = await self.client.get_messages(
                    entity, 
                    ids=parsed_info['message_id']
                )
            else:
                # Para enlaces t.me/c/{id}/{msg}, Telegram requiere prefijo -100
                channel_id = parsed_info['channel_id']
                if channel_id > 0:
                    channel_id = int(f"-100{channel_id}")
                message = await self.client.get_messages(
                    channel_id, 
                    ids=parsed_info['message_id']
                )
                
            return message
        except Exception as e:
            print(f"❌ Error al obtener mensaje: {e}")
            return None
            
    def get_file_info(self, message) -> Dict[str, Any]:
        """
        Extrae información del archivo del mensaje
        
        Args:
            message: Objeto Message de Telegram
            
        Returns:
            Dict con información del archivo
        """
        info = {
            'filename': 'archivo_sin_nombre',
            'size': 0,
            'size_mb': 0,
            'mime_type': 'application/octet-stream',
            'has_file': False
        }
        
        if not message or not message.media:
            return info
            
        info['has_file'] = True
        
        if isinstance(message.media, MessageMediaDocument):
            doc = message.media.document
            info['size'] = doc.size
            info['size_mb'] = doc.size / (1024 * 1024)
            info['mime_type'] = doc.mime_type
            
            # Buscar el nombre del archivo en los atributos
            for attr in doc.attributes:
                if hasattr(attr, 'file_name'):
                    info['filename'] = attr.file_name
                    break
                    
        elif isinstance(message.media, MessageMediaPhoto):
            info['filename'] = f'photo_{message.id}.jpg'
            info['mime_type'] = 'image/jpeg'
            # El tamaño exacto requiere más procesamiento
            
        return info
            
    async def download_file(
        self, 
        url: str, 
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> Optional[str]:
        """
        Descarga un archivo desde una URL de Telegram
        
        Args:
            url: URL del mensaje de Telegram
            output_path: Ruta donde guardar (carpeta o archivo completo)
            progress_callback: Función para reportar progreso (current, total)
            
        Returns:
            Ruta del archivo descargado o None si falla
            
        Example:
            path = await downloader.download_file(
                "https://t.me/channel/123",
                "./downloads/"
            )
        """
        if not self.connected:
            print("❌ No estás conectado. Ejecuta connect() primero")
            return None
            
        # Parsear URL
        parsed = self.parse_telegram_url(url)
        if not parsed:
            print(f"❌ URL no válida: {url}")
            return None
            
        print(f"📡 Obteniendo mensaje...")
        message = await self.get_message(parsed)
        
        if not message:
            print("❌ No se pudo obtener el mensaje")
            return None
            
        # Verificar si el mensaje tiene un archivo
        if not message.media:
            print("❌ El mensaje no contiene ningún archivo")
            return None
            
        # Obtener información del archivo
        file_info = self.get_file_info(message)
        if not file_info['has_file']:
            print("❌ No se pudo obtener información del archivo")
            return None
            
        print(f"📁 Archivo: {file_info['filename']}")
        print(f"📊 Tamaño: {file_info['size_mb']:.2f} MB")
        print(f"🗂️  Tipo: {file_info['mime_type']}")
        
        # Determinar ruta de salida
        if not output_path:
            output_path = file_info['filename']
        elif os.path.isdir(output_path):
            output_path = os.path.join(output_path, file_info['filename'])
            
        # Crear directorio si no existe
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        
        # Función de progreso
        def progress(current: int, total: int):
            percentage = (current / total) * 100
            mb_current = current / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            
            print(
                f"\r⬇️  Descargando: {percentage:.1f}% "
                f"({mb_current:.2f}/{mb_total:.2f} MB)", 
                end=''
            )
            
            if progress_callback:
                progress_callback(current, total)

        async def download_document_resumable() -> Optional[str]:
            doc = message.media.document
            total = int(getattr(doc, 'size', 0) or 0)
            current = 0

            if os.path.exists(output_path):
                current = os.path.getsize(output_path)

            if total and current > total:
                current = 0

            if total and current == total:
                print("✅ Archivo ya descargado previamente")
                return output_path

            if current > 0:
                print(f"♻️  Reanudando descarga desde {current / (1024 * 1024):.2f} MB")

            mode = 'ab' if current > 0 else 'wb'
            with open(output_path, mode) as fh:
                async for chunk in self.client.iter_download(doc, offset=current):
                    fh.write(chunk)
                    current += len(chunk)
                    progress(current, total)

            return output_path
                
        # Descargar archivo
        print(f"💾 Guardando en: {output_path}")
        try:
            if isinstance(message.media, MessageMediaDocument):
                path = await download_document_resumable()
            else:
                path = await self.client.download_media(
                    message,
                    file=output_path,
                    progress_callback=progress
                )
            print(f"\n✅ Descarga completada: {path}")
            return path
        except Exception as e:
            print(f"\n❌ Error durante la descarga: {e}")
            return None
            
    async def get_file_info_only(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene solo la información del archivo sin descargarlo
        
        Args:
            url: URL del mensaje de Telegram
            
        Returns:
            Dict con información del archivo o None
        """
        if not self.connected:
            print("❌ No estás conectado. Ejecuta connect() primero")
            return None
            
        parsed = self.parse_telegram_url(url)
        if not parsed:
            return None
            
        message = await self.get_message(parsed)
        if not message:
            return None
            
        return self.get_file_info(message)


# Función auxiliar para uso rápido
async def download_from_telegram(
    api_id: int, 
    api_hash: str, 
    url: str, 
    output_path: Optional[str] = None
) -> Optional[str]:
    """
    Función simplificada para descargar desde Telegram
    
    Args:
        api_id: Tu API ID
        api_hash: Tu API Hash
        url: URL del archivo en Telegram
        output_path: Ruta de salida (opcional)
        
    Returns:
        Ruta del archivo descargado o None
        
    Example:
        result = await download_from_telegram(
            12345678,
            'your_hash',
            'https://t.me/channel/123'
        )
    """
    downloader = TelegramFileDownloader(api_id, api_hash)
    
    try:
        await downloader.connect()
        result = await downloader.download_file(url, output_path)
        return result
    finally:
        await downloader.disconnect()


if __name__ == "__main__":
    print("="*60)
    print("📥 TELEGRAM FILE DOWNLOADER")
    print("="*60)
    print("\n⚠️  Este módulo debe ser importado, no ejecutado directamente")
    print("📖 Ver examples/download_example.py para ejemplos de uso")
    print("\n💡 Para empezar:")
    print("   1. Copia config.example.py a config.py")
    print("   2. Añade tus credenciales en config.py")
    print("   3. Ejecuta: python examples/download_example.py")
    print("="*60)