import os
import sys
import re
import time
import json
import zipfile
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
import yt_dlp
import requests

try:
    import openpyxl
except ImportError:
    openpyxl = None

# Configuración básica
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
AUDIO_DIR = os.path.join(DOWNLOAD_DIR, 'audio')
VIDEO_DIR = os.path.join(DOWNLOAD_DIR, 'video')
PINTEREST_DIR = os.path.join(DOWNLOAD_DIR, 'pinterest')

for d in [DOWNLOAD_DIR, AUDIO_DIR, VIDEO_DIR, PINTEREST_DIR]:
    os.makedirs(d, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")

# ==========================================
# 🛡️ FILTROS DE PUREZA (Aesthetic & B-Roll)
# ==========================================
CLEAN_POSITIVE_KEYWORDS = ["aesthetic", "b-roll", "landscape", "background", "virgin video", "scenery"]
FORBIDDEN_KEYWORDS = ["tiktok", "funny", "shorts", "meme", "watermark", "text", "sticker"]

def sanitize_query(query):
    if not query:
        return ""
    pattern = r"\b(?:" + "|".join([re.escape(w) for w in FORBIDDEN_KEYWORDS]) + r")\b"
    sanitized = re.sub(pattern, "", query, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized

def build_clean_query(query):
    clean = sanitize_query(query)
    existing = set(clean.lower().split())
    missing = [w for w in CLEAN_POSITIVE_KEYWORDS if w.lower() not in existing]
    return f"{clean} {' '.join(missing[:4])}".strip()

# ==========================================
# 🎵 MOTOR DE DESCARGA DE AUDIO (yt-dlp)
# ==========================================
def download_audio_sync(query):
    if not query.startswith("http"):
        query = f"ytsearch1:{query} Audio Oficial"
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(AUDIO_DIR, '%(title).80s.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=True)
        title = info.get('title', 'audio')
        filename = f"{title[:80]}.mp3"
        # Comprobar el nombre exacto guardado
        for f in os.listdir(AUDIO_DIR):
            if f.endswith('.mp3') and (title[:20] in f or f == filename):
                return f, title
        # fallback al último archivo creado
        files = [os.path.join(AUDIO_DIR, f) for f in os.listdir(AUDIO_DIR) if f.endswith('.mp3')]
        if files:
            latest = max(files, key=os.path.getctime)
            return os.path.basename(latest), title
    return None, None

def download_video_sync(url):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(VIDEO_DIR, '%(title).80s.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get('title', 'video')
        for f in os.listdir(VIDEO_DIR):
            if (f.endswith('.mp4') or f.endswith('.mkv')) and title[:20] in f:
                return f, title
        files = [os.path.join(VIDEO_DIR, f) for f in os.listdir(VIDEO_DIR) if f.endswith('.mp4')]
        if files:
            latest = max(files, key=os.path.getctime)
            return os.path.basename(latest), title
    return None, None

def search_pinterest_images(query, limit=150):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        # 1. Si es un enlace directo (pin.it o pinterest.com)
        if query.startswith("http://") or query.startswith("https://") or "pin.it" in query or "pinterest.com" in query:
            url_to_fetch = query if query.startswith("http") else "https://" + query
            res = requests.get(url_to_fetch, headers=headers, allow_redirects=True, timeout=12)
            if res.status_code == 200:
                matches = re.findall(r'https://i\.pinimg\.com/[^"\'\s<>]+?\.(?:jpg|jpeg|png|webp)', res.text)
                images = []
                for m in matches:
                    if any(bad in m for bad in ['avatar', '75x75', '200x150', '150x150', '30x30']):
                        continue
                    orig = re.sub(r'/(?:236x|474x|564x|736x)/', '/originals/', m)
                    if orig not in [img["url"] for img in images]:
                        pin_id = f"pin_{len(images)+1}"
                        images.append({"id": pin_id, "title": f"Pinterest {len(images)+1}", "url": orig})
                    if len(images) >= limit:
                        break
                if images:
                    return images
        
        # 2. Si es una búsqueda temática / palabra clave
        clean_q = build_clean_query(query)
        url = f"https://www.pinterest.com/resource/BaseSearchResource/get/?source_url=/search/pins/?q={clean_q}&data=%7B%22options%22%3A%7B%22query%22%3A%22{clean_q}%22%2C%22scope%22%3A%22pins%22%7D%2C%22context%22%3A%7B%7D%7D"
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            data = res.json()
            results = data.get("resource_response", {}).get("data", {}).get("results", [])
            images = []
            for r in results:
                imgs = r.get("images", {})
                orig = imgs.get("orig", {}).get("url") or imgs.get("736x", {}).get("url")
                pin_id = r.get("id", str(time.time()))
                title = r.get("grid_title") or r.get("title") or query
                if orig and orig not in [img["url"] for img in images]:
                    images.append({"id": pin_id, "title": title, "url": orig})
                if len(images) >= limit:
                    break
            return images
    except Exception as e:
        print(f"Error Pinterest API: {e}")
    return []

# ==========================================
# 🧹 AUTOLIMPIEZA (14 días)
# ==========================================
def cleanup_worker():
    while True:
        try:
            now = time.time()
            for root, dirs, files in os.walk(DOWNLOAD_DIR):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.stat(fp).st_mtime < now - 14 * 86400:
                        os.remove(fp)
        except Exception:
            pass
        time.sleep(3600 * 12)

threading.Thread(target=cleanup_worker, daemon=True).start()

# ==========================================
# 🌐 RUTAS Y ENDPOINTS DEL SERVIDOR WEB
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/download_audio', methods=['POST'])
def api_download_audio():
    data = request.get_json(silent=True) or request.form
    query = data.get('query', '').strip()
    if not query:
        return jsonify({"status": "error", "message": "Debes ingresar un nombre o enlace."}), 400
    
    try:
        filename, title = download_audio_sync(query)
        if filename:
            return jsonify({
                "status": "success",
                "filename": filename,
                "title": title,
                "download_url": f"/api/files/audio/{filename}"
            })
        return jsonify({"status": "error", "message": "No se pudo extraer el audio."}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/download_video', methods=['POST'])
def api_download_video():
    data = request.get_json(silent=True) or request.form
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"status": "error", "message": "Debes ingresar un enlace de video."}), 400
    
    try:
        filename, title = download_video_sync(url)
        if filename:
            return jsonify({
                "status": "success",
                "filename": filename,
                "title": title,
                "download_url": f"/api/files/video/{filename}"
            })
        return jsonify({"status": "error", "message": "No se pudo descargar el video."}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/download_excel', methods=['POST'])
def api_download_excel():
    file = request.files.get('file')
    if not file:
        return jsonify({"status": "error", "message": "No se adjuntó ningún archivo."}), 400

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
            return jsonify({"status": "error", "message": "Formato no soportado. Usa Excel (.xlsx) o .csv"}), 400

        if not links:
            return jsonify({"status": "error", "message": "No se encontraron enlaces en el archivo."}), 400

        # Descargar audios en segundo plano
        def bulk_worker(items):
            for link in items:
                try:
                    download_audio_sync(link)
                except Exception:
                    pass
        threading.Thread(target=bulk_worker, args=(links,)).start()

        return jsonify({
            "status": "success",
            "message": f"Se procesaron {len(links)} enlaces. La descarga masiva está en progreso.",
            "total_links": len(links)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error leyendo archivo: {e}"}), 500

from concurrent.futures import ThreadPoolExecutor

@app.route('/api/download_pinterest', methods=['POST'])
def api_download_pinterest():
    data = request.get_json(silent=True) or request.form
    query = data.get('query', '').strip()
    format_type = data.get('format', 'any')
    media_type = data.get('media_type', 'both')
    
    if not query:
        return jsonify({"status": "error", "message": "Debes ingresar una URL o término."}), 400
    
    try:
        images = search_pinterest_images(query, limit=150)
        if not images:
            return jsonify({"status": "error", "message": "No se encontraron fotos o el enlace no es accesible."}), 404
        
        batch_id = int(time.time())
        batch_folder = os.path.join(PINTEREST_DIR, f"batch_{batch_id}")
        os.makedirs(batch_folder, exist_ok=True)
        
        # Guardar directamente como archivos individuales .jpg/.png
        def download_single_pin(item):
            try:
                img_url = item['url']
                r = requests.get(img_url, timeout=10)
                if r.status_code == 200:
                    raw_name = img_url.split('/')[-1].split('?')[0]
                    if not raw_name.endswith(('.jpg', '.png', '.jpeg', '.webp')):
                        raw_name += ".jpg"
                    fp = os.path.join(PINTEREST_DIR, raw_name)
                    with open(fp, "wb") as f:
                        f.write(r.content)
                    return raw_name
            except Exception:
                return None
            return None

        # Descarga ultrarrápida en paralelo con 12 hilos
        with ThreadPoolExecutor(max_workers=12) as executor:
            downloaded = list(executor.map(download_single_pin, images))
        
        saved = [f for f in downloaded if f]
        
        if not saved:
            return jsonify({"status": "error", "message": "No se pudieron descargar las imágenes."}), 500
        
        return jsonify({
            "status": "success",
            "message": f"Descargadas {len(saved)} fotos exitosamente a tu carpeta de imágenes.",
            "total": len(saved),
            "files": [f"/api/files/pinterest/{f}" for f in saved]
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/files/<category>/<filename>')
def serve_file(category, filename):
    folder_map = {
        'audio': AUDIO_DIR,
        'video': VIDEO_DIR,
        'pinterest': PINTEREST_DIR
    }
    target_dir = folder_map.get(category, DOWNLOAD_DIR)
    return send_from_directory(target_dir, filename, as_attachment=True)

@app.route('/api/list_files')
def list_files():
    all_files = []
    for cat, d in [('audio', AUDIO_DIR), ('video', VIDEO_DIR), ('pinterest', PINTEREST_DIR)]:
        if os.path.exists(d):
            for f in os.listdir(d):
                fp = os.path.join(d, f)
                if os.path.isfile(fp):
                    all_files.append({
                        "name": f,
                        "category": cat,
                        "size_mb": round(os.path.getsize(fp) / (1024 * 1024), 2),
                        "date": datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M"),
                        "download_url": f"/api/files/{cat}/{f}"
                    })
    all_files.sort(key=lambda x: x['date'], reverse=True)
    return jsonify({"status": "success", "files": all_files})

@app.route('/api/download_zip')
def download_all_zip():
    zip_path = os.path.join(BASE_DIR, "descargas_completas.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            for file in files:
                fp = os.path.join(root, file)
                rel_path = os.path.relpath(fp, DOWNLOAD_DIR)
                zipf.write(fp, rel_path)
    return send_file(zip_path, as_attachment=True, download_name="descargas_universal.zip")

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "Descargador Universal Web"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
