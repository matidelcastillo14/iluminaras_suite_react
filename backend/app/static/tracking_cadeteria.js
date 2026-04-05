(function(){
  const $ = (id) => document.getElementById(id);
  const setText = (id, txt) => { const el = $(id); if (el) el.textContent = String(txt ?? ''); };
  const setShown = (id, shown) => { const el = $(id); if (el) el.style.display = shown ? '' : 'none'; };

  function parseCode(raw){
    let s = String(raw || '').trim();
    if (!s) return '';
    // if raw is a URL, try to extract code from query params or last path segment
    try{
      if (s.startsWith('http://') || s.startsWith('https://')){
        const u = new URL(s);
        const qp = u.searchParams;
        const qcode = (qp.get('code') || qp.get('tracking_code') || qp.get('tracking') || '').trim();
        if (qcode) return qcode;
        // known patterns
        const path = (u.pathname || '').replace(/\/+$/,'');
        if (path.includes('/rastreo/go/')){
          return path.split('/rastreo/go/')[1].split('/')[0].trim();
        }
        const seg = path.split('/').filter(Boolean).pop() || '';
        if (seg) return seg.trim();
      }
    } catch(_){ /* ignore */ }

    // known embedded pattern
    const idx = s.indexOf('/rastreo/go/');
    if (idx >= 0){
      s = s.substring(idx + '/rastreo/go/'.length);
    }
    // strip query/hash
    s = s.split('?')[0].split('#')[0];
    // if looks like a path, take last segment
    if (s.includes('/')){
      const seg = s.replace(/\/+$/,'').split('/').filter(Boolean).pop() || '';
      if (seg) s = seg;
    }
    // take first token if spaces
    s = s.split(/\s+/)[0];
    return s.trim();
  }

  // feedback
  let _audioCtx = null;
  async function beep(ok){
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      _audioCtx = _audioCtx || new AudioContext();
      const ctx = _audioCtx;
      if (ctx.state === 'suspended') { try { await ctx.resume(); } catch(_){} }
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = 'sine';
      o.frequency.value = ok ? 880 : 220;
      g.gain.value = 0.0001;
      o.connect(g); g.connect(ctx.destination);
      const now = ctx.currentTime;
      g.gain.setValueAtTime(0.0001, now);
      g.gain.exponentialRampToValueAtTime(0.15, now + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, now + (ok ? 0.09 : 0.12));
      o.start(now); o.stop(now + (ok ? 0.11 : 0.14));
    } catch(_){}
  }
  function vibrate(ok){
    try { if (navigator.vibrate) navigator.vibrate(ok ? 60 : [80,60,80]); } catch(_){}
  }

  async function api(url, body){
    const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{}) });
    let j=null; try{ j=await res.json(); }catch(_){}
    if (!res.ok){
      const msg = (j && j.error) ? j.error : ('http_' + res.status);
      throw new Error(msg);
    }
    return j;
  }
  async function apiGet(url){
    const res = await fetch(url);
    let j=null; try{ j=await res.json(); }catch(_){}
    if (!res.ok){
      const msg = (j && j.error) ? j.error : ('http_' + res.status);
      throw new Error(msg);
    }
    return j;
  }

  // UI state
  let stopScan = null;
  let stopValidate = null;

  let batchItems = [];
  let activeCode = null;
  let selectedCode = null;
  let validated = false;

  const LS_KEY = 'tracking_cadeteria_order_v1';

  function todayStr(){
    try{
      const d = new Date();
      return d.toLocaleDateString(undefined, { year:'numeric', month:'2-digit', day:'2-digit' });
    }catch(_){ return ''; }
  }

  function setTab(which){
    const scan = $('view_scan');
    const route = $('view_route');
    if (!scan || !route) return;

    if (which === 'route'){
      scan.style.display = 'none';
      route.style.display = '';
      $('tab_scan')?.classList.remove('primary');
      $('tab_route')?.classList.add('primary');
      stopScan && stopScan(); stopScan = null;
    } else {
      route.style.display = 'none';
      scan.style.display = '';
      $('tab_route')?.classList.remove('primary');
      $('tab_scan')?.classList.add('primary');
      stopValidate && stopValidate(); stopValidate = null;
      validated = false;
    }
  }

  function computeKpis(){
    const total = batchItems.length;
    const done = batchItems.filter(x => x.status === 'DELIVERED').length;
    const failed = batchItems.filter(x => x.status === 'DELIVERY_FAILED').length;
    const returned = batchItems.filter(x => x.status === 'RETURNED').length;
    const inRoute = batchItems.filter(x => x.status === 'OUT_FOR_DELIVERY' || x.status === 'ON_ROUTE_TO_DELIVERY').length;
    const pending = Math.max(0, total - done - returned);

    setText('kpi_total', total);
    setText('kpi_ready', inRoute);
    setText('kpi_problem', failed);

    setText('kpi_done', done);
    setText('kpi_failed', failed);
    setText('kpi_pending', pending);
  }


  function updateRouteControls(){
    const needsStart = batchItems.some(it => !['OUT_FOR_DELIVERY','ON_ROUTE_TO_DELIVERY','DELIVERED','DELIVERY_FAILED','RETURNED'].includes(it.status));
    setShown('route_actions', needsStart);
  }

  function loadOrderPreference(){
    try{
      const raw = localStorage.getItem(LS_KEY) || '';
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch(_){
      return [];
    }
  }
  function saveOrderPreference(codes){
    try{ localStorage.setItem(LS_KEY, JSON.stringify(codes || [])); } catch(_){}
  }

  function applyManualOrder(items){
    const pref = loadOrderPreference();
    if (!pref.length) return items;

    const byCode = new Map(items.map(i => [i.tracking_code, i]));
    const out = [];
    pref.forEach(c => { if (byCode.has(c)) out.push(byCode.get(c)); });
    items.forEach(i => { if (!pref.includes(i.tracking_code)) out.push(i); });
    return out;
  }

  function renderBatchList(){
    const list = $('batch_list');
    if (!list) return;
    list.innerHTML = '';
    batchItems.forEach((it, idx) => {
      const row = document.createElement('div');
      row.className = 'tc-item';
      row.innerHTML = `
        <div class="tc-item-main">
          <div class="tc-item-title">${idx+1}. ${escapeHtml(it.order_name || '')}</div>
          <div class="tc-item-sub">${escapeHtml(it.tracking_code)} · ${escapeHtml(it.status_label || '')}</div>
          <div class="tc-rowbtn">
            <button class="btn primary" type="button" data-act="open">Ver</button>
            <button class="btn" type="button" data-act="remove">Quitar</button>
          </div>
        </div>
        <div class="tc-badges">
          ${badgeFor(it)}
        </div>
      `;
      row.querySelector('[data-act="open"]').addEventListener('click', async (e) => {
        e.preventDefault();
        await openSheet(it.tracking_code);
      });
      row.querySelector('[data-act="remove"]').addEventListener('click', async (e) => {
        e.preventDefault();
        try{
          await api('/rastreo/cadeteria/api/batch_remove', { code: it.tracking_code });
          await loadBatch();
          setText('scan_status', 'Quitado: ' + it.tracking_code);
        } catch(err){
          setText('scan_status', 'Error: ' + err.message);
        }
      });
      list.appendChild(row);
    });
  }

  function badgeFor(it){
    const a = (it.tracking_code === activeCode);
    if (a) return '<span class="tc-badge active">En camino</span>';
    if (it.status === 'DELIVERED') return '<span class="tc-badge done">Entregado</span>';
    if (it.status === 'DELIVERY_FAILED') return '<span class="tc-badge fail">No entregado</span>';
    if (it.status === 'RETURNED') return '<span class="tc-badge ret">Devuelto</span>';
    if (it.status === 'ON_ROUTE_TO_DELIVERY') return '<span class="tc-badge active">En camino</span>';
    if (it.status === 'OUT_FOR_DELIVERY') return '<span class="tc-badge">En reparto</span>';
    return '<span class="tc-badge">' + escapeHtml(it.status_label || '') + '</span>';
  }

  function renderRouteList(){
    const list = $('route_list');
    if (!list) return;
    list.innerHTML = '';

    const ordered = applyManualOrder(batchItems.slice());
    const codes = ordered.map(x => x.tracking_code);
    saveOrderPreference(codes);

    ordered.forEach((it, idx) => {
      const row = document.createElement('div');
      row.className = 'tc-item';
      row.setAttribute('draggable', 'true');
      row.dataset.code = it.tracking_code;

      const isActive = (it.tracking_code === activeCode) || (it.status === 'ON_ROUTE_TO_DELIVERY' && it.tracking_code === activeCode);
      const canGo = (it.status !== 'DELIVERED' && it.status !== 'RETURNED');

      row.innerHTML = `
        <div class="tc-item-main">
          <div class="tc-item-title">${idx+1}. ${escapeHtml(it.order_name || '')}</div>
          <div class="tc-item-sub">${escapeHtml(it.tracking_code)} · ${escapeHtml(it.status_label || '')}</div>
          <div class="tc-rowbtn">
            <button class="btn primary" type="button" data-act="go" ${canGo ? '' : 'disabled'}>${isActive ? 'Activo' : 'Voy para allá'}</button>
            <button class="btn" type="button" data-act="open">Ver</button>
            ${it.status === 'DELIVERY_FAILED' ? '<button class="btn" type="button" data-act="retry">Reintentar</button>' : ''}
          </div>
        </div>
        <div class="tc-badges">${badgeFor(it)}</div>
      `;

      row.querySelector('[data-act="open"]').addEventListener('click', async (e) => {
        e.preventDefault();
        await openSheet(it.tracking_code);
      });

      row.querySelector('[data-act="go"]').addEventListener('click', async (e) => {
        e.preventDefault();
        await setActive(it.tracking_code);
      });

      const retryBtn = row.querySelector('[data-act="retry"]');
      if (retryBtn){
        retryBtn.addEventListener('click', async (e) => {
          e.preventDefault();
          try{
            await api('/tracking-cadeteria/api/retry', { code: it.tracking_code });
            await beep(true); vibrate(true);
            await loadBatch();
          } catch(err){
            await beep(false); vibrate(false);
            setText('route_status', 'Error reintentando: ' + err.message);
          }
        });
      }

      // drag reorder
      row.addEventListener('dragstart', (ev) => {
        ev.dataTransfer.setData('text/plain', it.tracking_code);
        ev.dataTransfer.effectAllowed = 'move';
      });
      row.addEventListener('dragover', (ev) => {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
      });
      row.addEventListener('drop', (ev) => {
        ev.preventDefault();
        const from = ev.dataTransfer.getData('text/plain');
        const to = it.tracking_code;
        if (!from || !to || from === to) return;
        reorder(from, to);
        renderRouteList();
      });

      list.appendChild(row);
    });

    setShown('validate_box', !!selectedCode);
  }

  function reorder(fromCode, toCode){
    const pref = loadOrderPreference();
    const codes = pref.length ? pref.slice() : batchItems.map(x => x.tracking_code);
    const fromIdx = codes.indexOf(fromCode);
    const toIdx = codes.indexOf(toCode);
    if (fromIdx < 0 || toIdx < 0) return;
    codes.splice(fromIdx, 1);
    codes.splice(toIdx, 0, fromCode);
    saveOrderPreference(codes);
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

    computeKpis();
    renderBatchList();
    renderRouteList();
    updateRouteControls();
  }

  async function addToBatch(raw){
    const code = parseCode(raw);
    if (!code) return;
    try {
      const j = await api('/rastreo/cadeteria/api/batch_add', { code });
      await beep(true); vibrate(true);
      setText('scan_status', j.added ? ('Agregado: ' + j.shipment.tracking_code) : ('Ya estaba: ' + j.shipment.tracking_code));
      await loadBatch();
    } catch(err){
      await beep(false); vibrate(false);
      setText('scan_status', 'Error: ' + err.message);
    }
  }

  async function startReparto(){
    try{
      setText('scan_status', 'Iniciando reparto...');
      const j = await api('/rastreo/cadeteria/api/start_reparto', {});
      const errs = (j.errors || []);
      setText('scan_status', errs.length ? ('Reparto iniciado con errores: ' + errs.map(e => e.tracking_code).join(', ')) : 'Reparto iniciado.');
      await loadBatch();
      setTab('route');
    } catch(err){
      setText('scan_status', 'Error: ' + err.message);
    }
  }


  async function ensureRepartoIfNeeded(code){
    const it = batchItems.find(x => x.tracking_code === code);
    if (!it) return;
    // if it's already in the reparto workflow, do nothing
    if (it.status === 'OUT_FOR_DELIVERY' || it.status === 'ON_ROUTE_TO_DELIVERY' || it.status === 'DELIVERED' || it.status === 'DELIVERY_FAILED' || it.status === 'RETURNED'){
      return;
    }
    // start reparto for the whole batch (backend only supports batch start)
    setText('route_status', 'Iniciando reparto...');
    await api('/rastreo/cadeteria/api/start_reparto', {});
    await loadBatch();
  }

  async function setActive(code){
    // En ML: "Voy para allá" -> activa + estado ON_ROUTE
    try{
      selectedCode = code;
      validated = false;
      setText('route_status', 'Activo: ' + code + '. Validá escaneando el QR del paquete.');
      setShown('validate_box', true);
      setText('validate_status', 'Listo para validar: ' + code);
      await ensureRepartoIfNeeded(code);
      await api('/rastreo/cadeteria/api/select_active', { code });
      activeCode = code;
      await loadBatch();
    } catch(err){
      setText('route_status', 'Error: ' + err.message);
    }
  }

  // Bottom sheet
  function openSheetUI(){
    setShown('sheet_backdrop', true);
    setShown('sheet', true);
  }
  function closeSheet(){
    setShown('sheet_backdrop', false);
    setShown('sheet', false);
  }

  function escapeHtml(s){
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  async function openSheet(code){
    openSheetUI();
    setText('sheet_sub', 'Cargando...');
    setText('sheet_title', code);
    $('sheet_body').innerHTML = '';
    $('sheet_actions').innerHTML = '';
    setShown('sheet_open_detail', false);
    setShown('sheet_maps', false);
    setShown('sheet_call', false);

    let order = null;
    let ship = null;
    try{
      const j = await apiGet('/tracking-cadeteria/api/order_detail?code=' + encodeURIComponent(code));
      ship = j.shipment;
      order = j.order;
    } catch(err){
      setText('sheet_sub', 'Error: ' + err.message);
      return;
    }

    setText('sheet_sub', (ship.order_name || '') + ' · ' + (ship.status_label || ''));
    setText('sheet_title', order.pedido || ship.order_name || code);

    const tel = (order.telefono || '').trim();
    const addr = (order.direccion || '').trim();
    const obs = (order.observaciones || '').trim();
    $('sheet_body').innerHTML = `
      <div><strong>${escapeHtml(order.nombre || '')}</strong></div>
      <div class="tc-note" style="margin-top:6px;">${escapeHtml(addr)}</div>
      ${obs ? ('<div class="tc-note" style="margin-top:10px;"><strong>Obs:</strong> ' + escapeHtml(obs) + '</div>') : ''}
      <div class="tc-note" style="margin-top:10px;"><strong>Código:</strong> ${escapeHtml(code)}</div>
    `;

    const detailLink = $('sheet_open_detail');
    if (detailLink){
      detailLink.href = '/tracking-cadeteria/pedido/' + encodeURIComponent(code);
      setShown('sheet_open_detail', true);
    }

    const mapsLink = $('sheet_maps');
    if (mapsLink && addr){
      mapsLink.href = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(addr);
      setShown('sheet_maps', true);
    }

    const callLink = $('sheet_call');
    if (callLink && tel){
      callLink.href = 'tel:' + tel;
      callLink.textContent = 'Llamar ' + tel;
      setShown('sheet_call', true);
    }

    // acciones rápidas
    $('sheet_actions').innerHTML = `
      <div class="tc-card" style="border-radius:16px;">
        <h4 style="margin:0 0 10px 0;">Acciones</h4>

        <div class="grid" style="grid-template-columns:1fr;gap:10px;">
          <div class="card" style="border-radius:16px;">
            <h5 style="margin:0 0 8px 0;">Entregado</h5>
            <label>Relación (requerido)</label>
            <select id="del_receiver_relation">
              <option value="">Seleccionar...</option>
                            <option value="Titular (comprador)">Titular (comprador)</option>
              <option value="Cónyuge / pareja">Cónyuge / pareja</option>
              <option value="Padre / Madre">Padre / Madre</option>
              <option value="Hijo/a">Hijo/a</option>
              <option value="Hermano/a">Hermano/a</option>
              <option value="Otro familiar">Otro familiar</option>
              <option value="Amigo/a">Amigo/a</option>
              <option value="Vecino/a">Vecino/a</option>
              <option value="Portero / Conserje">Portero / Conserje</option>
              <option value="Recepción / Administración">Recepción / Administración</option>
              <option value="Guardia de seguridad">Guardia de seguridad</option>
              <option value="Empleada doméstica">Empleada doméstica</option>
              <option value="Encargado/a">Encargado/a</option>
              <option value="Compañero/a de trabajo">Compañero/a de trabajo</option>
              <option value="Otro">Otro</option>
            </select>
            <label>Nombre (requerido)</label>
            <input id="del_receiver_name" placeholder="Nombre" />
            <label>Documento (requerido)</label>
            <input id="del_receiver_id" placeholder="CI" />
            <button class="btn primary" type="button" id="btn_do_delivered" style="margin-top:10px;">Marcar entregado</button>
          </div>

          <div class="card" style="border-radius:16px;">
            <h5 style="margin:0 0 8px 0;">No entregado</h5>
            <label>Motivo (requerido)</label>
            <select id="fail_reason">
              <option value="">Seleccionar...</option>
              <option>No atienden</option>
              <option>Dirección incorrecta</option>
              <option>Cliente rechazó</option>
              <option>No se pudo coordinar</option>
              <option>Problema de seguridad</option>
              <option>Otro</option>
            </select>
            <label>Detalle (opcional)</label>
            <input id="fail_detail" placeholder="Detalle" />
            <button class="btn primary" type="button" id="btn_do_failed" style="margin-top:10px;">Marcar no entregado</button>
          </div>

          <div class="card" style="border-radius:16px;">
            <h5 style="margin:0 0 8px 0;">Devuelto</h5>
            <label>Nota (opcional)</label>
            <input id="ret_note" placeholder="Ej: Devuelto al depósito" />
            <button class="btn primary" type="button" id="btn_do_returned" style="margin-top:10px;">Marcar devuelto</button>
          </div>
        </div>

        <div class="tc-note" style="margin-top:10px;">
          Requiere validación QR si el pedido está activo.
        </div>
      </div>
    `;

    const ensureAllowed = async () => {
      // Only enforce validation for the currently active shipment
      if (selectedCode === code && !validated){
        const ok = window.confirm('No validaste el QR del paquete. ¿Marcar igualmente?');
        if (!ok) throw new Error('need_validation');
      }
    };

    $('btn_do_delivered')?.addEventListener('click', async () => {
      try{
        await ensureAllowed();
        const receiver_relation = ($('del_receiver_relation').value || '').trim();
        const receiver_name = ($('del_receiver_name').value || '').trim();
        const receiver_id = ($('del_receiver_id').value || '').trim();
        if(!receiver_relation || !receiver_name || !receiver_id){
          throw new Error('receiver_required');
        }
        await mark(code, 'DELIVERED', { receiver_relation, receiver_name, receiver_id });
        closeSheet();
      } catch(err){
        setText('route_status', err.message === 'need_validation' ? 'Validá el QR del paquete (Reparto → Escanear para validar) o confirmá sin validar.' : ('Error: ' + (err.message === 'receiver_required' ? 'Para marcar ENTREGADO tenés que completar: relación, nombre y documento.' : err.message)));
      }
    });

    $('btn_do_failed')?.addEventListener('click', async () => {
      try{
        await ensureAllowed();
        const reason = ($('fail_reason').value || '').trim();
        const detail = ($('fail_detail').value || '').trim();
        await mark(code, 'DELIVERY_FAILED', { reason, detail });
        closeSheet();
      } catch(err){
        setText('route_status', err.message === 'need_validation' ? 'Validá el QR del paquete (Reparto → Escanear para validar) o confirmá sin validar.' : ('Error: ' + (err.message === 'receiver_required' ? 'Para marcar ENTREGADO tenés que completar: relación, nombre y documento.' : err.message)));
      }
    });

    $('btn_do_returned')?.addEventListener('click', async () => {
      try{
        await ensureAllowed();
        const note = ($('ret_note').value || '').trim();
        await mark(code, 'RETURNED', { note });
        closeSheet();
      } catch(err){
        setText('route_status', err.message === 'need_validation' ? 'Validá el QR del paquete (Reparto → Escanear para validar) o confirmá sin validar.' : ('Error: ' + (err.message === 'receiver_required' ? 'Para marcar ENTREGADO tenés que completar: relación, nombre y documento.' : err.message)));
      }
    });
  }

  async function mark(code, eventType, payload){
    try{
      const j = await api('/rastreo/cadeteria/api/mark', Object.assign({ code, event_type: eventType }, payload || {}));
      await beep(true); vibrate(true);
      setText('route_status', 'OK: ' + (j.shipment?.status_label || ''));
      // Reset state
      if (selectedCode === code){
        selectedCode = null;
        validated = false;
        activeCode = null;
        stopValidate && stopValidate(); stopValidate = null;
        setShown('validate_box', false);
      }
      await loadBatch();
    } catch(err){
      await beep(false); vibrate(false);
      throw err;
    }
  }

  async function startValidation(){
    if (!selectedCode){
      setText('route_status', 'Elegí un pedido y tocá "Voy para allá".');
      return;
    }
    if (stopValidate) return;

    setText('validate_status', 'Cámara activa. Escaneá el QR del paquete seleccionado...');
    stopValidate = await window.RastreoScanner.startCameraScan({
      videoId: 'qr_video_validate',
      statusId: 'validate_status',
      continuous: true,
      debounceMs: 900,
      stopOnCode: false,
      onCode: async (raw) => {
        const code = parseCode(raw);
        if (!code) return false;
        if (code !== selectedCode){
          await beep(false); vibrate(false);
          setText('validate_status', 'QR NO coincide. Seleccionado: ' + selectedCode + ' / Escaneado: ' + code);
          return false;
        }
        await beep(true); vibrate(true);
        validated = true;
        setText('validate_status', 'QR OK. Ahora podés marcar la entrega.');
        return { stop:true };
      }
    });
  }

  function bind(){
    setText('tc_today', todayStr());

    $('tab_scan')?.addEventListener('click', () => setTab('scan'));
    $('tab_route')?.addEventListener('click', () => setTab('route'));

    $('btn_scan_start')?.addEventListener('click', async () => {
      if (stopScan) return;
      stopScan = await window.RastreoScanner.startCameraScan({
        videoId: 'qr_video_scan',
        statusId: 'scan_status',
        continuous: true,
        debounceMs: 1200,
        onCode: async (raw) => { await addToBatch(raw); return false; }
      });
    });
    $('btn_scan_stop')?.addEventListener('click', () => { stopScan && stopScan(); stopScan=null; });

    $('btn_batch_clear')?.addEventListener('click', async () => {
      try{
        await api('/rastreo/cadeteria/api/batch_clear', {});
        batchItems = [];
        activeCode = null;
        selectedCode = null;
        validated = false;
        saveOrderPreference([]);
        await loadBatch();
        setText('scan_status', 'Lista vaciada.');
      } catch(err){
        setText('scan_status', 'Error: ' + err.message);
      }
    });

    $('btn_start_route')?.addEventListener('click', startReparto);
    $('btn_start_route_route')?.addEventListener('click', startReparto);
    $('btn_validate_start')?.addEventListener('click', startValidation);
    $('btn_validate_stop')?.addEventListener('click', () => { stopValidate && stopValidate(); stopValidate=null; setText('validate_status','Cámara detenida.'); });

    $('sheet_close')?.addEventListener('click', closeSheet);
    $('sheet_backdrop')?.addEventListener('click', closeSheet);
  }

  window.addEventListener('load', async () => {
    bind();
    try { await loadBatch(); } catch(_){}
    setTab('scan');
  });
})();
