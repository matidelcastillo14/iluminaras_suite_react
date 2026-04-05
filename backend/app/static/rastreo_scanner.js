(function(){
  function $(id){ return document.getElementById(id); }

  async function startCameraScan(opts){
    const video = $(opts.videoId);
    const status = $(opts.statusId);
    const onCode = opts.onCode;

    const continuous = !!opts.continuous;
    const debounceMs = Number(opts.debounceMs || 1200);
    const stopOnCode = (typeof opts.stopOnCode === 'boolean') ? opts.stopOnCode : !continuous;

    if (!video) return null;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
      status && (status.textContent = 'El navegador no soporta cámara.');
      return null;
    }

    status && (status.textContent = 'Solicitando permiso de cámara...');

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    } catch(e){
      status && (status.textContent = 'No se pudo acceder a la cámara. Verificá permisos y HTTPS.');
      throw e;
    }

    video.srcObject = stream;
    video.setAttribute('playsinline', 'true');
    video.muted = true;
    await video.play();
    status && (status.textContent = 'Cámara activa. Apuntá al QR...');

    let stopped = false;
    const stop = () => {
      if (stopped) return;
      stopped = true;
      try { video.pause(); } catch(_){ }
      try { video.srcObject = null; } catch(_){ }
      try { stream.getTracks().forEach(t => t.stop()); } catch(_){ }
      status && (status.textContent = 'Cámara detenida.');
    };

    let lastRaw = null;
    let lastAt = 0;
    let handling = false;

    const shouldSkip = (raw) => {
      const now = Date.now();
      if (continuous && raw && raw === lastRaw && (now - lastAt) < debounceMs) return true;
      lastRaw = raw;
      lastAt = now;
      return false;
    };

    const handleFound = async (raw) => {
      if (stopped) return;
      if (!raw) return;
      if (shouldSkip(raw)) return;
      if (handling) return;
      handling = true;
      try {
        status && (status.textContent = 'QR detectado.');
        let res = null;
        try { res = onCode ? await onCode(raw) : null; } catch(_){ }
        const wantsStop = (res === true) || (res && res.stop === true);
        if (stopOnCode || wantsStop){
          stop();
        }
      } finally {
        const delay = continuous ? max(350, min(900, debounceMs)) : 0;
        setTimeout(() => { handling = false; }, delay);
      }
    };

    function min(a,b){ return a<b?a:b; }
    function max(a,b){ return a>b?a:b; }

    // Ruta A: BarcodeDetector (más rápido, sin servidor)
    const hasBarcodeDetector = typeof window.BarcodeDetector !== 'undefined';
    if (hasBarcodeDetector){
      try {
        const detector = new BarcodeDetector({ formats: ['qr_code'] });
        const tick = async () => {
          if (stopped) return;
          try {
            const barcodes = await detector.detect(video);
            if (barcodes && barcodes.length){
              const raw = (barcodes[0].rawValue || '').trim();
              if (raw){
                await handleFound(raw);
              }
            }
          } catch(_){ /* ignore */ }
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
        return stop;
      } catch(_){
        // cae a fallback
      }
    }

    // Ruta B (fallback iOS): capturar frames y decodificar en el servidor (/rastreo/api/decode_qr)
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    let inFlight = false;

    const loop = async () => {
      if (stopped) return;
      try {
        if (video.readyState >= 2 && ctx){
          const w = video.videoWidth || 0;
          const h = video.videoHeight || 0;
          if (w && h){
            const targetW = Math.min(800, w);
            const targetH = Math.round(h * (targetW / w));
            canvas.width = targetW;
            canvas.height = targetH;
            ctx.drawImage(video, 0, 0, targetW, targetH);

            if (!inFlight){
              inFlight = true;
              try {
                const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.7));
                if (blob){
                  const fd = new FormData();
                  fd.append('image', blob, 'frame.jpg');
                  const res = await fetch('/rastreo/api/decode_qr', { method: 'POST', body: fd });
                  let j = null;
                  try { j = await res.json(); } catch(_){ }
                  if (j && j.ok && j.code){
                    await handleFound(String(j.code));
                  } else if (res.status === 501 && j && j.error === 'qr_decode_deps_missing'){
                    status && (status.textContent = 'Escaneo en vivo requiere dependencias en el servidor (opencv/numpy). Instalá requirements.txt actualizado o usá "Sacar foto" / ingreso manual.');
                    return;
                  }
                }
              } finally {
                inFlight = false;
              }
            }
          }
        }
      } catch(_){
        inFlight = false;
      }
      setTimeout(loop, continuous ? 450 : 700);
    };

    status && (status.textContent = 'Cámara activa. Buscando QR...');
    setTimeout(loop, 300);
    return stop;
  }

  async function decodeByPhoto(opts){
    const fileInput = $(opts.fileId);
    const status = $(opts.statusId);
    const onCode = opts.onCode;

    if (!fileInput) return;
    const f = fileInput.files && fileInput.files[0];
    if (!f) return;

    status && (status.textContent = 'Decodificando...');
    const fd = new FormData();
    fd.append('image', f);
    try {
      const res = await fetch('/rastreo/api/decode_qr', { method: 'POST', body: fd });
      let j = null;
      try { j = await res.json(); } catch(e) {}

      if (j && j.ok && j.code){
        onCode(String(j.code));
        return;
      }
      if (res.status === 501 && j && j.error === 'qr_decode_deps_missing'){
        status && (status.textContent = 'Decodificación por foto no disponible (faltan dependencias en el servidor). Instalá requirements_qr_photo.txt o usá escaneo en vivo / ingreso manual.');
        return;
      }
      status && (status.textContent = 'No se detectó QR. Intentá de nuevo.');
    } catch(e){
      status && (status.textContent = 'Error decodificando.');
    }
  }

  window.RastreoScanner = { startCameraScan, decodeByPhoto };
})();
