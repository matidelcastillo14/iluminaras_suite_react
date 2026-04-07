import React, { useState } from 'react';
import api from '../../services/api';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';

/**
 * Página para el módulo de Tracking Administrador (rastreo_ventas).
 *
 * Este módulo está orientado a personal de ventas y administración.  Permite
 * buscar envíos, ver su estado detallado y aplicar acciones como
 * confirmar entrega, marcar devolución o reactivar el envío.  Al igual
 * que otros módulos nuevos, depende de endpoints JSON que aún no están
 * disponibles en el backend; por lo tanto se definen las rutas esperadas
 * y la lógica de manejo para cuando estén disponibles.
 */
const RastreoVentasPage = () => {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError('');
    setResults([]);
    setSelected(null);
    try {
      // Endpoint esperado: GET /rastreo/api/admin/shipments/search?q=...
      const res = await api.get(
        `/rastreo/api/admin/shipments/search?q=${encodeURIComponent(query.trim())}`
      );
      if (Array.isArray(res)) {
        setResults(res);
      } else if (res && res.error) {
        setError(res.detail || res.error || 'Error al buscar envíos');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = async (code) => {
    setLoading(true);
    setError('');
    setSelected(null);
    try {
      // Endpoint esperado: GET /rastreo/api/admin/shipments/<code>
      const res = await api.get(`/rastreo/api/admin/shipments/${encodeURIComponent(code)}`);
      if (res && !res.error) {
        setSelected(res);
      } else {
        setError(res.detail || res.error || 'Envío no encontrado');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Realizar acción sobre envío (override, reset, etc.)
  const handleAction = async (action, payload = {}) => {
    if (!selected) return;
    setLoading(true);
    setError('');
    try {
      // Endpoint esperado: POST /rastreo/api/admin/shipments/<code>/<action>
      await api.post(
        `/rastreo/api/admin/shipments/${encodeURIComponent(selected.code)}/${action}`,
        payload
      );
      // Recargar seleccionado
      const res = await api.get(
        `/rastreo/api/admin/shipments/${encodeURIComponent(selected.code)}`
      );
      if (res && !res.error) {
        setSelected(res);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>Tracking Administrador</h2>
      <form onSubmit={handleSearch} style={{ marginBottom: '10px' }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Código, pedido o ID…"
          required
        />
        <button type="submit" disabled={loading} style={{ marginLeft: '5px' }}>
          Buscar
        </button>
      </form>
      {loading && <Loader />}
      <ErrorMessage error={error} />
      {!loading && results.length > 0 && (
        <div>
          <h3>Resultados</h3>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {results.map((r) => (
              <li key={r.code || r.tracking_code || r.order_name} style={{ marginBottom: '4px' }}>
                <button
                  type="button"
                  onClick={() => handleSelect(r.code || r.tracking_code || r.order_name)}
                >
                  {r.order_name || r.tracking_code || r.code}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {!loading && selected && (
        <div style={{ marginTop: '10px' }}>
          <h3>Detalle del envío</h3>
          <pre
            style={{ backgroundColor: '#f8f8f8', padding: '8px', overflowX: 'auto' }}
          >
            {JSON.stringify(selected, null, 2)}
          </pre>
          <div style={{ marginTop: '10px' }}>
            <button
              type="button"
              onClick={() => handleAction('override', { status: 'DELIVERED' })}
            >
              Marcar como entregado
            </button>
            <button
              type="button"
              onClick={() => handleAction('override', { status: 'RETURNED' })}
              style={{ marginLeft: '5px' }}
            >
              Marcar como devuelto
            </button>
            <button
              type="button"
              onClick={() => handleAction('reset')}
              style={{ marginLeft: '5px' }}
            >
              Reiniciar estado
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default RastreoVentasPage;
