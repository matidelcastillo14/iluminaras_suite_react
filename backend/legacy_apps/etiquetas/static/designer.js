(() => {
  const CFG = window.__LABEL;
  const canvas = document.getElementById('canvas');
  const saveBtn = document.getElementById('saveBtn');
  const resetBtn = document.getElementById('resetBtn');
  const addText = document.getElementById('addText');
  const addLine = document.getElementById('addLine');
  const addRect = document.getElementById('addRect');
  const addImg = document.getElementById('addImg');
  const addQr = document.getElementById('addQr');
  const delEl = document.getElementById('delEl');
  const props = document.getElementById('props');
  const noSel = document.getElementById('noSel');

  const mm2px = (mm) => mm * state.scale;
  const px2mm = (px) => px / state.scale;

  const state = {
    tpl: null,
    elements: [],
    selectedId: null,
    scale: 4,
  };

  function uid(prefix){
    return `${prefix}_${Math.random().toString(16).slice(2,8)}${Date.now().toString(16).slice(-4)}`;
  }

  function clamp(n, a, b){ return Math.max(a, Math.min(b, n)); }

  function computeScale(){
    // Ajuste al ancho disponible
    const wrap = canvas.parentElement;
    const maxW = Math.max(320, wrap.clientWidth - 24);
    const scale = maxW / CFG.width_mm;
    state.scale = clamp(scale, 2, 7);
  }

  function setCanvasSize(){
    computeScale();
    canvas.style.width = `${mm2px(CFG.width_mm)}px`;
    canvas.style.height = `${mm2px(CFG.height_mm)}px`;
    canvas.style.border = '1px solid #e5e5e5';
    canvas.style.borderRadius = '10px';
  }

  async function loadTemplate(){
    const r = await fetch(CFG.api.templateGet);
    const tpl = await r.json();
    state.tpl = tpl;
    state.elements = Array.isArray(tpl.elements) ? tpl.elements : [];
    // sincronizar tamaño de página
    if(!tpl.page) tpl.page = {};
    tpl.page.width_mm = CFG.width_mm;
    tpl.page.height_mm = CFG.height_mm;
  }

  function elBbox(el){
    const t = (el.type||'').toLowerCase();
    if(t === 'line'){
      const x1 = +el.x1_mm||0, y1 = +el.y1_mm||0, x2 = +el.x2_mm||0, y2 = +el.y2_mm||0;
      return {
        x: Math.min(x1,x2),
        y: Math.min(y1,y2),
        w: Math.max(1, Math.abs(x2-x1)),
        h: Math.max(1, Math.abs(y2-y1)),
      };
    }
    if(t === 'qr'){
      const s = +el.size_mm || 24;
      return { x: +el.x_mm||0, y: +el.y_mm||0, w: s, h: s };
    }
    return { x: +el.x_mm||0, y: +el.y_mm||0, w: +el.w_mm||10, h: +el.h_mm||5 };
  }

  function setElBbox(el, bb){
    const t = (el.type||'').toLowerCase();
    if(t === 'line'){
      // Mantener orientación si es horizontal o vertical; sino ajustar solo x2/y2
      const x1 = +el.x1_mm||0, y1 = +el.y1_mm||0, x2 = +el.x2_mm||0, y2 = +el.y2_mm||0;
      const dx = x2-x1, dy = y2-y1;
      if(Math.abs(dx) >= Math.abs(dy)){
        el.x1_mm = bb.x;
        el.x2_mm = bb.x + bb.w;
        el.y1_mm = bb.y;
        el.y2_mm = bb.y;
      } else {
        el.x1_mm = bb.x;
        el.x2_mm = bb.x;
        el.y1_mm = bb.y;
        el.y2_mm = bb.y + bb.h;
      }
      return;
    }
    if(t === 'qr'){
      el.x_mm = bb.x;
      el.y_mm = bb.y;
      el.size_mm = Math.max(8, Math.min(bb.w, bb.h));
      return;
    }
    el.x_mm = bb.x;
    el.y_mm = bb.y;
    el.w_mm = Math.max(1, bb.w);
    el.h_mm = Math.max(1, bb.h);
  }

  function cssForElement(el){
    const bb = elBbox(el);
    return {
      left: `${mm2px(bb.x)}px`,
      top: `${mm2px(bb.y)}px`,
      width: `${mm2px(bb.w)}px`,
      height: `${mm2px(bb.h)}px`,
    };
  }

  function render(){
    setCanvasSize();
    canvas.innerHTML = '';

    // fondo (para ver márgenes)
    canvas.style.background = '#fff';

    for(const el of state.elements){
      const div = document.createElement('div');
      div.className = 'el';
      div.dataset.id = el.id || '';
      const t = (el.type||'').toLowerCase();
      div.dataset.type = t;

      Object.assign(div.style, cssForElement(el));

      if(state.selectedId && state.selectedId === el.id){
        div.classList.add('selected');
      }

      if(t === 'text'){
        div.style.border = '1px dashed #bbb';
        div.style.padding = '2px 3px';
        div.style.display = 'flex';
        div.style.alignItems = 'flex-start';
        div.style.justifyContent = 'flex-start';
        div.style.overflow = 'hidden';
        div.style.fontFamily = (el.font || 'Helvetica').replace('Helvetica', 'Arial');
        div.style.fontWeight = el.bold ? '700' : '400';
        div.style.fontSize = `${Math.max(8, (el.size||10))}px`;
        div.style.textAlign = el.align || 'left';
        div.textContent = el.value || '';
      }

      if(t === 'rect'){
        div.classList.add('rect');
        div.style.border = `${Math.max(1, el.stroke||1)}px solid #111`;
        div.style.background = el.fill ? '#eee' : 'transparent';
      }

      if(t === 'line'){
        div.classList.add('line');
        const x1 = +el.x1_mm||0, y1 = +el.y1_mm||0, x2 = +el.x2_mm||0, y2 = +el.y2_mm||0;
        const horizontal = Math.abs(x2-x1) >= Math.abs(y2-y1);
        const sw = Math.max(1, (el.stroke||1));
        if(horizontal){
          div.style.height = `${sw}px`;
          div.style.top = `${mm2px(Math.min(y1,y2))}px`;
          div.style.width = `${mm2px(Math.abs(x2-x1))}px`;
          div.style.left = `${mm2px(Math.min(x1,x2))}px`;
        } else {
          div.style.width = `${sw}px`;
          div.style.left = `${mm2px(Math.min(x1,x2))}px`;
          div.style.height = `${mm2px(Math.abs(y2-y1))}px`;
          div.style.top = `${mm2px(Math.min(y1,y2))}px`;
        }
        div.style.background = '#111';
      }

      if(t === 'image'){
        div.style.border = '1px dashed #bbb';
        div.style.overflow = 'hidden';
        const img = document.createElement('img');
        img.style.width = '100%';
        img.style.height = '100%';
        img.style.objectFit = (el.fit || 'contain');
        const src = (el.src||'').toString();
        if(src.startsWith('upload:')){
          img.src = `/static/uploads/${src.split(':')[1]}`;
        } else if(src.startsWith('logo:')){
          const mode = src.split(':')[1] || 'auto';
          img.src = CFG.api.logoPreview + `?brand=${encodeURIComponent(mode)}`;
        } else {
          img.src = src;
        }
        div.appendChild(img);
      }

      if(t === 'qr'){
        div.classList.add('qr');
        div.textContent = 'QR';
      }

      // handles
      const handle = document.createElement('div');
      handle.className = 'handle';
      div.appendChild(handle);
      if(t === 'line'){
        const h2 = document.createElement('div');
        h2.className = 'handle2';
        div.appendChild(h2);
      }

      div.addEventListener('pointerdown', (e) => onPointerDown(e, el, div));
      canvas.appendChild(div);
    }

    renderProps();
  }

  function select(id){
    state.selectedId = id;
    render();
  }

  function selected(){
    return state.elements.find(e => e.id === state.selectedId) || null;
  }

  function removeSelected(){
    const el = selected();
    if(!el) return;
    state.elements = state.elements.filter(e => e.id !== el.id);
    state.selectedId = null;
    render();
  }

  function onPointerDown(e, el, div){
    e.preventDefault();
    e.stopPropagation();
    select(el.id);

    const isHandle = e.target && e.target.classList && e.target.classList.contains('handle');
    const isHandle2 = e.target && e.target.classList && e.target.classList.contains('handle2');

    const start = { x: e.clientX, y: e.clientY };
    const bb0 = elBbox(el);

    const move = (ev) => {
      const dx = px2mm(ev.clientX - start.x);
      const dy = px2mm(ev.clientY - start.y);

      if(isHandle || isHandle2){
        const bb = {...bb0};
        if((el.type||'').toLowerCase()==='line'){
          // resize endpoint
          if(isHandle2){
            // mover origen
            el.x1_mm = (+(el.x1_mm||0)) + dx;
            el.y1_mm = (+(el.y1_mm||0)) + dy;
          } else {
            el.x2_mm = (+(el.x2_mm||0)) + dx;
            el.y2_mm = (+(el.y2_mm||0)) + dy;
          }
        } else {
          bb.w = Math.max(1, bb0.w + dx);
          bb.h = Math.max(1, bb0.h + dy);
          setElBbox(el, bb);
        }
      } else {
        // move
        if((el.type||'').toLowerCase()==='line'){
          el.x1_mm = (+(el.x1_mm||0)) + dx;
          el.y1_mm = (+(el.y1_mm||0)) + dy;
          el.x2_mm = (+(el.x2_mm||0)) + dx;
          el.y2_mm = (+(el.y2_mm||0)) + dy;
        } else {
          const bb = {...bb0, x: bb0.x + dx, y: bb0.y + dy};
          setElBbox(el, bb);
        }
      }

      render();
    };

    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  function inputRow(label, value, onChange, type='number', step='0.5'){
    const l = document.createElement('label');
    l.textContent = label;
    const inp = document.createElement('input');
    inp.type = type;
    if(type==='number') inp.step = step;
    inp.value = (value ?? '').toString();
    inp.addEventListener('input', () => onChange(inp.value));
    return [l, inp];
  }

  function textAreaRow(label, value, onChange){
    const l = document.createElement('label');
    l.textContent = label;
    const ta = document.createElement('textarea');
    ta.value = (value ?? '').toString();
    ta.addEventListener('input', () => onChange(ta.value));
    return [l, ta];
  }

  function selectRow(label, value, options, onChange){
    const l = document.createElement('label');
    l.textContent = label;
    const sel = document.createElement('select');
    for(const [val, txt] of options){
      const o = document.createElement('option');
      o.value = val;
      o.textContent = txt;
      if(val === value) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener('change', () => onChange(sel.value));
    return [l, sel];
  }

  function renderProps(){
    const el = selected();
    if(!el){
      props.style.display = 'none';
      noSel.style.display = 'block';
      props.innerHTML = '';
      return;
    }

    props.innerHTML = '';
    props.style.display = 'block';
    noSel.style.display = 'none';

    const t = (el.type||'').toLowerCase();
    const title = document.createElement('div');
    title.style.fontWeight = '700';
    title.style.marginBottom = '8px';
    title.textContent = `Elemento: ${t} (${el.id})`;
    props.appendChild(title);

    const bb = elBbox(el);

    // Posición y tamaño
    for(const [lab, key] of [['X (mm)','x'],['Y (mm)','y'],['W (mm)','w'],['H (mm)','h']]){
      if(t==='line' && (key==='w' || key==='h')) continue;
      if(t==='qr' && (key==='w' || key==='h')) continue;
      const [l, inp] = inputRow(lab, bb[key], (v) => {
        const num = parseFloat(v||'0');
        const bb2 = {...bb};
        bb2[key] = isNaN(num)?0:num;
        setElBbox(el, bb2);
        render();
      });
      props.appendChild(l); props.appendChild(inp);
    }
    if(t==='qr'){
      const [l, inp] = inputRow('Tamaño (mm)', el.size_mm||24, (v)=>{ el.size_mm=parseFloat(v||'24'); render(); });
      props.appendChild(l); props.appendChild(inp);
    }

    if(t==='line'){
      for(const [lab, k] of [['X1 (mm)','x1_mm'],['Y1 (mm)','y1_mm'],['X2 (mm)','x2_mm'],['Y2 (mm)','y2_mm']]){
        const [l, inp] = inputRow(lab, el[k]||0, (v)=>{ el[k]=parseFloat(v||'0'); render(); });
        props.appendChild(l); props.appendChild(inp);
      }
      const [ls, ins] = inputRow('Stroke (pt)', el.stroke||1, (v)=>{ el.stroke=parseFloat(v||'1'); render(); }, 'number','0.1');
      props.appendChild(ls); props.appendChild(ins);
      return;
    }

    if(t==='rect'){
      const [ls, ins] = inputRow('Stroke (pt)', el.stroke||1, (v)=>{ el.stroke=parseFloat(v||'1'); render(); }, 'number','0.1');
      props.appendChild(ls); props.appendChild(ins);
      const [lf, sf] = selectRow('Fill', el.fill? '1':'0', [['0','No'],['1','Sí']], (v)=>{ el.fill = (v==='1'); render(); });
      props.appendChild(lf); props.appendChild(sf);
      return;
    }

    if(t==='text'){
      const [lv, ta] = textAreaRow('Texto', el.value||'', (v)=>{ el.value=v; render(); });
      props.appendChild(lv); props.appendChild(ta);

      const [lf, sf] = selectRow('Fuente', el.font||'Helvetica', [['Helvetica','Helvetica'],['Times-Roman','Times-Roman'],['Courier','Courier']], (v)=>{ el.font=v; render(); });
      props.appendChild(lf); props.appendChild(sf);

      const [ls, ins] = inputRow('Tamaño', el.size||10, (v)=>{ el.size=parseFloat(v||'10'); render(); }, 'number','0.5');
      props.appendChild(ls); props.appendChild(ins);

      const [lb, sb] = selectRow('Negrita', el.bold? '1':'0', [['0','No'],['1','Sí']], (v)=>{ el.bold=(v==='1'); render(); });
      props.appendChild(lb); props.appendChild(sb);

      const [la, sa] = selectRow('Alineación', el.align||'left', [['left','Izq'],['center','Centro'],['right','Der']], (v)=>{ el.align=v; render(); });
      props.appendChild(la); props.appendChild(sa);

      const [lw, sw] = selectRow('Wrap', el.wrap? '1':'0', [['0','No'],['1','Sí']], (v)=>{ el.wrap=(v==='1'); render(); });
      props.appendChild(lw); props.appendChild(sw);

      const [laf, saf] = selectRow('Auto-fit', el.autofit? '1':'0', [['0','No'],['1','Sí']], (v)=>{ el.autofit=(v==='1'); render(); });
      props.appendChild(laf); props.appendChild(saf);
      return;
    }

    if(t==='image'){
      const src = (el.src||'').toString();
      let mode = 'custom';
      if(src.startsWith('logo:')) mode = src.split(':')[1] || 'auto';
      if(src.startsWith('upload:')) mode = 'upload';

      const [lm, sm] = selectRow('Logo/Imagen', mode, [
        ['auto','Logo auto (por pedido)'],
        ['luminarias','Logo Iluminarás'],
        ['estilo_home','Logo Estilo Home'],
        ['upload','Subir imagen'],
        ['custom','URL/Path'],
      ], async (v)=>{
        if(v==='upload'){
          // se setea al subir
          el.src = el.src || '';
        } else if(v==='custom'){
          el.src = '';
        } else {
          el.src = `logo:${v}`;
        }
        render();
      });
      props.appendChild(lm); props.appendChild(sm);

      if(mode==='upload'){
        const l = document.createElement('label');
        l.textContent = 'Subir (png/jpg/webp)';
        const fi = document.createElement('input');
        fi.type = 'file';
        fi.accept = '.png,.jpg,.jpeg,.webp';
        fi.addEventListener('change', async ()=>{
          if(!fi.files || !fi.files[0]) return;
          const fd = new FormData();
          fd.append('file', fi.files[0]);
          const r = await fetch(CFG.api.upload, { method:'POST', body: fd });
          const j = await r.json();
          if(j && j.ok){
            el.src = j.src;
            render();
          } else {
            alert('Error subiendo imagen');
          }
        });
        props.appendChild(l); props.appendChild(fi);
      }

      if(mode==='custom'){
        const [lv, ta] = textAreaRow('src (logo:auto | upload:archivo | URL | path)', el.src||'', (v)=>{ el.src=v; render(); });
        props.appendChild(lv); props.appendChild(ta);
      }

      const [lf, sf] = selectRow('Fit', el.fit||'contain', [['contain','Contain'],['cover','Cover'],['fill','Fill']], (v)=>{ el.fit=v; render(); });
      props.appendChild(lf); props.appendChild(sf);
      return;
    }

    if(t==='qr'){
      const [lv, ta] = textAreaRow('Valor (placeholder)', el.value||'{tracking_url}', (v)=>{ el.value=v; render(); });
      props.appendChild(lv); props.appendChild(ta);
      return;
    }
  }

  function addElement(el){
    state.elements.push(el);
    select(el.id);
  }

  addText.addEventListener('click', () => addElement({
    id: uid('text'),
    type: 'text',
    x_mm: 10, y_mm: 10, w_mm: 60, h_mm: 10,
    value: '{nombre}', font:'Helvetica', size:12, bold:false, align:'left', wrap:false, autofit:true,
  }));

  addRect.addEventListener('click', () => addElement({
    id: uid('rect'),
    type: 'rect',
    x_mm: 10, y_mm: 10, w_mm: 60, h_mm: 20,
    stroke: 1,
    fill: false,
  }));

  addLine.addEventListener('click', () => addElement({
    id: uid('line'),
    type: 'line',
    x1_mm: 5, y1_mm: 20, x2_mm: 145, y2_mm: 20,
    stroke: 0.9,
  }));

  addImg.addEventListener('click', () => addElement({
    id: uid('img'),
    type: 'image',
    x_mm: 8, y_mm: 6, w_mm: 50, h_mm: 16,
    src: 'logo:auto',
    fit: 'contain',
  }));

  addQr.addEventListener('click', () => addElement({
    id: uid('qr'),
    type: 'qr',
    x_mm: 60, y_mm: 60, size_mm: 28,
    value: '{tracking_url}',
  }));

  delEl.addEventListener('click', removeSelected);

  canvas.addEventListener('pointerdown', () => {
    state.selectedId = null;
    render();
  });

  window.addEventListener('keydown', (e) => {
    if(e.key === 'Delete' || e.key === 'Backspace'){
      removeSelected();
    }
  });

  saveBtn.addEventListener('click', async () => {
    if(!state.tpl) return;
    state.tpl.page = { width_mm: CFG.width_mm, height_mm: CFG.height_mm };
    state.tpl.elements = state.elements;
    const r = await fetch(CFG.api.templateSet, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.tpl),
    });
    if(r.ok){
      alert('Template guardado');
    } else {
      alert('Error guardando template');
    }
  });

  resetBtn.addEventListener('click', async () => {
    if(!confirm('Resetear al template default?')) return;
    const r = await fetch(CFG.api.templateReset, { method: 'POST' });
    if(!r.ok){
      alert('Error reseteando');
      return;
    }
    await loadTemplate();
    state.selectedId = null;
    render();
  });

  window.addEventListener('resize', () => render());

  (async () => {
    await loadTemplate();
    setCanvasSize();
    render();
  })();
})();
