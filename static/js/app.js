let selectedFile = null;

function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  event.target.classList.add('active');
  const target = document.getElementById(`tab-${tabId}`);
  if (target) target.classList.add('active');

  if (tabId === 'files') {
    loadFiles();
  }
}

// 🎵 AUDIO DOWNLOAD
async function downloadAudio() {
  const query = document.getElementById('audio-input').value.trim();
  const status = document.getElementById('audio-status');
  if (!query) return alert('Por favor ingresa un nombre de canción o enlace.');

  status.className = 'status-box loading';
  status.innerHTML = '⏳ Descargando y convirtiendo audio a MP3... Por favor espera.';

  try {
    const res = await fetch('/api/download_audio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });
    const data = await res.json();

    if (data.status === 'success') {
      status.className = 'status-box success';
      status.innerHTML = `✅ <strong>${data.title}</strong> descargado exitosamente.<br><a href="${data.download_url}" class="btn btn-primary" style="margin-top:10px; display:inline-block;">📥 Guardar MP3 en mi Dispositivo</a>`;
      updateFileCount();
    } else {
      status.className = 'status-box error';
      status.innerText = `❌ Error: ${data.message}`;
    }
  } catch (err) {
    status.className = 'status-box error';
    status.innerText = `❌ Error de red: ${err.message}`;
  }
}

// 🎬 VIDEO DOWNLOAD
async function downloadVideo() {
  const url = document.getElementById('video-input').value.trim();
  const status = document.getElementById('video-status');
  if (!url) return alert('Por favor ingresa un enlace de video.');

  status.className = 'status-box loading';
  status.innerHTML = '⏳ Extrayendo video virgen en máxima resolución...';

  try {
    const res = await fetch('/api/download_video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json();

    if (data.status === 'success') {
      status.className = 'status-box success';
      status.innerHTML = `✅ <strong>${data.title}</strong> listo.<br><a href="${data.download_url}" class="btn btn-primary" style="margin-top:10px; display:inline-block;">📥 Guardar Video en mi Dispositivo</a>`;
      updateFileCount();
    } else {
      status.className = 'status-box error';
      status.innerText = `❌ Error: ${data.message}`;
    }
  } catch (err) {
    status.className = 'status-box error';
    status.innerText = `❌ Error de conexión: ${err.message}`;
  }
}

// 📊 BULK EXCEL UPLOAD
function handleFileSelect(e) {
  selectedFile = e.target.files[0];
  if (selectedFile) {
    document.getElementById('file-label').innerHTML = `📄 Archivo seleccionado: <strong>${selectedFile.name}</strong>`;
  }
}

async function uploadExcel() {
  if (!selectedFile) return alert('Por favor selecciona un archivo .xlsx, .xls o .csv primero.');

  const status = document.getElementById('bulk-status');
  status.className = 'status-box loading';
  status.innerHTML = '⏳ Leyendo archivo y encolando descargas en la nube...';

  const formData = new FormData();
  formData.append('file', selectedFile);

  try {
    const res = await fetch('/api/download_excel', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();

    if (data.status === 'success') {
      status.className = 'status-box success';
      status.innerHTML = `✅ ${data.message}<br>💡 Puedes ir a la pestaña <strong>Mis Archivos</strong> para ver y descargar tus audios conforme terminen.`;
      updateFileCount();
    } else {
      status.className = 'status-box error';
      status.innerText = `❌ Error: ${data.message}`;
    }
  } catch (err) {
    status.className = 'status-box error';
    status.innerText = `❌ Error al subir: ${err.message}`;
  }
}

// 📌 PINTEREST SEARCH
async function searchPinterest() {
  const query = document.getElementById('pinterest-input').value.trim();
  const status = document.getElementById('pinterest-status');
  const gallery = document.getElementById('pinterest-gallery');
  if (!query) return alert('Ingresa qué buscar en Pinterest.');

  status.className = 'status-box loading';
  status.innerHTML = `🔍 Buscando fotos HD en Pinterest de: <strong>${query}</strong>...`;
  gallery.innerHTML = '';

  try {
    const res = await fetch('/api/search_pinterest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });
    const data = await res.json();

    if (data.status === 'success' && data.images.length > 0) {
      status.className = 'status-box success';
      status.innerText = `✅ Encontradas ${data.images.length} imágenes en resolución original:`;

      data.images.forEach(img => {
        const card = document.createElement('div');
        card.className = 'gallery-card';
        card.innerHTML = `
          <img src="${img.url}" loading="lazy" alt="Pin" />
          <div class="gallery-actions">
            <button class="btn btn-secondary btn-block" onclick="savePinterestImage('${img.url}')">📥 Guardar</button>
          </div>
        `;
        gallery.appendChild(card);
      });
    } else {
      status.className = 'status-box error';
      status.innerText = '❌ No se encontraron fotos o Pinterest limitó la petición temporalmente.';
    }
  } catch (err) {
    status.className = 'status-box error';
    status.innerText = `❌ Error: ${err.message}`;
  }
}

async function savePinterestImage(url) {
  try {
    const res = await fetch('/api/save_pinterest_image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json();
    if (data.status === 'success') {
      window.location.href = data.download_url;
      updateFileCount();
    } else {
      alert('Error guardando imagen: ' + data.message);
    }
  } catch (err) {
    alert('Error al descargar: ' + err.message);
  }
}

// 📂 FILE MANAGER
async function loadFiles() {
  const tbody = document.getElementById('files-tbody');
  tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Cargando archivos...</td></tr>';

  try {
    const res = await fetch('/api/list_files');
    const data = await res.json();

    if (data.status === 'success' && data.files.length > 0) {
      tbody.innerHTML = '';
      data.files.forEach(f => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${f.name}</strong></td>
          <td><span class="type-tag">${f.category.toUpperCase()}</span></td>
          <td>${f.size_mb} MB</td>
          <td>${f.date}</td>
          <td><a href="${f.download_url}" class="btn btn-secondary" style="padding: 6px 12px; font-size:12px;">📥 Descargar</a></td>
        `;
        tbody.appendChild(tr);
      });
      document.getElementById('file-count').innerText = data.files.length;
    } else {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color: var(--text-muted);">No hay archivos descargados todavía.</td></tr>';
      document.getElementById('file-count').innerText = '0';
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color: var(--error);">Error cargando archivos: ${err.message}</td></tr>`;
  }
}

async function updateFileCount() {
  try {
    const res = await fetch('/api/list_files');
    const data = await res.json();
    if (data.status === 'success') {
      document.getElementById('file-count').innerText = data.files.length;
    }
  } catch (e) {}
}

document.addEventListener('DOMContentLoaded', () => {
  updateFileCount();
});
