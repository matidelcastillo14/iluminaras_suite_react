(function(){
  const $ = (id) => document.getElementById(id);
  const setText = (id, txt) => {
    const el = $(id);
    if (!el) return;
    el.textContent = String(txt ?? '');
  };
  const setHtml = (id, html) => {
    const el = $(id);
    if (!el) return;
    el.innerHTML = html;
  };
  const setShown = (id, shown) => {
    const el = $(id);
    if (!el) return;
    el.style.display = shown ? '' : 'none';
  };

  function parseCode(raw){
    let code = String(raw || '').trim();
    if (!code) return '';
    const idx = code.indexOf('/rastreo/go/');
    if (idx >= 0){
      code = code.substring(idx + '/rastreo/go/'.length).split('?')[0].replace(/\/+$/, '');
    }
    return code.trim();
  }

  // --- feedback (sonido + vibración)
  let _audioCtx = null;
  async function beep(ok){
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      _audioCtx = _audioCtx || new AudioContext();
      const ctx = _audioCtx;
      // iOS Safari often requires an explicit resume after a user gesture.
      if (ctx.state === 'suspended') {
        try { await ctx.resume(); } catch(_){ }
      }
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = 'sine';
      o.frequency.value = ok ? 880 : 220;
      g.gain.value = 0.0001;
      o.connect(g);
      g.connect(ctx.destination);
      const now = ctx.currentTime;
      g.gain.setValueAtTime(0.0001, now);
      g.gain.exponentialRampToValueAtTime(0.15, now + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, now + (ok ? 0.09 : 0.12));
      o.start(now);
      o.stop(now + (ok ? 0.11 : 0.14));
    } catch(_){ }
  }

  function vibrate(ok){
    try {
      if (!navigator.vibrate) return;
      navigator.vibrate(ok ? 60 : [80, 60, 80]);
    } catch(_){ }
  }

  async function api(url, body){
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    let j = null;
    try { j = await res.json(); } catch(_){ }
    if (!res.ok) {
      const msg = (j && j.error) ? j.error : ('http_' + res.status);
      throw new Error(msg);
    }
    return j;
  }

  async function apiGet(url){
    const res = await fetch(url);
    let j = null;
    try { j = await res.json(); } catch(_){ }
    if (!res.ok) {
      const msg = (j && j.error) ? j.error : ('http_' + res.status);
      throw new Error(msg);
    }
    return j;
  }

  // --- state
  let batchItems = [];
  let activeCode = null;
  let selectedCode = null;
  let validated = false;
  let stopCarga = null;
  let stopVal = null;

  function setTab(which){
    const carga = $('view_carga');
    const reparto = $('view_reparto');
    if (!carga || !reparto) return;

    if (which === 'reparto'){
      carga.style.display = 'none';
      reparto.style.display = '';
      $('tab_carga').classList.remove('primary');
      $('tab_reparto').classList.add('primary');
      stopCarga && stopCarga();
      stopCarga = null;
    } else {
      reparto.style.display = 'none';
      carga.style.display = '';
      $('tab_reparto').classList.remove('primary');
      $('tab_carga').classList.add('primary');
      stopVal && stopVal();
      stopVal = null;
    }
  }

  function renderBatch(){
    setText('batch_count', batchItems.length);
    const list = $('batch_list');
    if (!list) return;
    list.innerHTML = '';
    batchItems.forEach((it) => {
      const row = document.createElement('div');
      row.className = 'rw-item';

      const left = document.createElement('div');
      left.className = 'rw-item-main';
      left.innerHTML = `<div class="rw-item-title">${it.order_name || ''}</div>
        <div class="rw-item-sub">${it.tracking_code} · ${it.status_label}</div>`;

      const btn = document.createElement('button');
      btn.className = 'btn rw-btn-small';
      btn.type = 'button';
      btn.textContent = 'Quitar';
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        try {
          await api('/rastreo/cadeteria/api/batch_remove', { code: it.tracking_code });
          await loadBatch();
        } catch(err){
          setText('scan_status_carga', 'Error quitando: ' + err.message);
        }
      });

      row.appendChild(left);
      row.appendChild(btn);
      list.appendChild(row);
    });
  }

  function renderReparto(){
    const list = $('reparto_list');
    if (!list) return;
    list.innerHTML = '';

    batchItems.forEach((it) => {
      const row = document.createElement('div');
      row.className = 'rw-item rw-item-click';
      const isActive = (it.tracking_code === activeCode);
      const isSelected = (it.tracking_code === selectedCode);

      const badge = isActive ? '<span style="font-size:12px;color:#0a7;">● Activo</span>' : '';
      const sel = isSelected ? '<span style="font-size:12px;color:#06c;">● Seleccionado</span>' : '';

      const done = (it.status === 'DELIVERED');
      const failed = (it.status === 'DELIVERY_FAILED');
      const returned = (it.status === 'RETURNED');
      const statusTag = done ? '✅' : (failed ? '⚠️' : (returned ? '↩️' : ''));

      row.innerHTML = `<div class="rw-item-main">
          <div class="rw-item-title">${it.order_name || ''} <span class="rw-tag">${statusTag}</span></div>
          <div class="rw-item-sub">${it.tracking_code} · ${it.status_label}</div>
        </div>
        <div class="rw-item-meta">${badge}${sel}</div>`;

      row.addEventListener('click', async () => {
        await selectShipment(it.tracking_code);
      });

      list.appendChild(row);
    });

    // panel seleccionado
    if (!selectedCode) {
      setHtml('selected_box', '<div class="rw-muted">Ninguno seleccionado.</div>');
      const btn = $('btn_validate_scan');
      if (btn) btn.disabled = true;
      setShown('btn_open_detail', false);
      setText('val_status', '');
    } else {
      const statusTxt = validated ? 'QR OK. Elegí la acción.' : 'Seleccionado. Escaneá para validar el paquete.';
      setHtml('selected_box', `<div><strong>${selectedCode}</strong></div><div class="rw-muted">${statusTxt}</div>`);
      const btn = $('btn_validate_scan');
      if (btn) btn.disabled = false;
      const link = $('btn_open_detail');
      if (link) {
        link.href = '/rastreo/cadeteria/' + encodeURIComponent(selectedCode);
      }
      setShown('btn_open_detail', true);
    }

    // acciones tras validar
    const actions = $('actions_box');
    if (actions) {
      const enabled = !!(selectedCode && validated);
      actions.style.opacity = enabled ? '1' : '0.55';
      actions.style.pointerEvents = enabled ? 'auto' : 'none';
    }
  }

  async function loadBatch(){
    const j = await apiGet('/rastreo/cadeteria/api/batch_list');
    batchItems = (j.items || []).map(x => ({
      tracking_code: x.tracking_code,
      order_name: x.order_name,
      status: x.status,
      status_label: x.status_label,
    }));
    activeCode = j.active_code || null;
    if (selectedCode && !batchItems.find(x => x.tracking_code === selectedCode)){
      selectedCode = null;
      validated = false;
    }
    renderBatch();
    renderReparto();
  }

  async function addToBatch(raw){
    const code = parseCode(raw);
    if (!code) return;
    try {
      const j = await api('/rastreo/cadeteria/api/batch_add', { code });
      await beep(true);
      vibrate(true);
      if (j.added) {
        setText('scan_status_carga', `Agregado: ${j.shipment.tracking_code}`);
      } else {
        setText('scan_status_carga', `Ya estaba en la lista: ${j.shipment.tracking_code}`);
      }
      await loadBatch();
    } catch(err){
      await beep(false);
      vibrate(false);
      setText('scan_status_carga', 'Error: ' + err.message);
    }
  }

  async function selectShipment(code){
    selectedCode = code;
    validated = false;
    setText('val_status', 'Seleccionado. Escaneá el QR del paquete para validar.');
    renderReparto();

    try {
      const j = await api('/rastreo/cadeteria/api/select_active', { code });
      activeCode = (j.shipment && j.shipment.tracking_code) ? j.shipment.tracking_code : activeCode;
      await loadBatch();
    } catch(err){
      setText('val_status', 'Error seleccionando: ' + err.message);
    }
  }

  async function mark(eventType, payload){
    if (!selectedCode) return;
    try {
      setText('val_status', 'Guardando...');
      const j = await api('/rastreo/cadeteria/api/mark', Object.assign({ code: selectedCode, event_type: eventType }, payload || {}));
      await beep(true);
      vibrate(true);
      setText('val_status', `OK: ${j.shipment.status_label}`);
      validated = false;
      selectedCode = null;
      activeCode = null;
      stopVal && stopVal();
      stopVal = null;
      await loadBatch();
    } catch(err){
      await beep(false);
      vibrate(false);
      setText('val_status', 'Error: ' + err.message);
    }
  }

  function bind(){
    const tabCarga = $('tab_carga');
    const tabReparto = $('tab_reparto');
    tabCarga && tabCarga.addEventListener('click', () => setTab('carga'));
    tabReparto && tabReparto.addEventListener('click', () => setTab('reparto'));

    $('btn_start_carga')?.addEventListener('click', async () => {
      if (stopCarga) return;
      stopCarga = await window.RastreoScanner.startCameraScan({
        videoId: 'qr_video_carga',
        statusId: 'scan_status_carga',
        continuous: true,
        debounceMs: 1200,
        onCode: async (raw) => {
          await addToBatch(raw);
          return false; // no detener
        }
      });
    });

    $('btn_stop_carga')?.addEventListener('click', () => {
      stopCarga && stopCarga();
      stopCarga = null;
    });

    $('btn_clear_batch')?.addEventListener('click', async () => {
      try {
        await api('/rastreo/cadeteria/api/batch_clear', {});
        batchItems = [];
        activeCode = null;
        selectedCode = null;
        validated = false;
        renderBatch();
        renderReparto();
        setText('scan_status_carga', 'Lista vaciada.');
      } catch(err){
        setText('scan_status_carga', 'Error: ' + err.message);
      }
    });

    $('btn_start_reparto')?.addEventListener('click', async () => {
      try {
        setText('scan_status_carga', 'Marcando pedidos en reparto...');
        const j = await api('/rastreo/cadeteria/api/start_reparto', {});
        const errs = (j.errors || []);
        if (errs.length){
          setText('scan_status_carga', 'Reparto iniciado con errores: ' + errs.map(e => e.tracking_code).join(', '));
        } else {
          setText('scan_status_carga', 'Reparto iniciado.');
        }
        await loadBatch();
        setTab('reparto');
      } catch(err){
        setText('scan_status_carga', 'Error: ' + err.message);
      }
    });

    $('btn_validate_scan')?.addEventListener('click', async () => {
      if (!selectedCode) return;
      if (stopVal) return;
      setText('val_status', 'Cámara activa. Escaneá el QR del paquete seleccionado...');

      stopVal = await window.RastreoScanner.startCameraScan({
        videoId: 'qr_video_valid',
        statusId: 'val_status',
        continuous: true,
        debounceMs: 900,
        stopOnCode: false,
        onCode: async (raw) => {
          const code = parseCode(raw);
          if (!code) return false;
          if (code !== selectedCode){
            await beep(false);
            vibrate(false);
            setText('val_status', `QR NO coincide. Seleccionado: ${selectedCode} / Escaneado: ${code}`);
            return false; // seguir
          }
          await beep(true);
          vibrate(true);
          validated = true;
          setText('val_status', 'QR OK. Elegí la acción.');
          renderReparto();
          return { stop: true };
        }
      });
    });

    $('btn_stop_valid')?.addEventListener('click', () => {
      stopVal && stopVal();
      stopVal = null;
      setText('val_status', 'Cámara detenida.');
    });

    $('btn_mark_delivered')?.addEventListener('click', async () => {
      const receiver_relation = ($('del_receiver_relation').value || '').trim();
      const receiver_name = ($('del_receiver_name').value || '').trim();
      const receiver_id = ($('del_receiver_id').value || '').trim();

      if (!receiver_relation || !receiver_name || !receiver_id){
        setText('val_status', 'Para marcar ENTREGADO tenés que completar: relación, nombre y documento.');
        return;
      }

      await mark('DELIVERED', { receiver_relation, receiver_name, receiver_id });
    });

    $('btn_mark_failed')?.addEventListener('click', async () => {
      const reason = ($('fail_reason').value || '').trim();
      const detail = ($('fail_detail').value || '').trim();
      await mark('DELIVERY_FAILED', { reason, detail });
    });

    $('btn_mark_returned')?.addEventListener('click', async () => {
      const note = ($('ret_note').value || '').trim();
      await mark('RETURNED', { note });
    });

    // init
    setTab('carga');
  }

  window.addEventListener('load', async () => {
    try {
      bind();
      await loadBatch();
    } catch(err){
      // noop
    }
  });
})();
