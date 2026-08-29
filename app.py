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
                v_matches = re.findall(r'https://[^"\'\s<>]+?\.pinimg\.com/[^"\'\s<>]+\.mp4', html)
                for v in v_matches:
                    if v not in videos: videos.append(v)
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

def process_pinterest_download(query, format_type='any', media_type='both', pin_tab='individual', count=1, target_folder=PINTEREST_DIR):
    try:
        req_count = int(count) if (str(count).isdigit() and int(count) > 0) else 1
        print(f"[Pinterest] Procesando: {query} | Modo: {pin_tab} | Formato: {format_type} | Tipo: {media_type} | Cantidad: {req_count}")
        raw = extract_pinterest_raw_links(query, count=req_count)
        videos = raw.get("videos", [])
        images = raw.get("images", [])
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        saved_files = []
        batch_id = int(time.time())
        batch_folder = os.path.join(target_folder, f"lote_{batch_id}")
        os.makedirs(batch_folder, exist_ok=True)
        
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

        # Tablero o Temática
        limit = req_count
        if pin_tab == 'tablero' and req_count == 1 and len(images) > 1:
            limit = len(images) # Si es tablero y no especificó número pequeño, descarga todo el tablero
            
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
                            
                        # Validación de Aspect Ratio
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

        for f in saved_files:
            shutil.copy(os.path.join(batch_folder, f), os.path.join(target_folder, f))
            
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
        return jsonify({"status": "error", "message": "Debes ingresar un enlace o nombre.", "note": "Verifica que el término de búsqueda no esté vacío."}), 400
        
    filename = process_audio_download(query, quality=quality, format_type=format_type, speed=speed)
    if filename:
        return jsonify({
            "status": "success",
            "message": f"Audio descargado exitosamente ({speed}x): {query}",
            "filename": filename,
            "download_url": f"/api/files/audio/{filename}"
        })
    return jsonify({"status": "error", "message": "No se pudo extraer el audio.", "note": "Comprueba que el video de YouTube esté disponible públicamente y no tenga restricciones de edad o región."}), 500

@app.route('/api/download_excel', methods=['POST'])
def download_excel():
    file = request.files.get('file')
    speed = request.form.get('speed', '1.0')
    if not file:
        return jsonify({"status": "error", "message": "No se subió ningún archivo.", "note": "Selecciona un archivo .xlsx o .csv válido."}), 400

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
            return jsonify({"status": "error", "message": "No se encontraron enlaces en el archivo.", "note": "Asegúrate de que las celdas contengan URLs completas que empiecen por http://"}), 400

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
    count = data.get('cantidad', 1)
    
    if not query:
        return jsonify({"status": "error", "message": "Debes ingresar una URL o término.", "note": "Pega un enlace de pin/tablero o escribe una palabra clave para buscar."}), 400
        
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
    return jsonify({
        "status": "error", 
        "message": "No se encontraron archivos con los criterios indicados.",
        "note": "Si seleccionaste un formato específico (ej. 9:16 o 16:9), es posible que los pines encontrados no coincidan con esa proporción. Prueba cambiando a 'Cualquiera' o ajusta el término de búsqueda."
    }), 404

# ==========================================
# 🤖 ASISTENTE DE ÓRDENES IA (Línea por Línea Inteligente)
# ==========================================
@app.route('/api/ai_order_assistant', methods=['POST'])
def ai_order_assistant():
    data = request.get_json(silent=True) or request.form
    prompt = data.get('prompt', '').strip()
    
    if not prompt:
        return jsonify({"status": "error", "message": "Por favor ingresa o dicta una orden."}), 400
        
    slug = re.sub(r'[^\w\-_]', '_', prompt[:25]).strip('_') or "proyecto_capcut"
    
    # Parser inteligente de líneas
    # Divide por comas, " y ", saltos de línea o conjunciones
    raw_segments = re.split(r'[,;\n]|\by\b', prompt, flags=re.IGNORECASE)
    items = []
    item_id = 1
    
    for seg in raw_segments:
        seg = seg.strip()
        if not seg: continue
        
        # Detectar cantidad
        count_match = re.search(r'(\d+)', seg)
        count = int(count_match.group(1)) if count_match else 1
        
        # Detectar tipo
        is_audio = any(w in seg.lower() for w in ['audio', 'cancion', 'canción', 'musica', 'música', 'mp3', 'sound', 'tema'])
        is_video = any(w in seg.lower() for w in ['video', 'vídeo', 'clip', 'reels', 'shorts', 'broll', 'b-roll'])
        is_photo = any(w in seg.lower() for w in ['foto', 'imagen', 'imágenes', 'portada', 'wallpaper', 'pic'])
        
        if is_audio:
            item_type = 'audio'
        elif is_video:
            item_type = 'video'
        else:
            item_type = 'photo'
            
        # Detectar formato / ratio
        if '9:16' in seg or 'vertical' in seg.lower():
            fmt = '9:16'
        elif '16:9' in seg or 'horizontal' in seg.lower():
            fmt = '16:9'
        elif '1:1' in seg or 'cuadrad' in seg.lower():
            fmt = '1:1'
        else:
            fmt = 'any' if item_type != 'audio' else 'mp3'
            
        # Detectar velocidad para audios
        speed = "1.0"
        if '1.06' in seg or 'anticopyright' in seg.lower() or 'anti copyright' in seg.lower():
            speed = "1.06"
        elif '1.25' in seg:
            speed = "1.25"
        elif '1.5' in seg:
            speed = "1.5"
            
        # Limpiar término
        clean = re.sub(r'(\d+|\b(de|fotos?|im[aá]genes|videos?|audios?|cancion(?:es)?|m[uú]sicas?|mp3|vertical|horizontal|cuadrada|1:1|9:16|16:9|1\.06x?|anticopyright|quiero|necesito|para|un|una|unos|unas)\b)', '', seg, flags=re.IGNORECASE).strip()
        if not clean: clean = seg.strip()
        
        items.append({
            "id": item_id,
            "term": clean,
            "type": item_type,
            "format": fmt,
            "speed": speed,
            "count": count
        })
        item_id += 1
        
    if not items:
        items.append({
            "id": 1,
            "term": prompt,
            "type": "photo",
            "format": "any",
            "speed": "1.0",
            "count": 5
        })

    return jsonify({
        "status": "success",
        "project_name": slug,
        "items": items
    })

@app.route('/api/execute_custom_order', methods=['POST'])
def execute_custom_order():
    data = request.get_json(silent=True) or request.form
    project_name = sanitize_filename(data.get('project_name', f"proyecto_{int(time.time())}"))
    items = data.get('items', [])
    
    if not items:
        return jsonify({"status": "error", "message": "No hay elementos en la orden."}), 400
        
    project_folder = os.path.join(ORDENES_DIR, project_name)
    os.makedirs(project_folder, exist_ok=True)
    downloaded_files = []
    
    for itm in items:
        term = itm.get('term', '').strip()
        itype = itm.get('type', 'photo')
        fmt = itm.get('format', 'any')
        speed = itm.get('speed', '1.0')
        cnt = int(itm.get('count', 1))
        
        if not term: continue
        
        if itype == 'audio':
            f = process_audio_download(term, speed=speed, target_folder=project_folder)
            if f: downloaded_files.append(f)
        else:
            media_t = 'videos' if itype == 'video' else 'photos'
            pins, _ = process_pinterest_download(term, format_type=fmt, media_type=media_t, pin_tab='tematica', count=cnt, target_folder=project_folder)
            if pins: downloaded_files.extend(pins)
            
    zip_name = f"{project_name}_completo.zip"
    zip_path = os.path.join(ORDENES_DIR, zip_name)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for f in os.listdir(project_folder):
            fp = os.path.join(project_folder, f)
            if os.path.isfile(fp):
                zipf.write(fp, f)
                
    return jsonify({
        "status": "success",
        "message": f"Proyecto completado con {len(downloaded_files)} archivos descargados.",
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
    print("[Sistema] Iniciando Descargador Universal...")
    app.run(host='0.0.0.0', port=10000, debug=False)
