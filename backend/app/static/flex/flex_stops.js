(function(){
  const routeId = window.FLEX_ROUTE_ID;
  const btnFinish = document.getElementById('btnFinish');
  const btnOptimize = document.getElementById('btnOptimize');
  const dlgFinish = document.getElementById('dlgFinishBlocked');
  const finishDlgBody = document.getElementById('finishDlgBody');
  const finishDlgList = document.getElementById('finishDlgList');
  const finishDlgErr = document.getElementById('finishDlgErr');
  const btnApplyFinish = document.getElementById('btnApplyFinish');
  const lnkGoogle = document.getElementById('lnkGoogle');
  const lnkWaze = document.getElementById('lnkWaze');
  const optMsg = document.getElementById('optMsg');

  const stops = Array.isArray(window.FLEX_STOPS) ? window.FLEX_STOPS.slice() : [];

  function setMsg(msg){
    if(!optMsg) return;
    optMsg.textContent = msg || '';
  }


  function showFinishErr(msg){
    if(!finishDlgErr) return;
    finishDlgErr.style.display = 'block';
    finishDlgErr.textContent = msg || '';
  }
  function hideFinishErr(){
    if(!finishDlgErr) return;
    finishDlgErr.style.display = 'none';
    finishDlgErr.textContent = '';
  }

  function clearFinishList(){
    if(finishDlgList) finishDlgList.innerHTML = '';
  }

  function el(tag, attrs, text){
    const d = document.createElement(tag);
    if(attrs){
      Object.entries(attrs).forEach(([k,v])=>{ if(v!=null) d.setAttribute(k,v); });
    }
    if(text!=null) d.textContent = text;
    return d;
  }

  function renderFinishBlocked(data){
    hideFinishErr();
    clearFinishList();
    if(!dlgFinish) return;

    const pendingShipments = (data && data.pending_shipments) ? data.pending_shipments : [];
    const pendingDecisions = (data && data.pending_decisions) ? data.pending_decisions : [];
    const receivers = (data && data.depot_receivers) ? data.depot_receivers : [];

    if(pendingShipments.length){
      if(finishDlgBody) finishDlgBody.textContent = 'Hay pedidos todavía en reparto. Marcá entregado / no entregado antes de finalizar.';
      pendingShipments.forEach(it=>{
        const row = el('div', {'class':'fx-card', 'style':'margin:8px 0; padding:10px;'});
        row.appendChild(el('div', {'style':'font-weight:600;'}, (it.id_web || it.order_name || it.tracking_code || ('#'+it.shipment_id))));
        row.appendChild(el('div', {'class':'fx-muted'}, (it.address_text || '')));
        finishDlgList.appendChild(row);
      });
      dlgFinish.showModal();
      return;
    }

    if(finishDlgBody) finishDlgBody.textContent = 'Tenés pedidos NO ENTREGADOS. Elegí qué hacer con cada uno para poder finalizar:';
    pendingDecisions.forEach(it=>{
      const row = el('div', {'class':'fx-card', 'style':'margin:8px 0; padding:10px;'});
      row.dataset.shipmentId = it.shipment_id;
      row.dataset.stopId = it.stop_id || '';
      row.appendChild(el('div', {'style':'font-weight:600;'}, (it.id_web || it.order_name || it.tracking_code || ('#'+it.shipment_id))));
      row.appendChild(el('div', {'class':'fx-muted', 'style':'margin-bottom:6px;'}, (it.address_text || '')));

      const sel = el('select', {'class':'fx-input'});
      sel.appendChild(el('option', {value:''}, 'Seleccionar acción…'));
      sel.appendChild(el('option', {value:'RETRY'}, 'Reintentar entrega'));
      sel.appendChild(el('option', {value:'NEXT_SHIFT'}, 'Dejar para siguiente turno'));
      sel.appendChild(el('option', {value:'RETURN_DEPOT'}, 'Devolver a depósito'));
      row.appendChild(sel);

      const recWrap = el('div', {'style':'display:none; margin-top:8px;'});
      const recSel = el('select', {'class':'fx-input'});
      recSel.appendChild(el('option', {value:''}, 'Seleccionar usuario de depósito…'));
      receivers.forEach(u=>{
        recSel.appendChild(el('option', {value: u.id}, u.label + (u.role ? (' ('+u.role+')') : '')));
      });
      recWrap.appendChild(el('div', {'style':'font-size:12px; margin-bottom:4px;'}, 'Entregado a:'));
      recWrap.appendChild(recSel);
      row.appendChild(recWrap);

      sel.addEventListener('change', ()=>{
        if(sel.value === 'RETURN_DEPOT'){
          recWrap.style.display = 'block';
        }else{
          recWrap.style.display = 'none';
          recSel.value = '';
        }
      });

      finishDlgList.appendChild(row);
    });

    dlgFinish.showModal();

    if(btnApplyFinish){
      btnApplyFinish.onclick = async (ev)=>{
        ev.preventDefault();
        hideFinishErr();
        btnApplyFinish.disabled = true;
        try{
          const rows = Array.from(finishDlgList.querySelectorAll('[data-shipment-id]'));
          for(const row of rows){
            const shipmentId = row.dataset.shipmentId;
            const stopId = row.dataset.stopId;
            const actionSel = row.querySelector('select');
            const actionVal = actionSel ? actionSel.value : '';
            if(!actionVal){
              throw new Error('Faltan acciones por seleccionar.');
            }
            const fd = new FormData();
            fd.append('shipment_id', shipmentId);
            if(stopId) fd.append('stop_id', stopId);

            if(actionVal === 'RETRY'){
              fd.append('action', 'OUT_FOR_DELIVERY');
              fd.append('note', 'Reintentar entrega (fin de ruta)');
            }else if(actionVal === 'NEXT_SHIFT'){
              fd.append('action', 'DEFERRED_NEXT_SHIFT');
              fd.append('note', 'Pendiente para siguiente turno (fin de ruta)');
            }else if(actionVal === 'RETURN_DEPOT'){
              const recSel = row.querySelector('div select');
              const recId = recSel ? recSel.value : '';
              if(!recId){
                throw new Error('Tenés que seleccionar el usuario de depósito para la devolución.');
              }
              fd.append('action', 'RETURN_TO_DEPOT_REQUESTED');
              fd.append('return_to_user_id', recId);
              fd.append('note', 'Devuelto a depósito (fin de ruta)');
            }else{
              throw new Error('Acción inválida.');
            }

            await window.FlexApi.shipmentAction(fd);
          }

          // intentar finalizar nuevamente
          await window.FlexApi.routeFinish(routeId);
          window.location.href = '/flex';
        }catch(e){
          showFinishErr(e.message);
        }finally{
          btnApplyFinish.disabled = false;
        }
      };
    }
  }

  function haversineKm(aLat, aLng, bLat, bLng){
    const R = 6371;
    const toRad = (d) => (d * Math.PI / 180);
    const dLat = toRad(bLat - aLat);
    const dLng = toRad(bLng - aLng);
    const sa = Math.sin(dLat/2) ** 2 + Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * (Math.sin(dLng/2) ** 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(sa)));
  }

  function orderGreedy(origin, pts){
    // pts: [{id, lat, lng, ...}]
    const remaining = pts.slice();
    const ordered = [];
    let cur = {lat: origin.lat, lng: origin.lng};
    while(remaining.length){
      let bestIdx = 0;
      let bestD = Infinity;
      for(let i=0;i<remaining.length;i++){
        const p = remaining[i];
        const d = haversineKm(cur.lat, cur.lng, p.lat, p.lng);
        if(d < bestD){
          bestD = d;
          bestIdx = i;
        }
      }
      const next = remaining.splice(bestIdx, 1)[0];
      ordered.push(next);
      cur = {lat: next.lat, lng: next.lng};
    }
    return ordered;
  }

  function googleMapsUrl(origin, orderedStops){
    // Usa coords si hay; si no, usa address_text.
    const enc = encodeURIComponent;
    const parts = orderedStops.map(s => (s.lat != null && s.lng != null) ? `${s.lat},${s.lng}` : (s.address_text || ''));
    if(parts.length === 0) return 'https://www.google.com/maps';
    const destination = parts[parts.length - 1];
    const waypoints = parts.slice(0, -1).filter(Boolean).join('|');
    const params = [];
    params.push('api=1');
    if(origin && origin.lat != null && origin.lng != null){
      params.push('origin=' + enc(`${origin.lat},${origin.lng}`));
    }
    params.push('destination=' + enc(destination));
    if(waypoints){
      params.push('waypoints=' + enc(waypoints));
    }
    params.push('travelmode=driving');
    return 'https://www.google.com/maps/dir/?' + params.join('&');
  }

  function wazeUrl(firstStop){
    if(!firstStop) return 'https://waze.com/';
    if(firstStop.lat != null && firstStop.lng != null){
      return `https://waze.com/ul?ll=${encodeURIComponent(firstStop.lat + ',' + firstStop.lng)}&navigate=yes`;
    }
    // sin coords: usar búsqueda de Waze (abre app si está instalada)
    return 'https://waze.com/ul?q=' + encodeURIComponent(firstStop.address_text || '') + '&navigate=yes';
  }

  function updateLinks(origin, orderedStops){
    const ord = orderedStops && orderedStops.length ? orderedStops : stops.slice().sort((a,b) => (a.sequence||0)-(b.sequence||0));
    if(lnkGoogle) lnkGoogle.href = googleMapsUrl(origin, ord);
    if(lnkWaze) lnkWaze.href = wazeUrl(ord[0]);
  }

  // Inicial (sin geoloc)
  updateLinks(null, null);

  document.querySelectorAll('button.arriving').forEach(btn => {
    btn.addEventListener('click', async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const sid = btn.getAttribute('data-stop-id');
      try{
        await window.FlexApi.stopArriving(parseInt(sid,10));
        btn.textContent = 'Listo';
        btn.disabled = true;
        btn.classList.add('ghost');
      }catch(e){
        alert('No se pudo marcar llegando: ' + e.message);
      }
    });
  });

    btnFinish.addEventListener('click', async (ev) => {
    ev.preventDefault();
    if(!confirm('¿Finalizar ruta?')) return;
    try{
      await window.FlexApi.routeFinish(routeId);
      window.location.href = '/flex';
    }catch(e){
      if(e && e.status === 409 && e.data){
        renderFinishBlocked(e.data);
        return;
      }
      alert('No se pudo finalizar: ' + e.message);
    }
  });

  async function optimizeWithOrigin(origin){
    const withCoords = stops.filter(s => s.lat != null && s.lng != null);
    const noCoords = stops.filter(s => s.lat == null || s.lng == null).sort((a,b) => (a.sequence||0)-(b.sequence||0));

    if(withCoords.length < 2){
      setMsg(withCoords.length ? 'Solo hay una parada con coordenadas; no se reordena.' : 'No hay coordenadas; no se puede ordenar por distancia.');
      updateLinks(origin, stops.slice().sort((a,b)=>(a.sequence||0)-(b.sequence||0)));
      return;
    }
    const ordered = orderGreedy(origin, withCoords).concat(noCoords);
    const ids = ordered.map(s => s.id);
    setMsg('Reordenando ruta…');
    await window.FlexApi.routeReorder(routeId, ids);
    setMsg('Ruta reordenada.');
    updateLinks(origin, ordered);
    // recargar para reflejar nuevo orden
    window.location.reload();
  }

  if(btnOptimize){
    btnOptimize.addEventListener('click', async (ev) => {
      ev.preventDefault();
      setMsg('');
      if(!navigator.geolocation){
        setMsg('El navegador no soporta geolocalización.');
        return;
      }
      btnOptimize.disabled = true;
      setMsg('Obteniendo tu ubicación…');
      navigator.geolocation.getCurrentPosition(async (pos) => {
        try{
          const origin = {lat: pos.coords.latitude, lng: pos.coords.longitude};
          await optimizeWithOrigin(origin);
        }catch(e){
          setMsg('No se pudo reordenar: ' + e.message);
        }finally{
          btnOptimize.disabled = false;
        }
      }, (err) => {
        setMsg('No se pudo obtener ubicación: ' + (err && err.message ? err.message : 'error'));
        btnOptimize.disabled = false;
      }, { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 });
    });
  }

  // si el usuario solo quiere abrir Google/Waze, intentar mejorar links con geoloc al click (sin reordenar DB)
  function attachGeoImproveLink(el){
    if(!el) return;
    el.addEventListener('click', (ev) => {
      if(!navigator.geolocation) return;
      navigator.geolocation.getCurrentPosition((pos)=>{
        const origin = {lat: pos.coords.latitude, lng: pos.coords.longitude};
        updateLinks(origin, null);
      }, ()=>{}, { enableHighAccuracy: false, timeout: 3000, maximumAge: 60000 });
    }, {capture:true});
  }
  attachGeoImproveLink(lnkGoogle);
  attachGeoImproveLink(lnkWaze);

})();