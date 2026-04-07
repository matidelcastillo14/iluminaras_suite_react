import React, { useState } from 'react';
import api from '../../services/api';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';

/**
 * Página para el módulo de Rastreo.
 *
 * Permite introducir un código de envío y consultar su estado junto con
 * los eventos asociados.  También permite registrar eventos sobre el
 * envío (por ejemplo: recibido en depósito, entregado, etc.).  Esta
 * implementación asume la existencia de endpoints de API dedicados al
 * módulo de rastreo, los cuales deben ser proporcionados por el backend.
 */
const TrackingPage = () => {
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [shipment, setShipment] = useState(null);
  const [events, setEvents] = useState([]);
  const [eventType, setEventType] = useState('');
  const [note, setNote] = useState('');

  // Buscar envío por código
  const handleSearch = async (e) => {
    e.preventDefault();
    if (!code.trim()) return;
    setLoading(true);
    setError('');
    setShipment(null);
    setEvents([]);
    try {
      // Endpoint esperado: /rastreo/api/shipments/<code>
      const res = await api.get(`/rastreo/api/shipments/${encodeURIComponent(code.trim())}`);
      if (res && !res.error) {
        setShipment(res.shipment || {});
        setEvents(res.events || []);
      } else {
        setError(res.detail || res.error || 'Envío no encontrado');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Registrar un evento sobre el envío
  const handleAddEvent = async (e) => {
    e.preventDefault();
    if (!shipment) return;
    if (!eventType) return;
    setLoading(true);
    setError('');
    try {
      // Endpoint esperado: /rastreo/api/shipments/<code>/event
      await api.post(`/rastreo/api/shipments/${encodeURIComponent(code.trim())}/event`, {
        event_type: eventType,
        note: note || undefined,
      });
      // Recargar eventos
      const res = await api.get(`/rastreo/api/shipments/${encodeURIComponent(code.trim())}`);
      if (res && !res.error) {
        setShipment(res.shipment || {});
        setEvents(res.events || []);
        setEventType('');
        setNote('');
      } else {
        setError(res.detail || res.error || 'Error al recargar envío');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>Rastreo</h2>
      <form onSubmit={handleSearch} style={{ marginBottom: '10px' }}>
        <input
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Código de envío o tracking…"
          required
        />
        <button type="submit" disabled={loading} style={{ marginLeft: '5px' }}>
          Buscar
        </button>
      </form>
      {loading && <Loader />}
      <ErrorMessage error={error} />
      {!loading && shipment && (
        <div>
          <h3>Información del envío</h3>
          <pre
            style={{ backgroundColor: '#f8f8f8', padding: '8px', overflowX: 'auto' }}
          >
            {JSON.stringify(shipment, null, 2)}
          </pre>
          <h3>Eventos</h3>
          {events.length > 0 ? (
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {events.map((ev, idx) => (
                <li key={idx} style={{ marginBottom: '4px' }}>
                  {new Date(ev.created_at).toLocaleString()} – {ev.event_type}{' '}
                  {ev.note ? `: ${ev.note}` : ''}
                </li>
              ))}
            </ul>
          ) : (
            <p>No hay eventos registrados.</p>
          )}
          <div style={{ marginTop: '10px' }}>
            <h4>Registrar evento</h4>
            <form onSubmit={handleAddEvent}>
              <select
                value={eventType}
                onChange={(e) => setEventType(e.target.value)}
                required
              >
                <option value="">Seleccione evento…</option>
                <option value="RECEIVED">Recibido</option>
                <option value="DISPATCHED">Despachado</option>
                <option value="DELIVERED">Entregado</option>
                <option value="RETURNED">Devuelto</option>
                {/* Agregar más tipos según sea necesario */}
              </select>
              <input
                type="text"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Nota (opcional)"
                style={{ marginLeft: '5px' }}
              />
              <button type="submit" style={{ marginLeft: '5px' }} disabled={loading}>
                Registrar
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default TrackingPage;
