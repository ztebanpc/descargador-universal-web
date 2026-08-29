import sys
import os
import shutil
import time
import requests
import re
import zipfile
import threading
import subprocess
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
    from PIL import Image
except ImportError:
    Image = None

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

def sanitize_filename(name):
    return re.sub(r'[^\w\-_.]', '_', name)

# ==========================================
# 🎵 AUDIO DOWNLOADER CON VELOCIDAD Y ANTICOPYRIGHT
# ==========================================
def process_audio_download(query, quality="192", format_type="mp3", speed="1.0", target_folder=AUDIO_DIR):
    try:
        print(f"[Audio] Buscando: {query} | Calidad: {quality}kbps | Formato: {format_type} | Velocidad: {speed}x")
        filename_base = f"audio_{int(time.time())}_{sanitize_filename(query[:25])}"
        out_template = os.path.join(target_folder, f"{filename_base}.%(ext)s")
        
        postprocessors = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3' if format_type == 'mp3' else format_type,
            'preferredquality': quality if quality in ('128', '192', '256', '320') else '192',
        }]
        
        postprocessor_args = []
        if speed == "1.06":
            # 1.06x pitch & speed shift (Anticopyright de CapCut)
            postprocessor_args = ['-filter:a', 'asetrate=46746,aresample=44100']
        elif speed and speed != "1.0":
            try:
                s_val = float(speed)
                postprocessor_args = ['-filter:a', f'atempo={s_val}']
            except ValueError:
                pass
                
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': postprocessors,
            'outtmpl': out_template,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
        }
        if postprocessor_args:
            ydl_opts['postprocessor_args'] = {'ffmpeg': postprocessor_args}
            
        search_query = query if query.startswith('http') else f"ytsearch1:{query}"
            
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.extract_info(search_query, download=True)
            except yt_dlp.utils.MaxDownloadsReached:
                pass
                
        # Buscar el archivo generado
        final_filename = None
        for f in os.listdir(target_folder):
            if f.startswith(filename_base):
                final_filename = f
                break
                
        if not final_filename:
            files = [f for f in os.listdir(target_folder) if f.endswith(('.mp3', '.m4a', '.wav', '.flac'))]
            if files:
                latest = max([os.path.join(target_folder, f) for f in files], key=os.path.getctime)
                final_filename = os.path.basename(latest)

        print(f"[Audio] [OK] Completado: {final_filename}")
        return final_filename
    except Exception as e:
        print(f"[Audio] [ERROR] Error en descarga de audio: {e}")
        return None

def process_bulk_audio(links, speed="1.0"):
    print(f"[Excel] Procesando {len(links)} enlaces en lote...")
    for link in links:
        process_audio_download(link, speed=speed, target_folder=EXCEL_DIR)
        time.sleep(1.5)
    print(f"[Excel] [OK] Todos los enlaces de Excel fueron procesados.")

# ==========================================
# 📌 PINTEREST SCRAPER & EXTRACTOR
# ==========================================
def extract_pinterest_raw_links(query, count=20):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    videos = []
    images = []
    
    if query.startswith('http') or 'pin.it' in query or 'pinterest.com' in query:
        url = query if query.startswith('http') else 'https://' + query
        try:
            res = requests.get(url, headers=headers, allow_redirects=True, timeout=12)
            if res.status_code == 200:
                html = res.text
                # Videos (.mp4)
                v_matches = re.findall(r'https://[^"\'\s<>]+?\.pinimg\.com/[^"\'\s<>]+\.mp4', html)
                for v in v_matches:
                    if v not in videos: videos.append(v)
                # Imágenes (/originals/)
                i_matches = re.findall(r'https://i\.pinimg\.com/[^"\'\s<>]+?\.(?:jpg|jpeg|png|webp)', html)
                for m in i_matches:
                    if any(bad in m for bad in ['avatar', '75x75', '200x150', '150x150', '30x30']):
                        continue
                    orig = re.sub(r'/(?:236x|474x|564x|736x)/', '/originals/', m)
                    if orig not in images:
                        images.append(orig)
        except Exception as e:
            print("[Pinterest] Error al resolver enlace:", e)
    else:
        # Búsqueda temática mediante gallery-dl
        try:
            range_req = max(40, count * 3)
            cmd = [sys.executable, "-m", "gallery_dl", "--get-urls", "--range", f"1-{range_req}", f"https://www.pinterest.com/search/pins/?q={query.replace(' ', '+')}"]
            out = subprocess.check_output(cmd, text=True, errors="ignore")
            for line in out.splitlines():
                u = line.strip().replace('| ', '').strip()
                if u.startswith('ytdl:'):
                    u = u.replace('ytdl:', '')
                if u.lower().split('?')[0].endswith(('.mp4', '.mov', '.webm')):
                    if u not in videos: videos.append(u)
                elif u.startswith('http'):
                    if any(bad in u for bad in ['avatar', '75x75', '200x150', '150x150', '30x30']):
                        continue
                    orig = re.sub(r'/(?:236x|474x|564x|736x)/', '/originals/', u)
                    if orig not in images:
                        images.append(orig)
        except Exception as e:
            print("[Pinterest] Error en búsqueda temática con gallery-dl:", e)

    return {"videos": videos, "images": images}

def process_pinterest_download(query, format_type='any', media_type='both', pin_tab='individual', count=20, target_folder=PINTEREST_DIR):
    try:
        print(f"[Pinterest] Procesando: {query} | Modo: {pin_tab} | Formato: {format_type} | Tipo: {media_type} | Cantidad: {count}")
        raw = extract_pinterest_raw_links(query, count=count)
        videos = raw.get("videos", [])
        images = raw.get("images", [])
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        saved_files = []
        batch_id = int(time.time())
        batch_folder = os.path.join(target_folder, f"lote_{batch_id}")
        os.makedirs(batch_folder, exist_ok=True)
        
        # 1. Modo Individual: Auto-detección de formato y tipo
        if pin_tab == 'individual':
            if videos:
                v_url = videos[0]
                try:
                    r = requests.get(v_url, headers=headers, stream=True, timeout=15)
                    if r.status_code == 200:
                        fname = f"pin_video_{batch_id}.mp4"
                        fp = os.path.join(batch_folder, fname)
                        with open(fp, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        saved_files.append(fname)
                except Exception as e:
                    print("[Pinterest] Error guardando video individual:", e)
            elif images:
                i_url = images[0]
                try:
                    r = requests.get(i_url, headers=headers, timeout=12)
                    if r.status_code == 200:
                        ext = i_url.split('?')[0].split('.')[-1].lower()
                        if ext not in ('jpg', 'jpeg', 'png', 'webp'): ext = 'jpg'
                        fname = f"pin_foto_{batch_id}.{ext}"
                        fp = os.path.join(batch_folder, fname)
                        with open(fp, 'wb') as f:
                            f.write(r.content)
                        saved_files.append(fname)
                except Exception as e:
                    print("[Pinterest] Error guardando foto individual:", e)
                    
            if saved_files:
                for f in saved_files:
                    shutil.copy(os.path.join(batch_folder, f), os.path.join(target_folder, f))
                return saved_files, None

        # 2. Modo Tablero o Temática (Filtrado por formato y tipo)
        limit = int(count) if (str(count).isdigit() and int(count) > 0) else 20
        if pin_tab == 'tablero' and limit == 20 and len(images) > 20:
            limit = len(images)
            
        items_to_download = []
        if media_type in ('both', 'videos'):
            for v in videos:
                items_to_download.append({'type': 'video', 'url': v})
        if media_type in ('both', 'photos'):
            for img in images:
                items_to_download.append({'type': 'image', 'url': img})
                
        count_saved = 0
        for item in items_to_download:
            if count_saved >= limit:
                break
                
            u = item['url']
            is_vid = item['type'] == 'video'
            
            try:
                if is_vid:
                    r = requests.get(u, headers=headers, stream=True, timeout=15)
                    if r.status_code == 200:
                        fname = f"pin_video_{batch_id}_{count_saved+1}.mp4"
                        fp = os.path.join(batch_folder, fname)
                        with open(fp, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        saved_files.append(fname)
                        count_saved += 1
                else:
                    r = requests.get(u, headers=headers, timeout=12)
                    if r.status_code == 200:
                        ext = u.split('?')[0].split('.')[-1].lower()
                        if ext not in ('jpg', 'jpeg', 'png', 'webp'): ext = 'jpg'
                        temp_name = f"temp_{count_saved}.{ext}"
                        temp_fp = os.path.join(batch_folder, temp_name)
                        with open(temp_fp, 'wb') as f:
                            f.write(r.content)
                            
                        # Validación de Ratio de Aspecto
                        if Image and format_type in ('9:16', 'vertical', '16:9', 'horizontal', '1:1', 'cuadrado'):
                            try:
                                with Image.open(temp_fp) as img_pil:
                                    w, h = img_pil.size
                                fmt = format_type.lower()
                                if fmt in ('9:16', 'vertical') and h < w * 1.15:
                                    os.remove(temp_fp); continue
                                elif fmt in ('16:9', 'horizontal') and w < h * 1.15:
                                    os.remove(temp_fp); continue
                                elif fmt in ('1:1', 'cuadrado') and not (0.85 <= w/h <= 1.15):
                                    os.remove(temp_fp); continue
                            except Exception:
                                pass
                                
                        final_fname = f"pin_foto_{batch_id}_{count_saved+1}.{ext}"
                        final_fp = os.path.join(batch_folder, final_fname)
                        shutil.move(temp_fp, final_fp)
                        saved_files.append(final_fname)
                        count_saved += 1
            except Exception:
                continue

        # Copiar archivos a la carpeta general
        for f in saved_files:
            shutil.copy(os.path.join(batch_folder, f), os.path.join(target_folder, f))
            
        # Generar ZIP
        zip_filename = f"pinterest_descarga_{batch_id}.zip"
        zip_path = os.path.join(target_folder, zip_filename)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for fname in saved_files:
                fpath = os.path.join(batch_folder, fname)
                if os.path.exists(fpath):
                    zipf.write(fpath, fname)
                    
        return saved_files, zip_filename
    except Exception as e:
        print("[Pinterest] [ERROR]:", e)
        return [], None

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
    speed = data.get('speed', '1.0')
    
    if not query:
        return jsonify({"status": "error", "message": "Debes ingresar un enlace o nombre."}), 400
        
    filename = process_audio_download(query, quality=quality, format_type=format_type, speed=speed)
    if filename:
        return jsonify({
            "status": "success",
            "message": f"Audio descargado exitosamente ({speed}x): {query}",
            "filename": filename,
            "download_url": f"/api/files/audio/{filename}"
        })
    return jsonify({"status": "error", "message": "No se pudo extraer el audio."}), 500

@app.route('/api/download_excel', methods=['POST'])
def download_excel():
    file = request.files.get('file')
    speed = request.form.get('speed', '1.0')
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

        threading.Thread(target=process_bulk_audio, args=(links, speed)).start()
        return jsonify({"status": "success", "message": f"Procesando {len(links)} audios desde Excel a {speed}x en segundo plano."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error leyendo archivo: {e}"}), 500

@app.route('/api/download_pinterest', methods=['POST'])
def download_pinterest():
    data = request.get_json(silent=True) or request.form
    query = data.get('query', '').strip()
    format_type = data.get('format', 'any')
    media_type = data.get('media_type', 'both')
    pin_tab = data.get('pin_tab', 'individual')
    count = data.get('cantidad', 20)
    
    if not query:
        return jsonify({"status": "error", "message": "Debes ingresar una URL o término."}), 400
        
    saved, zip_name = process_pinterest_download(query, format_type=format_type, media_type=media_type, pin_tab=pin_tab, count=count)
    if saved:
        file_urls = [f"/api/files/pinterest/{f}" for f in saved]
        zip_url = f"/api/files/pinterest/{zip_name}" if zip_name else None
        return jsonify({
            "status": "success",
            "message": f"Descargados {len(saved)} archivos en calidad original.",
            "total": len(saved),
            "files": file_urls,
            "zip_url": zip_url
        })
    return jsonify({"status": "error", "message": "No se encontraron fotos o el enlace no es accesible."}), 404

# ==========================================
# 🤖 ASISTENTE DE ÓRDENES IA
# ==========================================
@app.route('/api/ai_order_assistant', methods=['POST'])
def ai_order_assistant():
    data = request.get_json(silent=True) or request.form
    prompt = data.get('prompt', '').strip()
    speed = data.get('speed', '1.0')
    format_pref = data.get('format', 'any')
    
    if not prompt:
        return jsonify({"status": "error", "message": "Por favor ingresa o dicta una orden."}), 400
        
    slug = re.sub(r'[^\w\-_]', '_', prompt[:25]).strip('_') or "proyecto_capcut"
    prompt_lower = prompt.lower()
    
    # Extraer cantidades
    num_photos = 6
    photo_match = re.search(r'(\d+)\s*(?:fotos?|im[aá]gen(?:es)?)', prompt_lower)
    if photo_match: num_photos = int(photo_match.group(1))
        
    num_audios = 1
    audio_match = re.search(r'(\d+)\s*(?:audios?|cancion(?:es)?|m[uú]sicas?)', prompt_lower)
    if audio_match: num_audios = int(audio_match.group(1))

    clean_term = re.sub(r'\b(quiero|necesito|descargar|buscar|fotos?|audios?|cancion|imagenes|videos)\b', '', prompt, flags=re.IGNORECASE).strip()
    if not clean_term: clean_term = prompt

    return jsonify({
        "status": "success",
        "project_name": slug,
        "clean_term": clean_term,
        "plan": {
            "num_photos": num_photos,
            "num_audios": num_audios,
            "format": format_pref,
            "speed": speed,
            "audio_term": clean_term,
            "pin_term": clean_term
        }
    })

@app.route('/api/execute_project_order', methods=['POST'])
def execute_project_order():
    data = request.get_json(silent=True) or request.form
    project_name = sanitize_filename(data.get('project_name', f"proyecto_{int(time.time())}"))
    pin_term = data.get('pin_term', '')
    num_photos = int(data.get('num_photos', 6))
    audio_term = data.get('audio_term', '')
    speed = data.get('speed', '1.0')
    format_pref = data.get('format', 'any')
    
    project_folder = os.path.join(ORDENES_DIR, project_name)
    os.makedirs(project_folder, exist_ok=True)
    
    downloaded_files = []
    
    # 1. Descargar audios
    if audio_term:
        audio_file = process_audio_download(audio_term, speed=speed, target_folder=project_folder)
        if audio_file:
            downloaded_files.append(audio_file)
            
    # 2. Descargar Pinterest
    if pin_term:
        pin_files, _ = process_pinterest_download(pin_term, format_type=format_pref, pin_tab='tematica', count=num_photos, target_folder=project_folder)
        if pin_files:
            downloaded_files.extend(pin_files)
            
    # Crear ZIP unificado del proyecto
    zip_name = f"{project_name}_completo.zip"
    zip_path = os.path.join(ORDENES_DIR, zip_name)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for f in os.listdir(project_folder):
            fp = os.path.join(project_folder, f)
            if os.path.isfile(fp):
                zipf.write(fp, f)
                
    return jsonify({
        "status": "success",
        "message": f"Proyecto '{project_name}' completado con {len(downloaded_files)} recursos.",
        "total": len(downloaded_files),
        "zip_url": f"/api/files/ordenes/{zip_name}",
        "files": [f"/api/files/ordenes/{f}" for f in downloaded_files]
    })

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
