import React, { useState } from 'react';
import api from '../../services/api';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';

const EVENT_OPTIONS = [
  { value: 'PICKING_STARTED', label: 'Armado iniciado' },
  { value: 'READY_FOR_DISPATCH', label: 'Listo para despacho' },
  { value: 'STOCK_MISSING', label: 'Falta stock' },
  { value: 'RETURNED', label: 'Devuelto a depósito' },
];

const TrackingPage = () => {
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [shipment, setShipment] = useState(null);
  const [events, setEvents] = useState([]);
  const [eventType, setEventType] = useState('');
  const [note, setNote] = useState('');

  const loadShipment = async (rawCode) => {
    const res = await api.get(`/rastreo/api/shipments/${encodeURIComponent(rawCode.trim())}`);
    setShipment(res.shipment || null);
    setEvents(res.events || []);
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!code.trim()) return;
    setLoading(true);
    setError('');
    setShipment(null);
    setEvents([]);
    try {
      await loadShipment(code);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleAddEvent = async (e) => {
    e.preventDefault();
    if (!shipment || !eventType) return;
    setLoading(true);
    setError('');
    try {
      await api.post(`/rastreo/api/shipments/${encodeURIComponent(code.trim())}/event`, {
        event_type: eventType,
        note: note || undefined,
      });
      await loadShipment(code);
      setEventType('');
      setNote('');
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
        <input type="text" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Código de envío o tracking..." required />
        <button type="submit" disabled={loading} style={{ marginLeft: '5px' }}>Buscar</button>
      </form>
      {loading && <Loader />}
      <ErrorMessage error={error} />
      {!loading && shipment && (
        <div>
          <h3>Información del envío</h3>
          <pre style={{ backgroundColor: '#f8f8f8', padding: '8px', overflowX: 'auto' }}>{JSON.stringify(shipment, null, 2)}</pre>
          <h3>Eventos</h3>
          {events.length > 0 ? (
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {events.map((ev) => (
                <li key={ev.id} style={{ marginBottom: '4px' }}>
                  {ev.created_at ? new Date(ev.created_at).toLocaleString() : ''} - {ev.event_type}
                  {ev.note ? `: ${ev.note}` : ''}
                  {ev.created_by ? ` (${ev.created_by})` : ''}
                </li>
              ))}
            </ul>
          ) : (
            <p>No hay eventos registrados.</p>
          )}
          <div style={{ marginTop: '10px' }}>
            <h4>Registrar evento</h4>
            <form onSubmit={handleAddEvent}>
              <select value={eventType} onChange={(e) => setEventType(e.target.value)} required>
                <option value="">Seleccione evento...</option>
                {EVENT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Nota (opcional)" style={{ marginLeft: '5px' }} />
              <button type="submit" style={{ marginLeft: '5px' }} disabled={loading}>Registrar</button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default TrackingPage;
