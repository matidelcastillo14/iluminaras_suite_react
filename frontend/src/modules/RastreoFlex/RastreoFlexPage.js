import React, { useState, useEffect } from 'react';
import api from '../../services/api';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';

/**
 * Página para el módulo de Rastreo Flex (Cadete Flex).
 *
 * Este módulo permite al cadete gestionar su ruta de entregas.  La interfaz
 * está preparada para integrarse con endpoints de API que aún no existen en
 * el backend.  Para cada acción (listar comunidades, iniciar ruta,
 * listar paradas, ver detalles de la parada, registrar eventos) se
 * especifica el endpoint y método esperado.  Cuando estos endpoints
 * estén disponibles, la lógica de llamadas funcionará sin modificar la
 * interfaz.
 */
const RastreoFlexPage = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [communities, setCommunities] = useState([]);
  const [currentRoute, setCurrentRoute] = useState(null);
  const [stops, setStops] = useState([]);
  const [selectedStop, setSelectedStop] = useState(null);
  const [shipments, setShipments] = useState([]);

  // Al montar, intentar obtener la ruta actual
  useEffect(() => {
    const fetchCurrent = async () => {
      setLoading(true);
      setError('');
      try {
        // Endpoint esperado: GET /flex/api/routes/current
        const res = await api.get('/flex/api/routes/current');
        if (res && res.route) {
          setCurrentRoute(res.route);
          setStops(res.stops || []);
        } else {
          // No hay ruta activa: listar comunidades
          const commRes = await api.get('/flex/api/communities');
          setCommunities(commRes.items || []);
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchCurrent();
  }, []);

  // Iniciar ruta para una comunidad seleccionada
  const handleStartRoute = async (commId) => {
    if (!commId) return;
    setLoading(true);
    setError('');
    try {
      // Endpoint esperado: POST /flex/api/routes/start
      const res = await api.post('/flex/api/routes/start', { community_id: commId });
      if (res && res.route) {
        setCurrentRoute(res.route);
        setStops(res.stops || []);
        setCommunities([]);
      } else if (res && res.error) {
        setError(res.detail || res.error || 'No se pudo iniciar la ruta');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Seleccionar parada y cargar sus envíos
  const handleSelectStop = async (stopId) => {
    if (!stopId) return;
    setSelectedStop(null);
    setShipments([]);
    setLoading(true);
    setError('');
    try {
      // Endpoint esperado: GET /flex/api/stops/<stop_id>
      const res = await api.get(`/flex/api/stops/${stopId}`);
      if (res && !res.error) {
        setSelectedStop(res.stop || {});
        setShipments(res.shipments || []);
      } else {
        setError(res.detail || res.error || 'No se pudo cargar la parada');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Registrar entrega o estado para un envío en la parada
  const handleShipmentAction = async (shipmentId, action) => {
    if (!selectedStop || !shipmentId || !action) return;
    setLoading(true);
    setError('');
    try {
      // Endpoint esperado: POST /flex/api/shipments/<shipment_id>/event
      await api.post(`/flex/api/shipments/${shipmentId}/event`, {
        action,
        stop_id: selectedStop.id,
      });
      // Recargar parada
      const res = await api.get(`/cadete_flex/api/stops/${selectedStop.id}`);
      if (res && !res.error) {
        setSelectedStop(res.stop || {});
        setShipments(res.shipments || []);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>Rastreo Flex</h2>
      {loading && <Loader />}
      <ErrorMessage error={error} />
      {/* Si no hay ruta activa y hay comunidades disponibles, mostrar lista de comunidades */}
      {!loading && !currentRoute && communities.length > 0 && (
        <div>
          <p>Seleccione una comunidad para iniciar su ruta:</p>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {communities.map((c) => (
              <li key={c.id} style={{ marginBottom: '4px' }}>
                <button type="button" onClick={() => handleStartRoute(c.id)}>
                  {c.name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {/* Mostrar ruta activa y sus paradas */}
      {!loading && currentRoute && (
        <div style={{ display: 'flex' }}>
          <div style={{ width: '40%', marginRight: '10px' }}>
            <h3>Ruta #{currentRoute.id}</h3>
            <p>Comunidad: {currentRoute.community_name}</p>
            <h4>Paradas</h4>
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {stops.map((s) => (
                <li key={s.id} style={{ marginBottom: '4px' }}>
                  <button type="button" onClick={() => handleSelectStop(s.id)}>
                    #{s.sequence} – {s.address_text} ({s.count})
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div style={{ flex: 1 }}>
            {selectedStop && (
              <div>
                <h3>Parada #{selectedStop.sequence}</h3>
                <p>{selectedStop.address_text}</p>
                <h4>Envíos</h4>
                {shipments.length > 0 ? (
                  <ul style={{ listStyle: 'none', padding: 0 }}>
                    {shipments.map((sh) => (
                      <li key={sh.id} style={{ marginBottom: '4px' }}>
                        <div>
                          <strong>{sh.order_name || sh.id_web || sh.tracking_code}</strong>{' '}
                          – estado: {sh.status}
                        </div>
                        <div>
                          <button
                            type="button"
                            onClick={() => handleShipmentAction(sh.id, 'DELIVERED')}
                          >
                            Entregado
                          </button>
                          <button
                            type="button"
                            onClick={() => handleShipmentAction(sh.id, 'NOT_DELIVERED')}
                            style={{ marginLeft: '5px' }}
                          >
                            No entregado
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No hay envíos en esta parada.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default RastreoFlexPage;
