// Minimal API client for Cadete Flex

async function fxJson(url, method, body) {
  const res = await fetch(url, {
    method: method || 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) {
    const errCode = (data && data.error) ? data.error : ('http_' + res.status);
    const e = new Error(errCode);
    e.status = res.status;
    e.data = data;
    throw e;
  }
  return data;
}


async function fxForm(url, formData) {
  const res = await fetch(url, {
    method: 'POST',
    body: formData,
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) {
    const errCode = (data && data.error) ? data.error : ('http_' + res.status);
    const e = new Error(errCode);
    e.status = res.status;
    e.data = data;
    throw e;
  }
  return data;
}


window.FlexApi = {
  cartList: (communityId) => fxJson(`/flex/api/cart${communityId ? ('?community_id=' + communityId) : ''}`, 'GET'),
  cartScan: (raw, source, communityId) => fxJson('/flex/api/cart/scan', 'POST', { raw_code: raw, source: source || 'camera', community_id: communityId || null }),
  cartRemove: (shipmentId) => fxJson('/flex/api/cart/remove', 'POST', { shipment_id: shipmentId }),
  routeStart: (communityId) => fxJson('/flex/api/route/start', 'POST', { community_id: communityId || null }),
  routeBegin: (routeId) => fxJson('/flex/api/route/begin', 'POST', { route_id: routeId }),
  routeActive: () => fxJson('/flex/api/route/active', 'GET'),
  routeActiveItems: () => fxJson('/flex/api/route/active/items', 'GET'),
  // Agregar a la ruta activa por escaneo
  routeScanAdd: (raw, source) => fxJson('/flex/api/route/active/scan', 'POST', { raw_code: raw, source: source || 'camera' }),
  routeOptimize: (routeId, startLat, startLng) => fxJson('/flex/api/route/optimize', 'POST', { route_id: routeId, start_lat: startLat, start_lng: startLng }),
  stopArriving: (stopId) => fxJson('/flex/api/stop/arriving', 'POST', { stop_id: stopId }),
  shipmentAction: (formData) => fxForm('/flex/api/shipment/action', formData),
  routeFinish: (routeId) => fxJson('/flex/api/route/finish', 'POST', { route_id: routeId }),
};
