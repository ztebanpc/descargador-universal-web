import sys
import os
import shutil
import time
import requests
import re
import threading
from concurrent.futures import ThreadPoolExecutor

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from flask import Flask, render_template, request, jsonify, send_from_directory
import yt_dlp

try:
    import openpyxl
except ImportError:
    openpyxl = None

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
AUDIO_DIR = os.path.join(DOWNLOAD_DIR, 'audio')
PINTEREST_DIR = os.path.join(DOWNLOAD_DIR, 'pinterest')
EXCEL_DIR = os.path.join(DOWNLOAD_DIR, 'excel')
ORDENES_DIR = os.path.join(DOWNLOAD_DIR, 'ordenes')

for d in [AUDIO_DIR, PINTEREST_DIR, EXCEL_DIR, ORDENES_DIR]:
    os.makedirs(d, exist_ok=True)

# Añadir node al PATH si existe localmente
sistema_dir = os.path.dirname(os.path.abspath(__file__))
if sistema_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = sistema_dir + os.pathsep + os.environ.get("PATH", "")

# ==========================================
# 🎵 AUDIO DOWNLOADER (yt-dlp)
# ==========================================
def process_audio_download(query, quality="192", format_type="mp3"):
    try:
        print(f"[Audio] Buscando y procesando: {query} ({quality}kbps)...")
        filename_base = f"audio_{int(time.time())}"
        out_template = os.path.join(AUDIO_DIR, f"{filename_base}.%(ext)s")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3' if format_type == 'mp3' else format_type,
                'preferredquality': quality if quality in ('128', '192', '256', '320') else '192',
            }],
            'outtmpl': out_template,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
        }
        
        search_query = query if query.startswith('http') else f"ytsearch1:{query}"
            
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(search_query, download=True)
            except yt_dlp.utils.MaxDownloadsReached:
                pass
                
        # Buscar el archivo generado
        final_filename = f"{filename_base}.mp3"
        for f in os.listdir(AUDIO_DIR):
            if f.startswith(filename_base):
                final_filename = f
                break
                
        print(f"[Audio] [OK] Audio completado: {final_filename}")
        return final_filename
    except Exception as e:
        print(f"[Audio] [ERROR] Error descargando audio {query}: {e}")
        return None

def process_bulk_audio(links):
    print(f"[Excel] Procesando {len(links)} enlaces en lote...")
    for link in links:
        process_audio_download(link)
        time.sleep(1.5)
    print(f"[Excel] [OK] Todos los enlaces de Excel fueron procesados.")

# ==========================================
# 📌 PINTEREST DOWNLOADER (Ultra-rápido multihilo)
# ==========================================
def process_pinterest_download(query, format_type='any', media_type='both', pin_tab='individual'):
    try:
        print(f"[Pinterest] Iniciando descarga para: {query}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        links = []
        if query.startswith('http') or 'pin.it' in query or 'pinterest.com' in query:
            url = query if query.startswith('http') else 'https://' + query
            res = requests.get(url, headers=headers, allow_redirects=True, timeout=12)
            if res.status_code == 200:
                matches = re.findall(r'https://i\.pinimg\.com/[^"\'\s<>]+?\.(?:jpg|jpeg|png|webp)', res.text)
                for m in matches:
                    if any(bad in m for bad in ['avatar', '75x75', '200x150', '150x150', '30x30']):
                        continue
                    orig = re.sub(r'/(?:236x|474x|564x|736x)/', '/originals/', m)
                    if orig not in links:
                        links.append(orig)
        else:
            clean_q = query.replace(' ', '%20')
            api_url = f"https://www.pinterest.com/resource/BaseSearchResource/get/?source_url=/search/pins/?q={clean_q}&data=%7B%22options%22%3A%7B%22query%22%3A%22{clean_q}%22%2C%22scope%22%3A%22pins%22%7D%2C%22context%22%3A%7B%7D%7D"
            res = requests.get(api_url, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                results = data.get("resource_response", {}).get("data", {}).get("results", [])
                for r in results:
                    imgs = r.get("images", {})
                    orig = imgs.get("orig", {}).get("url") or imgs.get("736x", {}).get("url")
                    if orig and orig not in links:
                        links.append(orig)

        limit = 1 if pin_tab == 'individual' else (len(links) if pin_tab == 'todas' else min(len(links), 60))
        target_links = links[:limit]
        
        saved_files = []
        def download_one(link):
            try:
                r = requests.get(link, headers=headers, timeout=10)
                if r.status_code == 200:
                    raw_name = link.split('/')[-1].split('?')[0]
                    if not raw_name.endswith(('.jpg', '.png', '.jpeg', '.webp')):
                        raw_name += ".jpg"
                    filename = f"pin_{int(time.time())}_{raw_name}"
                    fp = os.path.join(PINTEREST_DIR, filename)
                    with open(fp, 'wb') as f:
                        f.write(r.content)
                    return filename
            except Exception:
                return None
            return None

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(download_one, target_links))

        saved_files = [f for f in results if f]
        print(f"[Pinterest] [OK] Descarga finalizada: {len(saved_files)} fotos guardadas.")
        return saved_files
    except Exception as e:
        print(f"[Pinterest] [ERROR] Error en Pinterest Scraper: {e}")
        return []

# ==========================================
# 🧹 AUTOLIMPIEZA (14 días)
# ==========================================
def cleanup_old_files():
    while True:
        now = time.time()
        for folder in [AUDIO_DIR, PINTEREST_DIR, EXCEL_DIR, ORDENES_DIR]:
            if os.path.exists(folder):
                for root, dirs, files in os.walk(folder):
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        try:
                            if os.stat(filepath).st_mtime < now - 14 * 86400:
                                os.remove(filepath)
                        except Exception:
                            pass
        time.sleep(86400)

# ==========================================
# 🌐 RUTAS FLASK
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({"status": "ok", "service": "descargador-universal-web"}), 200

@app.route('/api/download_audio', methods=['POST'])
def download_audio():
    data = request.get_json(silent=True) or request.form
    query = data.get('query', '').strip()
    quality = data.get('quality', '192')
    format_type = data.get('format', 'mp3')
    
    if not query:
        return jsonify({"status": "error", "message": "Debes ingresar un enlace o nombre."}), 400
        
    filename = process_audio_download(query, quality, format_type)
    if filename:
        return jsonify({
            "status": "success",
            "message": f"Audio descargado exitosamente: {query}",
            "filename": filename,
            "download_url": f"/api/files/audio/{filename}"
        })
    return jsonify({"status": "error", "message": "No se pudo extraer el audio."}), 500

@app.route('/api/download_excel', methods=['POST'])
def download_excel():
    file = request.files.get('file')
    if not file:
        return jsonify({"status": "error", "message": "No se subió ningún archivo."}), 400

    links = []
    fname = file.filename.lower()
    try:
        if fname.endswith('.csv'):
            import csv, io
            content = file.read().decode('utf-8', errors='ignore')
            reader = csv.reader(io.StringIO(content))
            for row in reader:
                for cell in row:
                    c = cell.strip()
                    if c.startswith('http'):
                        links.append(c)
        elif fname.endswith('.xlsx') or fname.endswith('.xls'):
            if openpyxl is None:
                return jsonify({"status": "error", "message": "Librería openpyxl no instalada."}), 500
            import io
            wb = openpyxl.load_workbook(io.BytesIO(file.read()))
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                for row in ws.iter_rows(values_only=True):
                    for cell in row:
                        if cell and str(cell).strip().startswith('http'):
                            links.append(str(cell).strip())
        else:
            return jsonify({"status": "error", "message": "Formato no soportado. Usa .xlsx o .csv"}), 400

        if not links:
            return jsonify({"status": "error", "message": "No se encontraron enlaces en el archivo."}), 400

        threading.Thread(target=process_bulk_audio, args=(links,)).start()
        return jsonify({"status": "success", "message": f"Procesando {len(links)} audios desde Excel en segundo plano."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error leyendo archivo: {e}"}), 500

@app.route('/api/download_pinterest', methods=['POST'])
def download_pinterest():
    data = request.get_json(silent=True) or request.form
    query = data.get('query', '').strip()
    format_type = data.get('format', 'any')
    media_type = data.get('media_type', 'both')
    pin_tab = data.get('pin_tab', 'individual')
    
    if not query:
        return jsonify({"status": "error", "message": "Debes ingresar una URL o término."}), 400
        
    saved = process_pinterest_download(query, format_type, media_type, pin_tab)
    if saved:
        file_urls = [f"/api/files/pinterest/{f}" for f in saved]
        return jsonify({
            "status": "success",
            "message": f"Descargadas {len(saved)} fotos en alta resolución.",
            "total": len(saved),
            "files": file_urls
        })
    return jsonify({"status": "error", "message": "No se encontraron fotos o el enlace no es accesible."}), 404

@app.route('/api/files/<category>/<filename>')
def serve_file(category, filename):
    folder_map = {
        'audio': AUDIO_DIR,
        'pinterest': PINTEREST_DIR,
        'excel': EXCEL_DIR,
        'ordenes': ORDENES_DIR
    }
    target_dir = folder_map.get(category, DOWNLOAD_DIR)
    return send_from_directory(target_dir, filename, as_attachment=True)

if __name__ == '__main__':
    print("[Sistema] Iniciando mecanismo de autolimpieza (14 días)...")
    threading.Thread(target=cleanup_old_files, daemon=True).start()
    print("[Sistema] Iniciando Descargador Universal...")
    app.run(host='0.0.0.0', port=10000, debug=False)
