"""
Ejemplo de uso del descargador de Telegram
Ejecuta este archivo para probar el downloader
"""

import asyncio
import sys
import os

# Añadir el directorio padre al path para importar src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.telegram_downloader import TelegramFileDownloader


async def download_example():
    """
    Ejemplo básico de descarga desde Telegram
    """
    print("="*60)
    print("📥 Telegram Downloader - Ejemplo de Uso")
    print("="*60)
    
    # Intentar importar configuración
    try:
        from config import API_ID, API_HASH, DOWNLOAD_PATH
        
        # Verificar que las credenciales fueron configuradas
        if API_ID == 0 or API_HASH == 'YOUR_API_HASH_HERE':
            print("\n❌ Error: Credenciales no configuradas")
            print("📝 Pasos para configurar:")
            print("   1. Copia config.example.py a config.py")
            print("   2. Edita config.py con tus credenciales de Telegram")
            print("   3. Obtén tus credenciales en: https://my.telegram.org/apps")
            return
            
    except ImportError:
        print("\n❌ Error: No se encontró config.py")
        print("📝 Pasos para configurar:")
        print("   1. Copia config.example.py a config.py:")
        print("      cp config.example.py config.py")
        print("   2. Edita config.py con tus credenciales")
        print("   3. Obtén tus credenciales en: https://my.telegram.org/apps")
        return
    
    # URL de ejemplo - CAMBIA ESTA URL por una real
    telegram_url = input("\n🔗 Ingresa la URL de Telegram (ejemplo: https://t.me/channel_name/123):\n> ").strip()
    
    if not telegram_url:
        print("❌ No ingresaste ninguna URL")
        return
    
    print(f"\n📍 URL a descargar: {telegram_url}")
    print(f"📁 Carpeta de salida: {DOWNLOAD_PATH}\n")
    
    # Crear el descargador
    downloader = TelegramFileDownloader(API_ID, API_HASH)
    
    try:
        # Conectar a Telegram
        print("🔌 Conectando a Telegram...")
        await downloader.connect()
        
        # Primero obtener información del archivo
        print("\n📊 Obteniendo información del archivo...")
        file_info = await downloader.get_file_info_only(telegram_url)
        
        if file_info and file_info['has_file']:
            print(f"\n✅ Archivo encontrado:")
            print(f"   📄 Nombre: {file_info['filename']}")
            print(f"   📦 Tamaño: {file_info['size_mb']:.2f} MB")
            print(f"   🗂️  Tipo: {file_info['mime_type']}")
            
            # Confirmar descarga
            confirmar = input(f"\n¿Descargar este archivo? (s/n): ").strip().lower()
            
            if confirmar == 's' or confirmar == 'si' or confirmar == 'yes' or confirmar == 'y':
                # Descargar archivo
                print("\n⬇️  Iniciando descarga...")
                result = await downloader.download_file(
                    telegram_url, 
                    output_path=DOWNLOAD_PATH
                )
                
                if result:
                    print(f"\n✅ ¡Descarga exitosa!")
                    print(f"📄 Archivo guardado en: {result}")
                    print(f"💾 Tamaño total: {file_info['size_mb']:.2f} MB")
                else:
                    print("\n❌ La descarga falló")
            else:
                print("\n⏹️  Descarga cancelada")
        else:
            print("\n❌ No se encontró ningún archivo en esa URL")
            print("💡 Verifica que:")
            print("   - La URL sea correcta")
            print("   - El mensaje contenga un archivo")
            print("   - Tengas acceso al canal/chat")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\n💡 Posibles soluciones:")
        print("   - Verifica tus credenciales API")
        print("   - Asegúrate de tener acceso al canal")
        print("   - Verifica tu conexión a internet")
        
    finally:
        # Desconectar
        await downloader.disconnect()
        print("\n" + "="*60)
        print("👋 Fin del ejemplo")
        print("="*60)


async def test_multiple_downloads():
    """
    Ejemplo de descarga múltiple
    """
    try:
        from config import API_ID, API_HASH, DOWNLOAD_PATH
    except ImportError:
        print("❌ Configura config.py primero")
        return
    
    # Lista de URLs a descargar
    urls = [
        "https://t.me/channel1/123",
        "https://t.me/channel2/456",
        # Añade más URLs aquí
    ]
    
    downloader = TelegramFileDownloader(API_ID, API_HASH)
    
    try:
        await downloader.connect()
        
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] Descargando: {url}")
            result = await downloader.download_file(url, DOWNLOAD_PATH)
            
            if result:
                print(f"✅ Descargado: {result}")
            else:
                print(f"❌ Falló: {url}")
                
    finally:
        await downloader.disconnect()


if __name__ == "__main__":
    print("\n🚀 Iniciando descargador de Telegram...\n")
    
    # Menú de opciones
    print("Selecciona una opción:")
    print("1. Descarga individual (recomendado para empezar)")
    print("2. Descarga múltiple")
    
    opcion = input("\nOpción (1 o 2): ").strip()
    
    try:
        if opcion == "1":
            # Ejecutar ejemplo individual
            asyncio.run(download_example())
        elif opcion == "2":
            # Ejecutar ejemplo múltiple
            asyncio.run(test_multiple_downloads())
        else:
            print("❌ Opción inválida")
    except KeyboardInterrupt:
        print("\n\n⏹️  Descarga cancelada por el usuario")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
