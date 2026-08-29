# REGISTRO DE ERRORES CORREGIDOS - DESCARGADOR UNIVERSAL

> **ATENCIÓN A AGENTES DE IA:** Este archivo contiene el historial estricto de bugs que ya han sido solucionados en este proyecto. NUNCA reviertas estos arreglos ni modifiques este archivo a menos que sea para agregar un nuevo error solucionado.

## 1. Bloqueo de YouTube en Búsquedas Masivas (Rate Limit / HTTP 429)
- **Síntoma:** Al procesar una "Orden Masiva" (Workorder) con decenas de audios, el programa solo lograba descargar las primeras 4 o 5 canciones. Luego reportaba un falso "ÉXITO" pero no guardaba ningún archivo nuevo.
- **Causa:** Enviar peticiones consecutivas e instantáneas a YouTube usando `ytsearch:` provocaba que YouTube bloqueara temporalmente la IP, devolviendo listas vacías para el resto de las canciones.
- **Solución implementada:** Se agregó una pausa obligatoria usando `time.sleep(random.uniform(1.5, 3.5))` justo después de descargar cada audio para simular un humano y evitar el baneo.

## 2. Excepción Falsa de yt-dlp (MaxDownloadsReached)
- **Síntoma:** En la función `process_audio_download`, a pesar de descargar el audio exitosamente, se enviaba un mensaje de "ERROR (Audio ...): Maximum number of downloads reached" al reporte final.
- **Causa:** Al configurar `'max_downloads': 1` en `yt-dlp` para búsquedas, la librería internamente lanza la excepción `yt_dlp.utils.MaxDownloadsReached` al concluir la primera descarga para abortar el playlist. Al capturarse con un `except Exception general`, el código lo trataba como un fallo grave.
- **Solución implementada:** Se envolvió el `ydl.download()` en un bloque `try-except yt_dlp.utils.MaxDownloadsReached: pass` para ignorar esta excepción específica y continuar reportándolo como ÉXITO.

## 3. Resolución de Enlaces Acortados de Pinterest (`pin.it`)
- **Síntoma:** La herramienta fallaba al intentar descargar imágenes o videos que provenían de enlaces acortados móviles de Pinterest (ej. `https://pin.it/...`).
- **Causa:** `gallery-dl` no procesa correctamente las redirecciones móviles y los enlaces `pin.it`.
- **Solución implementada:** En `process_pinterest_download`, se agregó una lógica previa que usa `requests.head(url, allow_redirects=True)` para extraer la URL final real (resolviendo el redirect) antes de pasársela a `gallery-dl`.

## 4. Dominios Regionales de Pinterest
- **Síntoma:** Enlaces como `es.pinterest.com` o subdominios regionales daban errores de compatibilidad.
- **Solución implementada:** Se implementó limpieza de cadenas mediante un `url.replace('es.pinterest.com', 'www.pinterest.com')` para estandarizar las URLs de Pinterest a su versión global.

## 5. Basura y Miniaturas Residuales de yt-dlp
- **Síntoma:** Al descargar videos, `yt-dlp` dejaba archivos `.webp` o `.jpg` de las portadas en las carpetas.
- **Solución implementada:** Se agregó un bucle de limpieza post-descarga que escanea la carpeta destino y borra (usando `os.remove`) cualquier archivo de imagen residual generado durante la sesión.
