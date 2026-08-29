import sys
import os
import shutil
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from flask import Flask, render_template, request, jsonify
import threading
import yt_dlp
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

try:
    import openpyxl
except ImportError:
    openpyxl = None

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL_AUDIO_DIR = os.path.join(BASE_DIR, 'Descargas_YouTube')
MANUAL_PIN_DIR = os.path.join(BASE_DIR, 'Descargas_Pinterest')
BOT_DIR = os.path.join(BASE_DIR, 'Descargas_Ordenes')
EXCEL_DIR = os.path.join(BASE_DIR, 'Descargas_Excel')

# Añadir la carpeta Sistema al PATH para que yt-dlp encuentre node.exe
sistema_dir = os.path.dirname(os.path.abspath(__file__))
if sistema_dir not in os.environ["PATH"]:
    os.environ["PATH"] += os.pathsep + sistema_dir

global_status = {"message": "Esperando..."}

def process_audio_download(query, bot_event=None, limit=1, folder_override=None, speed="1.0"):
    try:
        global_status["message"] = f"Preparando audio: {query}..."
        
        if folder_override:
            target_dir = folder_override
            outtmpl = os.path.join(target_dir, '[AUDIO] %(title)s.%(ext)s')
        elif bot_event:
            safe_event = bot_event.replace(' ', '_').replace('#', '')
            target_dir = os.path.join(BOT_DIR, safe_event)
            outtmpl = os.path.join(target_dir, '[AUDIO] %(title)s.%(ext)s')
        else:
            if "list=" in query and query.startswith("http"):
                target_dir = os.path.join(MANUAL_AUDIO_DIR, "Playlists")
                outtmpl = os.path.join(target_dir, '%(playlist_title)s', '[AUDIO] %(title)s.%(ext)s')
            elif query.startswith("http"):
                target_dir = os.path.join(MANUAL_AUDIO_DIR, "Individuales")
                outtmpl = os.path.join(target_dir, '[AUDIO] %(title)s.%(ext)s')
            else:
                safe_name = query.replace(' ', '_').replace('#', '')
                target_dir = os.path.join(MANUAL_AUDIO_DIR, "Tematicas", safe_name)
                outtmpl = os.path.join(target_dir, '[AUDIO] %(title)s.%(ext)s')
            
        os.makedirs(target_dir, exist_ok=True)
        files_before = set(os.listdir(target_dir))
        
        if not query.startswith("http") and not query.startswith("ytsearch"):
            search_query = f"ytsearch{limit}:{query}"
        else:
            search_query = query
            
        def audio_filter(info, *, incomplete):
            if info.get('is_live'): return 'Es un livestream infinito'
            return None

        # Si es una URL de playlist, NO poner límite de descargas
        es_playlist = 'list=' in query and query.startswith('http')
        
        postprocessors = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
        if speed and speed != "1.0":
            postprocessors.append({
                'key': 'FFmpegMetadata',
            })
            if speed == "1.06":
                # Aumenta velocidad a 1.06 y sube tono (pitch) en 6% (Anticopyright)
                ydl_opts_postprocessor_args = {'ffmpeg': ['-filter:a', 'asetrate=46746,aresample=44100']}
            else:
                ydl_opts_postprocessor_args = {'ffmpeg': [f'-filter:a', f'atempo={speed}']}
        else:
            ydl_opts_postprocessor_args = {}

        def my_hook(d):
            if d['status'] == 'downloading':
                p = d.get('_percent_str', 'N/A').strip()
                global_status["message"] = f"Descargando audio: {p} de {query}"

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': outtmpl,
            'noplaylist': False,
            'quiet': False,
            'ignoreerrors': True,
            'color': 'no_color',
            'match_filter': audio_filter,
            'postprocessors': postprocessors,
            'postprocessor_args': ydl_opts_postprocessor_args,
            'progress_hooks': [my_hook]
        }
        # Solo limitar si es búsqueda por nombre o individual (no playlist)
        if not es_playlist:
            ydl_opts['max_downloads'] = limit
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([search_query])
            except yt_dlp.utils.MaxDownloadsReached:
                pass # Es normal si se alcanza el límite

        # Pequeña pausa para evitar rate limit de YouTube si vienen muy rápido
        import time
        import random
        time.sleep(random.uniform(3.5, 6.0))

        # Limpiar miniaturas basura si yt-dlp las bajó
        files_after = set(os.listdir(target_dir))
        for f in files_after:
            if f.startswith("[AUDIO]") and not f.endswith(('.mp3', '.m4a')):
                try: os.remove(os.path.join(target_dir, f))
                except: pass
                
        new_audio_files = [f for f in (files_after - files_before) if f.endswith(('.mp3', '.m4a'))]
        if new_audio_files:
            resultado = f"ÉXITO: Audio descargado -> {query}"
        else:
            resultado = f"OMITIDO (Copyright/Privado): No se pudo extraer -> {query}"
            
        global_status["message"] = resultado
        return resultado
    except Exception as e:
        error_str = str(e)
        if "Maximum number of downloads reached" in error_str:
            # yt-dlp arroja esto como error cuando cumple el límite, pero es un éxito
            resultado = f"ÉXITO: Audio descargado -> {query}"
            global_status["message"] = resultado
            return resultado
            
        resultado = f"ERROR (Audio {query}): {error_str}"
        global_status["message"] = resultado
        return resultado

def process_bulk_audio(links, speed="1.0"):
    for link in links:
        process_audio_download(link, folder_override=EXCEL_DIR, speed=speed)
    global_status["message"] = f"ÉXITO: Lote de {len(links)} links de Excel completado a {speed}x"

def process_pinterest_download(query, cantidad, media_type, bot_event=None, img_format="Cualquiera", pin_tab=None, azar=False):
    try:
        # Si cantidad viene vacía o no es número positivo, se asume Sin Límite (9999)
        limit = int(cantidad) if (str(cantidad).isdigit() and int(cantidad) > 0) else 9999
        
        # Normalizar media_type para aceptar 'Solo Fotos', 'Solo Videos', 'Ambos', 'fotos', 'videos', 'both'
        m_lower = str(media_type).lower()
        if 'foto' in m_lower or 'photo' in m_lower or 'image' in m_lower:
            media_type = 'fotos'
        elif 'video' in m_lower:
            media_type = 'videos'
        else:
            media_type = 'both'
            
        print(f"[Pinterest] 🚀 Iniciando: {query} | Tipo: {media_type} | Formato: {img_format} | Límite: {limit}")
        
        if bot_event:
            safe_event = bot_event.replace(' ', '_').replace('#', '')
            target_dir = os.path.join(BOT_DIR, safe_event)
        else:
            if query.startswith('http'):
                titulo_enlace = ""
                # FIX: Resolver enlaces cortos (pin.it o url_shortener móvil) y obtener el título de la página
                try:
                    import requests
                    import re
                    response = requests.get(query, allow_redirects=True, timeout=5, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    if "pin.it" in query or "url_shortener" in query:
                        query = response.url
                    
                    # Intentar extraer el título de la página para la carpeta
                    match = re.search(r'<title.*?>(.*?)</title>', response.text, re.IGNORECASE | re.DOTALL)
                    if match:
                        titulo_raw = match.group(1).split('|')[0].strip()
                        # Limpiar el título para nombre de carpeta
                        titulo_enlace = re.sub(r'[^\w\s-]', '', titulo_raw).strip().replace(' ', '_')
                        # Si el título es genérico o muy largo, lo recortamos un poco
                        if len(titulo_enlace) > 50:
                            titulo_enlace = titulo_enlace[:50]
                except:
                    pass
                
                safe_name = query.strip('/').split('/')[-1]
                
                # FIX: Si es un enlace de búsqueda manual, extraer el texto para el nombre de la carpeta
                if '/search/' in query:
                    import urllib.parse
                    q_param = urllib.parse.parse_qs(urllib.parse.urlparse(query).query).get('q', [''])[0]
                    if q_param: 
                        safe_name = q_param
                        titulo_enlace = "" # Evita que el <title> de la web lo sobreescriba

                if titulo_enlace and titulo_enlace.lower() not in ['pinterest', 'pin', '']:
                    safe_name = titulo_enlace
                    
                if not safe_name or safe_name == 'pin': safe_name = 'url_directa'
                
                if pin_tab == 'tablero':
                    target_dir = os.path.join(MANUAL_PIN_DIR, safe_name)
                elif pin_tab == 'relacionados':
                    target_dir = os.path.join(MANUAL_PIN_DIR, safe_name)
                elif pin_tab == 'individual' or '/pin/' in query:
                    target_dir = os.path.join(MANUAL_PIN_DIR, 'Individuales')
                else:
                    target_dir = os.path.join(MANUAL_PIN_DIR, safe_name)
            else:
                safe_name = query.replace(' ', '_').replace('#', '')
                target_dir = os.path.join(MANUAL_PIN_DIR, safe_name)
            
        os.makedirs(target_dir, exist_ok=True)
        
        import subprocess, sys, random, urllib.request
        from subprocess import CREATE_NO_WINDOW
        
        # --- LISTA NEGRA de palabras prohibidas (nunca deben aparecer en búsquedas) ---
        FORBIDDEN_KEYWORDS = ['tiktok', 'funny', 'shorts', 'meme', 'sticker', 'watermark', 'text overlay']
        
        # --- LISTA BLANCA de expansiones limpias (solo videos aesthetic/paisaje) ---
        CLEAN_EXPANSIONS = ['aesthetic', 'background', 'b-roll', 'cinematic', 'visuals', 'scenery', 'landscape']
        
        # 1. Obtener URLs (Expansión Dinámica de Pinterest con Descarga Temprana)
        urls = []
        foto_urls = []
        video_urls = []
        if query.startswith('http'):
            # La redirección ya fue manejada arriba si era un shortlink
            query = query.replace('://es.pinterest.com', '://www.pinterest.com')
            query = query.replace('://ar.pinterest.com', '://www.pinterest.com')
            query = query.replace('://br.pinterest.com', '://www.pinterest.com')
            query = query.replace('://mx.pinterest.com', '://www.pinterest.com')
            query = query.replace('://co.pinterest.com', '://www.pinterest.com')
            query = query.replace('://in.pinterest.com', '://www.pinterest.com')
            
            # FIX: Si es un pin y pidió cantidad (está en Temática Avanzada), forzar relacionados
            if pin_tab == 'relacionados' or ('/pin/' in query and limit > 1):
                query = query.strip()
                if query.endswith('/'): query = query[:-1]
                if not query.endswith('#related'): query += '#related'
                
            range_max = 5000 if limit == 9999 else max(200, limit * 5)
            
            # Dividir la búsqueda de relacionados para obtener los primeros 50 rápido
            search_items = [{"url": query, "range": min(50, range_max)}]
            if range_max > 50:
                # El hilo de fondo raspará el resto
                search_items.append({"url": query, "range": range_max})
        else:
            # Sanitizar el query: eliminar palabras prohibidas
            palabras_raw = query.replace('#', '').split()
            palabras = [p for p in palabras_raw if p.lower() not in FORBIDDEN_KEYWORDS]
            query_limpio = ' '.join(palabras) if palabras else query
            
            range_max = max(1500, limit * 15)
            # Dividir la bǧsqueda para obtener los primeros 50 rǭpido y no congelar la pantalla
            search_path = "search/videos" if media_type == "Solo Video" else "search/pins"
            search_items = [{"url": f"https://www.pinterest.com/{search_path}/?q={query_limpio.replace(' ', '+')}", "range": min(50, range_max)}]
            if range_max > 50:
                search_items.append({"url": f"https://www.pinterest.com/{search_path}/?q={query_limpio.replace(' ', '+')}", "range": range_max})
            
            if len(palabras) >= 1:
                base_q = "+".join(palabras[:3])
                for expansion in CLEAN_EXPANSIONS:
                    search_items.append({"url": f"https://www.pinterest.com/{search_path}/?q={base_q}+{expansion}", "range": range_max})

        trigger_batch = 1  # Empezar a descargar inmediatamente tras la 1ra red (incluso para relacionados)
        bg_thread = None
        remaining_urls_container = {'nuevas': []}
        
        for i, item in enumerate(search_items):
            s_url = item["url"]
            r_max = item["range"]
            try:
                if len(search_items) == 1 or i == 0:
                    global_status["message"] = "Espere un momento. Buscando y procesando el contenido... Nos estamos asegurando de bajar el archivo en la máxima calidad original disponible."
                else:
                    global_status["message"] = f"Explorando búsqueda {i+1} de {len(search_items)} a fondo. Esto toma unos segundos, ¡tenga paciencia!..."
                
                comando = [sys.executable, "-m", "gallery_dl", "--get-urls", "--range", f"1-{r_max}", s_url]
                out = subprocess.check_output(comando, creationflags=CREATE_NO_WINDOW, text=True, stderr=subprocess.STDOUT, errors="ignore")
                for u in out.splitlines():
                    u = u.strip()
                    if u and (u.startswith('http') or u.startswith('ytdl:') or u.startswith('| ')): 
                        if u.startswith('| '): u = u[2:]
                        urls.append(u)
            except subprocess.CalledProcessError as e:
                if e.output and "NotFoundError" in e.output and "board could not be found" in e.output:
                    global_status["message"] = "Este tablero es privado. Solo podemos descargar contenido de tableros públicos."
                    return global_status["message"]
            except Exception:
                pass
            
            # DESCARGA TEMPRANA: tras completar la red #2, preparar URLs disponibles
            if (i + 1) == trigger_batch and len(urls) > 0:
                temp_urls = list(set(urls))
                foto_urls = []
                video_urls = []
                for u in temp_urls:
                    if u.startswith('ytdl:'):
                        if u.replace('ytdl:', '').startswith('http'):
                            video_urls.append(u.replace('ytdl:', ''))
                    elif u.lower().split('?')[0].endswith(('.mp4', '.webm', '.m3u8', '.mov')):
                        video_urls.append(u)
                    elif u.startswith('http'):
                        foto_urls.append(u)
                import re
                def deduplicate_videos(v_urls):
                    seen_ids = set()
                    unique = []
                    v_urls.sort(key=lambda x: 0 if '.mp4' in x.lower() else 1)
                    for u in v_urls:
                        match = re.search(r'([a-f0-9]{32})', u)
                        if match:
                            vid_id = match.group(1)
                            if vid_id in seen_ids: continue
                            seen_ids.add(vid_id)
                        unique.append(u)
                    return unique
                video_urls = deduplicate_videos(video_urls)
                if azar:
                    random.shuffle(foto_urls)
                    random.shuffle(video_urls)
                global_status["message"] = f"¡Lote temprano listo! {len(foto_urls)} fotos + {len(video_urls)} videos. Descargando mientras sigo buscando..."
                # Lanzar scraping restante en hilo paralelo
                def scrape_remaining(start_idx, s_items, container):
                    for j in range(start_idx, len(s_items)):
                        try:
                            cmd = [sys.executable, "-m", "gallery_dl", "--get-urls", "--range", f"1-{s_items[j]['range']}", s_items[j]['url']]
                            o = subprocess.check_output(cmd, creationflags=CREATE_NO_WINDOW, text=True, errors="ignore")
                            for line in o.splitlines():
                                if line.strip(): container['nuevas'].append(line.strip())
                        except subprocess.CalledProcessError as e:
                            if hasattr(e, 'output') and e.output:
                                for line in e.output.splitlines():
                                    if line.strip(): container['nuevas'].append(line.strip())
                        except:
                            pass
                
                bg_thread = threading.Thread(target=scrape_remaining, args=(i + 1, search_items, remaining_urls_container), daemon=True)
                bg_thread.start()
                break
        else:
            # Si no se activó el trigger (menos de 2 redes), preparar URLs normalmente
            urls = list(set(urls))
            foto_urls = []
            video_urls = []
            for u in urls:
                if u.startswith('ytdl:'):
                    if u.replace('ytdl:', '').startswith('http'):
                        video_urls.append(u.replace('ytdl:', ''))
                elif u.lower().split('?')[0].endswith(('.mp4', '.webm', '.m3u8', '.mov')):
                    video_urls.append(u)
                elif u.startswith('http'):
                    foto_urls.append(u)
            import re
            
            def deduplicate_videos(v_urls):
                seen_ids = set()
                unique = []
                # Sort to prefer .mp4 over .m3u8
                v_urls.sort(key=lambda x: 0 if '.mp4' in x.lower() else 1)
                for u in v_urls:
                    match = re.search(r'([a-f0-9]{32})', u)
                    if match:
                        vid_id = match.group(1)
                        if vid_id in seen_ids: continue
                        seen_ids.add(vid_id)
                    unique.append(u)
                return unique
            video_urls = deduplicate_videos(video_urls)
            if azar:
                random.shuffle(foto_urls)
                random.shuffle(video_urls)
        
        count_fotos = 0
        count_videos = 0
        descartados_fotos = 0
        descartados_videos = 0
        
        # Helper para absorber URLs del hilo en fondo
        seen_urls = set(foto_urls + video_urls)
        seen_hashes = set()
        import re
        for u in video_urls:
            match = re.search(r'([a-f0-9]{32})', u)
            if match: seen_hashes.add(match.group(1))

        def absorb_new_urls():
            if 'nuevas' in remaining_urls_container and remaining_urls_container['nuevas']:
                new_batch = list(set(remaining_urls_container['nuevas']))
                remaining_urls_container['nuevas'].clear()
                for u in new_batch:
                    is_video = False
                    clean_u = u
                    if u.startswith('ytdl:'):
                        clean_u = u.replace('ytdl:', '')
                        is_video = True
                    elif u.lower().split('?')[0].endswith(('.mp4', '.webm', '.m3u8', '.mov')):
                        is_video = True
                        
                    if clean_u not in seen_urls:
                        if is_video:
                            match = re.search(r'([a-f0-9]{32})', clean_u)
                            if match:
                                vid_id = match.group(1)
                                if vid_id in seen_hashes: continue
                                seen_hashes.add(vid_id)
                            seen_urls.add(clean_u)
                            video_urls.append(clean_u)
                        elif clean_u.startswith('http'):
                            seen_urls.add(clean_u)
                            foto_urls.append(clean_u)
                        
        # 4. Descargar y validar FOTOS una por una
        intentos = 0
        max_intentos = limit * 5 # máximo 5 intentos por cada foto solicitada (ej. si piden 5, máximo 25 intentos)
        if max_intentos < 50: max_intentos = 50

        idx_foto = 0

        if media_type in ('fotos', 'both'):
            while count_fotos < limit:
                if idx_foto < len(foto_urls):
                    u = foto_urls[idx_foto]
                    idx_foto += 1
                else:
                    absorb_new_urls()
                    if idx_foto < len(foto_urls):
                        continue
                    if 'bg_thread' in locals() and bg_thread is not None and bg_thread.is_alive():
                        global_status["message"] = f"Espere un momento. Buscando y procesando el contenido, tenga paciencia... (Fotos: {count_fotos})"
                        time.sleep(1)
                        continue
                    else:
                        absorb_new_urls()
                        if idx_foto >= len(foto_urls):
                            global_status["message"] = f"ERROR: No se encontraron más fotos que cumplan los requisitos. (Descartadas: {descartados_fotos})"
                            break
                        continue

                if limit == 9999:
                    global_status["message"] = f"Descargando foto... (Guardadas: {count_fotos + 1} | Omitidas: {descartados_fotos}). Esto puede tomar tiempo, estamos procesando con la mejor calidad, por favor tenga paciencia..."
                else:
                    global_status["message"] = f"Descargando foto {count_fotos + 1} de {limit} (Omitidas: {descartados_fotos}). Esto puede tomar tiempo, estamos procesando con la mejor calidad, por favor tenga paciencia..."
                
                if intentos >= max_intentos:
                    global_status["message"] = f"ERROR: No se encontraron más fotos que cumplan los requisitos. (Descartadas: {descartados_fotos})"
                    break
                intentos += 1
                
                clean_ext = u.split('?')[0].split('.')[-1].lower()
                if clean_ext not in ('jpg', 'jpeg', 'png', 'webp'):
                    clean_ext = 'jpg'
                temp_path = os.path.join(target_dir, f"temp_{random.randint(10000,99999)}.{clean_ext}")
                try:
                    r_img = requests.get(u, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}, timeout=12)
                    if r_img.status_code != 200:
                        descartados_fotos += 1
                        continue
                    with open(temp_path, 'wb') as f:
                        f.write(r_img.content)
                    from PIL import Image
                    with Image.open(temp_path) as img:
                        w, h = img.size
                        
                    fmt = img_format.lower()
                    if "1:1" in fmt and not (0.9 <= w/h <= 1.11):
                        os.remove(temp_path); descartados_fotos += 1; continue
                    elif "absoluto" in fmt and "vertical" in fmt and h < w * 1.5:
                        os.remove(temp_path); descartados_fotos += 1; continue
                    elif "casi" in fmt and "vertical" in fmt and not (w < h < w * 1.5):
                        os.remove(temp_path); descartados_fotos += 1; continue
                    elif fmt == "vertical" and h < w:
                        os.remove(temp_path); descartados_fotos += 1; continue
                    elif "horizontal" in fmt and w <= h:
                        os.remove(temp_path); descartados_fotos += 1; continue
                        
                    final_path = os.path.join(target_dir, f"[FOTO] {count_fotos + 1:03d}_pinterest_{int(time.time())}_{random.randint(10000,99999)}.jpg")
                    if os.path.exists(temp_path):
                        shutil.move(temp_path, final_path)
                        count_fotos += 1
                        print(f"[Pinterest] [OK] Guardada foto #{count_fotos}: {os.path.basename(final_path)}")
                except Exception as e:
                    print(f"[Pinterest] [WARN] Omitida imagen por: {e}")
                    if os.path.exists(temp_path):
                        try: os.remove(temp_path)
                        except: pass
                        
        # 5. Descargar y validar VIDEOS uno por uno
        idx_video = 0
        if media_type in ('videos', 'both'):
            import yt_dlp
            meta_real = limit if limit != 9999 else 99999
            
            while count_videos < meta_real:
                if idx_video < len(video_urls):
                    u = video_urls[idx_video]
                    idx_video += 1
                else:
                    absorb_new_urls()
                    if idx_video < len(video_urls):
                        continue
                    if 'bg_thread' in locals() and bg_thread is not None and bg_thread.is_alive():
                        global_status["message"] = f"Espere un momento. Buscando y procesando el contenido, tenga paciencia... (Videos: {count_videos})"
                        time.sleep(1)
                        continue
                    else:
                        absorb_new_urls()
                        if idx_video < len(video_urls):
                            continue
                            
                        if pin_tab in ('relacionados', 'fallback'):
                            fallback_suffixes = [" aesthetic video", " video", " edit", " tiktok", " live performance", " stage edit", " fan edit", " tour aesthetic"]
                            fallback_attempts = getattr(threading.current_thread(), 'fallback_attempts', 0)
                            
                            if fallback_attempts < len(fallback_suffixes):
                                suffix = fallback_suffixes[fallback_attempts]
                                threading.current_thread().fallback_attempts = fallback_attempts + 1
                                
                                global_status["message"] = f"Agotados los pines. Búsqueda profunda N°{fallback_attempts+1} con término '{suffix.strip()}' para tu cuota de {meta_real} videos... (Llevamos: {count_videos}). No cierre la ventana."
                                fallback_query = safe_name.replace('_', ' ') + suffix
                                
                                try:
                                    f_path = "search/videos" if media_type == "Solo Video" else "search/pins"
                                    s_url = f"https://www.pinterest.com/{f_path}/?q={fallback_query.replace(' ', '+')}"
                                    cmd = [sys.executable, "-m", "gallery_dl", "--get-urls", "--range", "1-3000", s_url]
                                    o = subprocess.check_output(cmd, creationflags=CREATE_NO_WINDOW, text=True, errors="ignore")
                                    for line in o.splitlines():
                                        if line.strip(): remaining_urls_container['nuevas'].append(line.strip())
                                except subprocess.CalledProcessError as e:
                                    if hasattr(e, 'output') and e.output:
                                        for line in e.output.splitlines():
                                            if line.strip(): remaining_urls_container['nuevas'].append(line.strip())
                                except Exception as e:
                                    pass
                                    
                                pin_tab = 'fallback'
                                continue
                            
                        break

                if limit == 9999:
                    global_status["message"] = f"Descargando video... (Guardados: {count_videos + 1} | Omitidos: {descartados_videos}). Esto puede tomar tiempo, estamos procesando con la mejor calidad, por favor tenga paciencia..."
                else:
                    global_status["message"] = f"Descargando video {count_videos + 1} de {meta_real} (Omitidos: {descartados_videos}). Esto puede tomar tiempo, estamos procesando con la mejor calidad, por favor tenga paciencia..."
                temp_id = str(random.randint(100000,999999))
                
                # 1. EVALUACIÓN SÚPER RÁPIDA (Sin descargar el archivo)
                ydl_opts_info = {
                    'quiet': True,
                    'ignoreerrors': True,
                    'extract_flat': False
                }
                
                w, h = 0, 0
                try:
                    u_clean = u.replace('ytdl:', '') if u.startswith('ytdl:') else u
                    with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                        info = ydl.extract_info(u_clean, download=False)
                    
                    if not info:
                        descartados_videos += 1; continue
                        
                    # Filtro de palabras clave prohibidas (ej. tiktok)
                    title = str(info.get('title', '')).lower()
                    desc = str(info.get('description', '')).lower()
                    if any(kw in title or kw in desc for kw in FORBIDDEN_KEYWORDS):
                        descartados_videos += 1; continue
                        
                    w = info.get('width') or 0
                    h = info.get('height') or 0
                    
                    if w and h:
                        fmt = img_format.lower()
                        if "1:1" in fmt and not (0.9 <= w/h <= 1.11):
                            descartados_videos += 1; continue
                        elif "absoluto" in fmt and "vertical" in fmt and h < w * 1.5:
                            descartados_videos += 1; continue
                        elif "casi" in fmt and "vertical" in fmt and not (w < h < w * 1.5):
                            descartados_videos += 1; continue
                        elif fmt == "vertical" and h < w:
                            descartados_videos += 1; continue
                        elif "horizontal" in fmt and w <= h:
                            descartados_videos += 1; continue
                            
                    # 2. DESCARGA (Pasó el filtro)
                    ydl_opts = {
                        'outtmpl': os.path.join(target_dir, f'temp_{temp_id}.%(ext)s'),
                        'quiet': True,
                        'ignoreerrors': True
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_dl:
                        ydl_dl.download([u_clean])
                        
                    descargado = None
                    for f in os.listdir(target_dir):
                        if f.startswith(f"temp_{temp_id}"):
                            descargado = os.path.join(target_dir, f)
                            break
                            
                    if not descargado: continue
                    
                    # 3. VERIFICACIÓN (Solo si yt-dlp falló leyendo w/h arriba)
                    if not (w and h):
                        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', descargado]
                        out_probe = subprocess.check_output(cmd, creationflags=CREATE_NO_WINDOW).decode().strip()
                        w, h = map(int, out_probe.split('x'))
                        
                        fmt = img_format.lower()
                        if "1:1" in fmt and not (0.9 <= w/h <= 1.11):
                            os.remove(descargado); descartados_videos += 1; continue
                        elif "absoluto" in fmt and "vertical" in fmt and h < w * 1.5:
                            os.remove(descargado); descartados_videos += 1; continue
                        elif "casi" in fmt and "vertical" in fmt and not (w < h < w * 1.5):
                            os.remove(descargado); descartados_videos += 1; continue
                        elif fmt == "vertical" and h < w:
                            os.remove(descargado); descartados_videos += 1; continue
                        elif "horizontal" in fmt and w <= h:
                            os.remove(descargado); descartados_videos += 1; continue
                    elif fmt not in ("1:1", "horizontal", "cualquiera") and w >= h: # Default fallback vertical
                        os.remove(descargado); descartados_videos += 1; continue
                        
                    final_path = os.path.join(target_dir, f"[VIDEO] {count_videos + 1:03d}_pinterest_{temp_id}.mp4")
                    os.rename(descargado, final_path)
                    count_videos += 1
                except:
                    descartados_videos += 1
                    if descargado and os.path.exists(descargado):
                        try: os.remove(descargado)
                        except: pass




        msg_fotos = f"{count_fotos} fotos" if media_type in ('fotos', 'both') else ""
        msg_videos = f"{count_videos} videos" if media_type in ('videos', 'both') else ""
        final_msg = " y ".join(filter(None, [msg_fotos, msg_videos]))
        
        # Extraer solo las dos últimas carpetas para que sea genérico (ej. Descargas_Pinterest/parejas)
        ruta_relativa = os.path.join(os.path.basename(os.path.dirname(target_dir)), os.path.basename(target_dir))
        
        if meta_real != 99999 and count_videos < meta_real:
            resultado = f"ATENCIÓN: Escasez de contenido. Pinterest no tiene {meta_real} videos reales disponibles para esta búsqueda (había duplicados, tiktoks o simplemente hay muy pocos). Solo logramos rescatar {count_videos} videos únicos. (Guardados en {ruta_relativa})"
        else:
            resultado = f"ÉXITO TOTAL: Descarga completada. {final_msg} guardados únicos en {ruta_relativa}"
            
        global_status["message"] = resultado
        return resultado
    except Exception as e:
        return f"ERROR (Pinterest {query}): {e}"

def cleanup_old_files():
    import getpass
    usuario = getpass.getuser()
    rutas_capturas = [
        os.path.join('C:\\Users', usuario, 'Videos', 'Captures'),
        os.path.join('C:\\Users', usuario, 'Pictures', 'Screenshots'),
        os.path.join('C:\\Users', usuario, 'Pictures', 'Capturas de pantalla'),
        os.path.join('C:\\Users', usuario, 'Videos', 'Capturas_Temporales'),
        os.path.join('C:\\Users', usuario, 'Videos', 'Grabador de pantalla')
    ]
    
    while True:
        now = time.time()
        
        # 1. Limpieza de Descargas (10 días / 1 semana y 3 días)
        directorios_a_limpiar = [MANUAL_AUDIO_DIR, MANUAL_PIN_DIR, BOT_DIR, EXCEL_DIR]
        for d in directorios_a_limpiar:
            if os.path.exists(d):
                for root, dirs, files in os.walk(d, topdown=False):
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        if os.stat(filepath).st_mtime < now - 10 * 86400:
                            try:
                                os.remove(filepath)
                                print(f"Limpieza: {filepath} eliminado (más de 10 días).")
                            except Exception as e:
                                print(f"Error borrando {filepath}: {e}")
                    
                    # Si la subcarpeta quedó vacía después de borrar archivos (y no es la carpeta principal), la eliminamos
                    if root != d and not os.listdir(root):
                        try:
                            os.rmdir(root)
                        except:
                            pass
                                
        # 2. Limpieza de Capturas (7 días)
        for d in rutas_capturas:
            if os.path.exists(d):
                for root, dirs, files in os.walk(d):
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        if filename.lower() == 'desktop.ini': continue
                        if os.stat(filepath).st_mtime < now - 7 * 86400:
                            try:
                                os.remove(filepath)
                                print(f"Limpieza Captura: {filepath} eliminada (más de 7 días).")
                            except Exception as e:
                                pass

        time.sleep(86400)  

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(global_status)

@app.route('/api/download_audio', methods=['POST'])
def download_audio():
    data = request.json
    query = data.get('query')
    speed = data.get('speed', "1.0")
    cantidad = int(data.get('cantidad', 1))
    threading.Thread(target=process_audio_download, args=(query, None, cantidad, None, speed)).start()
    return jsonify({"status": "success", "message": f"Audio en cola: {query} ({speed}x, {cantidad} canción(es))"})

@app.route('/api/download_excel', methods=['POST'])
def download_excel():
    file = request.files.get('file')
    speed = request.form.get('speed', "1.0")
    if not file:
        return jsonify({"status": "error", "message": "No se recibió ningún archivo."})

    links = []
    filename = file.filename.lower()

    if filename.endswith('.csv'):
        import csv, io
        content = file.read().decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        for row in reader:
            for cell in row:
                cell = cell.strip()
                if cell.startswith('http'):
                    links.append(cell)
    elif filename.endswith('.xlsx') or filename.endswith('.xls'):
        if openpyxl is None:
            return jsonify({"status": "error", "message": "Librería openpyxl no instalada. Ejecuta: pip install openpyxl"})
        import io
        wb = openpyxl.load_workbook(io.BytesIO(file.read()))
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell and str(cell).startswith('http'):
                        links.append(str(cell).strip())
    else:
        return jsonify({"status": "error", "message": "Formato no soportado. Usa .xlsx, .xls o .csv"})

    if not links:
        return jsonify({"status": "error", "message": "No se encontraron links en el archivo."})

    threading.Thread(target=process_bulk_audio, args=(links, speed)).start()
    return jsonify({"status": "success", "message": f"Se encontraron {len(links)} links. Descarga en proceso a {speed}x..."})

@app.route('/api/download_pinterest', methods=['POST'])
def download_pinterest():
    data = request.json
    query = data.get('query')
    format_type = str(data.get('cantidad', 20))
    media_type = data.get('media_type')
    bot_event = data.get('bot_event')
    img_format = data.get('format', 'Cualquiera')
    pin_tab = data.get('pin_tab', 'tematica')
    azar = data.get('azar', False)
    threading.Thread(target=process_pinterest_download, args=(query, format_type, media_type, bot_event, img_format, pin_tab, azar)).start()
    return jsonify({"status": "success", "message": "Iniciando proceso en segundo plano..."})

@app.route('/api/process_workorder', methods=['POST'])
def process_workorder():
    data = request.json
    workorder = data.get('workorder', '')
    speed = data.get('speed', '1.0')
    
    lines = workorder.strip().split('\n')
    evento = "Descarga_Masiva"
    
    from concurrent.futures import ThreadPoolExecutor
    
    # Límite estricto de 1 trabajador para que la UI no se sobreescriba y puedas ver la barra de progreso
    executor = ThreadPoolExecutor(max_workers=1)
    futures = []
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('[') or line.startswith('```'):
            continue
            
        if line.startswith('EVENTO='):
            evento = line.split('=')[1].strip()
            continue
            
        def parse_order_line(l, default_fmt="Vertical Absoluto"):
            ps = l.split(':', 3)
            if len(ps) >= 4:
                return ps[1], ps[3], ps[2]
            elif len(ps) == 3:
                return ps[1], ps[2], default_fmt
            return None, None, None

        if line.startswith('FOTOS:'):
            c, q, f = parse_order_line(line)
            if c: futures.append(executor.submit(process_pinterest_download, q, c, 'fotos', evento, f))

        elif line.startswith('VIDEOS:'):
            c, q, f = parse_order_line(line)
            if c: futures.append(executor.submit(process_pinterest_download, q, c, 'videos', evento, f))
                
        elif line.startswith('AMBOS:'):
            c, q, f = parse_order_line(line)
            if c: futures.append(executor.submit(process_pinterest_download, q, c, 'both', evento, f))

        elif line.startswith('PINTEREST:'):
            c, q, f = parse_order_line(line)
            if c: 
                media_type = 'videos' if 'video' in q.lower() else 'fotos'
                futures.append(executor.submit(process_pinterest_download, q, c, media_type, evento, f))

        elif line.startswith('AUDIO:'):
            parts = line.split(':', 2)
            if len(parts) >= 3:
                cantidad = int(parts[1])
                query = parts[2].strip()
                futures.append(executor.submit(process_audio_download, query, bot_event=evento, limit=cantidad, speed=speed))

    def wait_and_summarize(futures_list, exec_obj):
        resultados = []
        for f in futures_list:
            try:
                resultados.append(f.result())
            except Exception as ex:
                resultados.append(f"OMITIDO: Falla en procesamiento -> {ex}")
        exec_obj.shutdown()
        exitos = sum(1 for r in resultados if "ÉXITO" in r)
        omitidos = sum(1 for r in resultados if "OMITIDO" in r or "ERROR" in r)
        resumen_head = f"ÉXITO TOTAL: {exitos} procesados correctamente. {omitidos} omitidos por bloqueo de copyright/privacidad."
        reporte = resumen_head + "\n---\n" + "\n".join(resultados)
        global_status["message"] = reporte

    if futures:
        threading.Thread(target=wait_and_summarize, args=(futures, executor)).start()
        return jsonify({"status": "success", "message": "Orden industrial recibida.\nDelegada a los trabajadores en el fondo.\n\nMira la caja de arriba para el progreso en tiempo real."})
    else:
        return jsonify({"status": "success", "message": "No se encontraron comandos válidos."})

if __name__ == '__main__':
    print("Iniciando mecanismo de autolimpieza...")
    threading.Thread(target=cleanup_old_files, daemon=True).start()
    
    print("Iniciando Descargador Universal...")
    app.run(debug=True, port=5000, use_reloader=False)
