(function(){
  const stops = Array.isArray(window.FLEX_STOPS) ? window.FLEX_STOPS.slice() : [];
  const mapEl = document.getElementById('map');
  const sheet = document.getElementById('mapSheet');
  const msTitle = document.getElementById('msTitle');
  const msNav = document.getElementById('msNav');
  const msOpen = document.getElementById('msOpen');
  const lnkGoogle = document.getElementById('lnkGoogle');
  const lnkWaze = document.getElementById('lnkWaze');

  function navUrlForStop(s){
    if(s.lat != null && s.lng != null){
      return `https://www.google.com/maps?q=${encodeURIComponent(s.lat + ',' + s.lng)}`;
    }
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(s.address_text || '')}`;
  }

  function openStopUrl(s){
    return `/flex/stops/${s.id}`;
  }

  function showStop(s){
    msTitle.textContent = s.address_text || ('Parada ' + s.sequence);
    msNav.href = navUrlForStop(s);
    msOpen.href = openStopUrl(s);
    sheet.hidden = false;
  }

  function googleMapsUrl(origin, orderedStops){
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
    return 'https://waze.com/ul?q=' + encodeURIComponent(firstStop.address_text || '') + '&navigate=yes';
  }

  function updateLinks(origin){
    const orderedStops = stops.slice().sort((a,b) => (a.sequence||0)-(b.sequence||0));
    if(lnkGoogle) lnkGoogle.href = googleMapsUrl(origin, orderedStops);
    if(lnkWaze) lnkWaze.href = wazeUrl(orderedStops[0]);
  }

  updateLinks(null);

  function attachGeoImproveLink(el){
    if(!el) return;
    el.addEventListener('click', () => {
      if(!navigator.geolocation) return;
      navigator.geolocation.getCurrentPosition((pos)=>{
        updateLinks({lat: pos.coords.latitude, lng: pos.coords.longitude});
      }, ()=>{}, {timeout: 2500, maximumAge: 60000});
    }, {capture:true});
  }
  attachGeoImproveLink(lnkGoogle);
  attachGeoImproveLink(lnkWaze);

  const hasCoords = stops.some(s => (s.lat != null && s.lng != null));
  if(!hasCoords){
    mapEl.innerHTML = '';
    mapEl.style.background = '#fff';
    mapEl.style.display = 'flex';
    mapEl.style.flexDirection = 'column';
    mapEl.style.padding = '12px';
    mapEl.style.gap = '10px';
    const h = document.createElement('div');
    h.className = 'fx-big';
    h.textContent = 'Sin coordenadas';
    mapEl.appendChild(h);
    const p = document.createElement('div');
    p.className = 'fx-muted';
    p.textContent = 'Se puede navegar usando Google Maps por dirección.';
    mapEl.appendChild(p);
    stops.slice().sort((a,b)=>(a.sequence||0)-(b.sequence||0)).forEach(s => {
      const row = document.createElement('a');
      row.className = 'fx-stop';
      row.href = openStopUrl(s);
      row.innerHTML = `<div class="fx-stop-main"><div class="fx-stop-addr">${s.address_text || ''}</div><div class="fx-muted">Parada ${s.sequence}</div></div><div class="fx-stop-actions"><span class="fx-pill">Abrir</span></div>`;
      mapEl.appendChild(row);
    });
    return;
  }

  const map = L.map('map', { zoomControl: true });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap',
  }).addTo(map);

  const bounds = [];
  const ordered = stops.slice().sort((a,b) => (a.sequence||0)-(b.sequence||0));

  // Markers + polyline points
  const linePts = [];
  ordered.forEach(s => {
    if(s.lat == null || s.lng == null) return;
    const m = L.marker([s.lat, s.lng]).addTo(map);
    m.on('click', () => showStop(s));
    bounds.push([s.lat, s.lng]);
    linePts.push([s.lat, s.lng]);
  });

  if(linePts.length >= 2){
    L.polyline(linePts).addTo(map);
  }

  if(bounds.length){
    map.fitBounds(bounds, { padding: [24,24] });
  }else{
    map.setView([0,0], 2);
  }
})();