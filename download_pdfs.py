#!/usr/bin/env python3
"""
Script para descargar adjuntos PDF de correos de remitentes confiables.
Lee configuraciones desde .env y lista de correos desde trusted_emails.txt
"""

import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))

# Rutas
SCRIPT_DIR = Path(__file__).parent
ATTACHMENTS_DIR = SCRIPT_DIR / "pdf_attachments"
TRUSTED_EMAILS_FILE = SCRIPT_DIR / "trusted_emails.txt"
PROCESSED_LOG = SCRIPT_DIR / "processed_emails.log"
FAILED_LOG = SCRIPT_DIR / "failed_emails.log"


def load_trusted_emails(filepath):
    """Carga la lista de correos/dominios confiables desde un archivo."""
    trusted = set()
    if not filepath.exists():
        print(f"⚠️  Archivo {filepath} no encontrado.")
        return trusted
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                trusted.add(line.lower())
    return trusted


def is_trusted_sender(sender_email, trusted_list):
    """Verifica si el remitente está en la lista de confianza."""
    sender_email = sender_email.lower()
    
    # Coincidencia exacta
    if sender_email in trusted_list:
        return True
    
    # Coincidencia por dominio (si el elemento en trusted_list no tiene @)
    for trusted in trusted_list:
        if '@' not in trusted:
            # Es un dominio
            if sender_email.endswith('@' + trusted):
                return True
    
    return False


def decode_mime_words(subject):
    """Decodifica palabras MIME en el asunto."""
    decoded_parts = []
    for part in email.header.decode_header(subject):
        text, encoding = part
        if isinstance(text, bytes):
            try:
                decoded_parts.append(text.decode(encoding or 'utf-8', errors='replace'))
            except LookupError:
                decoded_parts.append(text.decode('utf-8', errors='replace'))
        else:
            decoded_parts.append(text)
    return ''.join(decoded_parts)


def get_email_address(email_address):
    """Extrae la dirección de email limpia."""
    if '<' in email_address and '>' in email_address:
        match = re.search(r'<([^>]+)>', email_address)
        if match:
            return match.group(1)
    return email_address.strip()


def save_attachment(payload, filename, output_dir):
    """Guarda el adjunto con timestamp si ya existe."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Verificar si el archivo ya existe
    file_path = output_dir / filename
    if file_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(filename)
        new_filename = f"{name}_{timestamp}{ext}"
        file_path = output_dir / new_filename
        print(f"  ⚠️  Archivo '{filename}' ya existía. Guardado como '{new_filename}'")
    
    with open(file_path, 'wb') as f:
        f.write(payload.get_payload(decode=True))
    
    return file_path


def fetch_emails_since_date(imap_conn, since_date):
    """Obtiene todos los emails desde una fecha específica."""
    date_str = since_date.strftime("%d-%b-%Y")
    
    try:
        status, messages = imap_conn.search(None, '(SINCE', f'"{date_str}")')
        if status != 'OK':
            print("❌ Error al buscar correos.")
            return []
        
        email_ids = messages[0].split()
        return email_ids
    except Exception as e:
        print(f"❌ Error en búsqueda: {e}")
        return []


def process_emails():
    """Función principal para procesar correos."""
    
    # Validar configuración
    if not all([EMAIL_USER, EMAIL_PASSWORD, IMAP_SERVER]):
        print("❌ Faltan credenciales en el archivo .env")
        print("   Copia .env.example a .env y completa los datos")
        return
    
    # Cargar lista de confianza
    trusted_emails = load_trusted_emails(TRUSTED_EMAILS_FILE)
    if not trusted_emails:
        print("⚠️  No hay correos confiables cargados.")
        return
    
    print(f"✅ {len(trusted_emails)} correos/dominios confiables cargados")
    
    # Crear directorio de adjuntos si no existe
    if not ATTACHMENTS_DIR.exists():
        ATTACHMENTS_DIR.mkdir(parents=True)
        print(f"📁 Carpeta '{ATTACHMENTS_DIR.name}' creada")
    
    # Solicitar fecha de búsqueda
    print("\n📅 ¿Desde qué fecha quieres buscar correos?")
    print("   Formato: YYYY-MM-DD (ej: 2024-01-01)")
    print("   Presiona Enter para últimos 7 días")
    
    date_input = input("> ").strip()
    
    if date_input:
        try:
            search_date = datetime.strptime(date_input, "%Y-%m-%d")
        except ValueError:
            print("❌ Fecha inválida. Usando últimos 7 días.")
            search_date = datetime.now() - timedelta(days=7)
    else:
        search_date = datetime.now() - timedelta(days=7)
    
    print(f"\n🔍 Buscando correos desde: {search_date.strftime('%Y-%m-%d')}")
    
    # Conectar al servidor IMAP
    try:
        print(f"\n📡 Conectando a {IMAP_SERVER}:{IMAP_PORT}...")
        imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        imap.login(EMAIL_USER, EMAIL_PASSWORD)
        imap.select("INBOX")
        print("✅ Conectado exitosamente")
    except imaplib.IMAP4.error as e:
        print(f"❌ Error de conexión: {e}")
        return
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        return
    
    # Obtener correos
    email_ids = fetch_emails_since_date(imap, search_date)
    total_emails = len(email_ids)
    print(f"📧 {total_emails} correos encontrados desde la fecha indicada")
    
    # Contadores y logs
    processed_count = 0
    failed_count = 0
    pdf_count = 0
    
    # Abrir archivos de log
    with open(PROCESSED_LOG, 'a', encoding='utf-8') as proc_log, \
         open(FAILED_LOG, 'a', encoding='utf-8') as fail_log:
        
        proc_log.write(f"\n{'='*60}\n")
        proc_log.write(f"Ejecución: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        proc_log.write(f"Búsqueda desde: {search_date.strftime('%Y-%m-%d')}\n")
        proc_log.write(f"{'='*60}\n\n")
        
        fail_log.write(f"\n{'='*60}\n")
        fail_log.write(f"Ejecución: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        fail_log.write(f"Búsqueda desde: {search_date.strftime('%Y-%m-%d')}\n")
        fail_log.write(f"{'='*60}\n\n")
        
        # Procesar cada correo
        for i, email_id in enumerate(email_ids, 1):
            try:
                status, msg_data = imap.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    continue
                
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        
                        # Obtener remitente
                        sender_raw = msg.get('From', '')
                        sender_email = get_email_address(sender_raw)
                        
                        # Obtener asunto
                        subject_raw = msg.get('Subject', '')
                        subject = decode_mime_words(subject_raw)
                        
                        # Obtener fecha del correo
                        date_raw = msg.get('Date', '')
                        email_date = email.utils.parsedate_to_datetime(date_raw) if date_raw else None
                        
                        # Verificar si es de confianza
                        if not is_trusted_sender(sender_email, trusted_emails):
                            fail_log.write(f"❌ [{email_id.decode()}] {sender_email} - {subject}\n")
                            fail_log.write(f"   Motivo: Remitente no está en lista de confianza\n\n")
                            failed_count += 1
                            continue
                        
                        # Buscar adjuntos PDF
                        found_pdf = False
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            content_disposition = str(part.get("Content-Disposition"))
                            
                            if content_type == "application/pdf" and "attachment" in content_disposition:
                                filename = part.get_filename()
                                if filename:
                                    filename = decode_mime_words(filename)
                                    if filename.lower().endswith('.pdf'):
                                        try:
                                            saved_path = save_attachment(part, filename, ATTACHMENTS_DIR)
                                            print(f"  ✅ PDF guardado: {saved_path.name}")
                                            
                                            proc_log.write(f"✅ [{email_id.decode()}] {sender_email} - {subject}\n")
                                            if email_date:
                                                proc_log.write(f"   Fecha correo: {email_date.strftime('%Y-%m-%d %H:%M')}\n")
                                            proc_log.write(f"   Adjunto: {saved_path.name}\n")
                                            proc_log.write(f"   Ruta: {saved_path}\n\n")
                                            
                                            found_pdf = True
                                            pdf_count += 1
                                            processed_count += 1
                                        except Exception as e:
                                            fail_log.write(f"❌ [{email_id.decode()}] {sender_email} - {subject}\n")
                                            fail_log.write(f"   Motivo: Error al guardar adjunto: {e}\n\n")
                                            failed_count += 1
                        
                        if not found_pdf and is_trusted_sender(sender_email, trusted_emails):
                            # Correo de confianza pero sin PDFs
                            proc_log.write(f"ℹ️  [{email_id.decode()}] {sender_email} - {subject}\n")
                            if email_date:
                                proc_log.write(f"   Fecha correo: {email_date.strftime('%Y-%m-%d %H:%M')}\n")
                            proc_log.write(f"   Motivo: Sin adjuntos PDF\n\n")
                
                if (i % 10 == 0 or i == total_emails) and total_emails > 0:
                    print(f"   Progreso: {i}/{total_emails} correos revisados")
                    
            except Exception as e:
                fail_log.write(f"❌ [{email_id.decode()}] Error procesando: {e}\n\n")
                failed_count += 1
    
    # Cerrar conexión
    imap.close()
    imap.logout()
    
    # Resumen final
    print(f"\n{'='*50}")
    print("📊 RESUMEN:")
    print(f"   Correos revisados: {total_emails}")
    print(f"   Correos procesados (con PDF): {processed_count}")
    print(f"   PDFs descargados: {pdf_count}")
    print(f"   Correos fallidos/omitidos: {failed_count}")
    print(f"\n📁 PDFs guardados en: {ATTACHMENTS_DIR}")
    print(f"📝 Log procesados: {PROCESSED_LOG}")
    print(f"📝 Log fallidos: {FAILED_LOG}")
    print(f"{'='*50}")


if __name__ == "__main__":
    print("="*50)
    print("📥 DESCARGADOR DE PDFs DE CORREOS CONFIABLES")
    print("="*50)
    process_emails()
