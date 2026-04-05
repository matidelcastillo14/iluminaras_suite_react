(function(){
  const video = document.getElementById('fxVideo');
  const canvas = document.getElementById('fxCanvas');
  const ctx = canvas.getContext('2d');
  const btnStartCam = document.getElementById('btnStartCam');
  const btnManual = document.getElementById('btnManual');
  const dlgManual = document.getElementById('dlgManual');
  const manualCode = document.getElementById('manualCode');
  const btnManualOk = document.getElementById('btnManualOk');
  const manualErr = document.getElementById('manualErr');
  const cartCountEl = document.getElementById('cartCount');
  const cartEl = document.getElementById('fxCart');
  const btnStartRoute = document.getElementById('btnStartRoute');

  const communityId = window.FLEX_COMMUNITY_ID || null;
  let stream = null;
  let detector = null;
  let running = false;
  let lastDecodeTs = 0;
  let busy = false;

  // Feedback (sonido + vibración)
  let _audioCtx = null;
  function _beep(freq, durationMs){
    try{
      if(!_audioCtx){
        const AC = window.AudioContext || window.webkitAudioContext;
        if(!AC) return;
        _audioCtx = new AC();
      }
      const o = _audioCtx.createOscillator();
      const g = _audioCtx.createGain();
      o.type = 'sine';
      o.frequency.value = freq;
      g.gain.value = 0.12;
      o.connect(g);
      g.connect(_audioCtx.destination);
      o.start();
      setTimeout(()=>{ try{ o.stop(); }catch(_){} }, durationMs);
    }catch(_){ /* ignore */ }
  }
  function _vibrate(pattern){
    try{
      if(navigator && typeof navigator.vibrate === 'function'){
        navigator.vibrate(pattern);
      }
    }catch(_){ /* ignore */ }
  }
  function feedback(kind){
    if(kind === 'success'){
      _beep(880, 70);
      _vibrate(60);
    }else if(kind === 'duplicate'){
      _beep(330, 60);
      setTimeout(()=>_beep(330, 60), 90);
      _vibrate([30,40,30]);
    }else{ // error
      _beep(180, 160);
      _vibrate([60,50,60]);
    }
  }

  // Toast simple
  let toastEl = null;
  function toast(msg){
    if(!toastEl){
      toastEl = document.createElement('div');
      toastEl.className = 'fx-toast';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    setTimeout(()=>toastEl && toastEl.classList.remove('show'), 1800);
  }

  function showManualErr(msg){
    manualErr.style.display = 'block';
    manualErr.textContent = msg;
  }
  function hideManualErr(){
    manualErr.style.display = 'none';
    manualErr.textContent = '';
  }

  async function refreshCart(){
    try{
      const data = await window.FlexApi.cartList(communityId);
      renderCart(data.items || []);
    }catch(e){
      renderCart([]);
    }
  }

  function renderCart(items){
    cartCountEl.textContent = String(items.length);
    cartEl.innerHTML = '';
    items.forEach(it => {
      const row = document.createElement('div');
      row.className = 'fx-cart-item';
      row.innerHTML = `
        <div>
          <div class="fx-cart-id">${(it.id_web || it.order_name || it.tracking_code)}</div>
          <div class="fx-muted">${it.status || ''}</div>
        </div>
        <button class="fx-cart-x" data-shipment-id="${it.shipment_id}">Quitar</button>
      `;
      row.querySelector('button').addEventListener('click', async (ev) => {
        ev.preventDefault();
        const sid = ev.target.getAttribute('data-shipment-id');
        try{
          await window.FlexApi.cartRemove(parseInt(sid,10));
          await refreshCart();
        }catch(err){
          // ignore
        }
      });
      cartEl.appendChild(row);
    });
    btnStartRoute.disabled = items.length === 0;
  }

  async function startRoute(){
    btnStartRoute.disabled = true;
    try{
      const data = await window.FlexApi.routeStart(communityId);
      window.location.href = `/flex/routes/${data.route_id}/stops`;
    }catch(e){
      alert('No se pudo iniciar: ' + e.message);
      await refreshCart();
    }
  }

  function normalizeCode(val){
    if(!val) return '';
    const s = String(val).trim();
    // si viene URL /rastreo/go/<code>
    const idx = s.indexOf('/rastreo/go/');
    if(idx >= 0){
      return s.slice(idx).split('/rastreo/go/')[1].split('?')[0].replace(/\/+$/,'');
    }
    return s;
  }

  async function handleCodeFound(raw){
    const code = normalizeCode(raw);
    if(!code) return;
    if(busy) return;
    busy = true;
    try{
      const res = await window.FlexApi.cartScan(code, 'camera', communityId);
      const d = (res && res.data) ? res.data : {};
      if(d && d.added_to_route){
        toast('Agregado a la ruta');
      }else{
        toast('Agregado');
      }
      feedback('success');
      await refreshCart();
    }catch(e){
      // mensajes comunes
      if(String(e.message||'').startsWith('already_assigned:')){
        feedback('duplicate');
        alert('Ya está asignado a: ' + String(e.message).split('already_assigned:')[1]);
      }else if(e.message === 'already_in_cart' || e.message === 'already_in_route'){
        feedback('duplicate');
        toast('Ya estaba agregado');
      }else if(e.message === 'not_ready_for_dispatch'){
        feedback('error');
        alert('El pedido no está listo para despacho.');
      }else if(e.message === 'not_found'){
        feedback('error');
      }else{
        feedback('error');
        alert('Error: ' + e.message);
      }
    }finally{
      setTimeout(()=>{ busy=false; }, 600);
    }
  }

  async function detectLoop(){
    if(!running) return;
    try{
      if(video.readyState >= 2){
        const w = video.videoWidth || 640;
        const h = video.videoHeight || 480;
        if(w && h){
          canvas.width = w;
          canvas.height = h;
          ctx.drawImage(video, 0, 0, w, h);
        }

        // Prefer browser BarcodeDetector when available (Android Chrome; some iOS versions).
        if(detector){
          const codes = await detector.detect(video);
          if(codes && codes.length){
            await handleCodeFound(codes[0].rawValue);
          }
        }else{
          // Fallback: send a frame to server QR decoder (works on iPhone too)
          const now = Date.now();
          if(now - lastDecodeTs > 700){
            lastDecodeTs = now;
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.7));
            if(blob){
              const fd = new FormData();
              fd.append('image', blob, 'frame.jpg');
              const res = await fetch('/rastreo/api/decode_qr', { method:'POST', body: fd, credentials:'same-origin' });
              if(res.ok){
                const data = await res.json().catch(()=>null);
                if(data && data.ok && data.code){
                  await handleCodeFound(data.code);
                }
              }
            }
          }
        }
      }
    }catch(e){
      // ignore loop errors
    }
    requestAnimationFrame(detectLoop);
  }

  async function startCamera(silent=false){
    if(stream) return;
    try{
      const constraints = {
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      };
      stream = await navigator.mediaDevices.getUserMedia(constraints);
      video.srcObject = stream;
      await video.play();

      if('BarcodeDetector' in window){
        try{
          // QR + common 1D barcodes
          detector = new window.BarcodeDetector({ formats: ['qr_code','code_128','ean_13','ean_8','code_39','upc_a','upc_e'] });
        }catch(_){
          detector = new window.BarcodeDetector();
        }
      }

      running = true;
      btnStartCam.textContent = 'Cámara activa';
      btnStartCam.disabled = true;
      detectLoop();
    }catch(e){
      if(!silent){
        alert('No se pudo abrir la cámara. En iPhone/iPad requiere HTTPS y permisos habilitados.\n\nDetalle: ' + (e && e.message ? e.message : e));
      }
    }
  }

  // Manual dialog
  btnManual.addEventListener('click', (ev)=>{
    ev.preventDefault();
    hideManualErr();
    manualCode.value = '';
    dlgManual.showModal();
    setTimeout(()=>manualCode.focus(), 50);
  });

  btnManualOk.addEventListener('click', async (ev)=>{
    ev.preventDefault();
    hideManualErr();
    const code = normalizeCode(manualCode.value);
    if(!code){
      showManualErr('Ingresá un código');
      return;
    }
    try{
      const res = await window.FlexApi.cartScan(code, 'manual', communityId);
      const d = (res && res.data) ? res.data : {};
      if(d && d.added_to_route){
        toast('Agregado a la ruta');
      }else{
        toast('Agregado');
      }
      feedback('success');
      dlgManual.close();
      await refreshCart();
    }catch(e){
      if(e.message === 'already_in_cart' || e.message === 'already_in_route'){
        feedback('duplicate');
      }else{
        feedback('error');
      }
      showManualErr(e.message);
    }
  });

  btnStartCam.addEventListener('click', (ev)=>{
    ev.preventDefault();
    startCamera();
  });

  if(btnStartRoute){
    btnStartRoute.addEventListener('click', (ev)=>{
      ev.preventDefault();
      startRoute();
    });
  }

  // Autoinicio de cámara al abrir la pestaña "Escanear" (puede requerir interacción en algunos navegadores)
  setTimeout(()=>{ startCamera(true); }, 350);

  // init
  refreshCart();
})();
