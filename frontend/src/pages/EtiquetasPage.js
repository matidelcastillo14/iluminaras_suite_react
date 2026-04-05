import React, { useState } from 'react';
import api, { API_BASE_URL } from '../services/api';

/**
 * Page to interact with the etiquetas module via API.
 * Allows searching for orders, viewing details and generating shipping labels.
 */
const EtiquetasPage = () => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Search for orders in Odoo
  const handleSearch = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.get(`/etiquetas/api/orders/search?q=${encodeURIComponent(query)}`);
      // The etiquetas search API returns an array on success.  If a JSON
      // object with an error property is returned (for example when the
      // backend encounters an Odoo error), surface the message to the user.
      if (Array.isArray(res)) {
        setResults(res);
      } else if (res && res.error) {
        setResults([]);
        // Show a generic error if no detail is provided.
        setError(res.detail || res.error || 'Error al buscar');
      } else {
        setResults([]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Fetch details for selected order
  const handleSelect = async (orderId) => {
    setError('');
    setLoading(true);
    try {
      const res = await api.get(`/etiquetas/api/orders/${orderId}`);
      // The order detail API returns an object describing the order.  If an
      // error object is returned, show the message instead of trying to
      // display the details.
      if (res && !res.error) {
        // Add id field to selected to pass to generate
        setSelected({ id: orderId, ...res });
      } else {
        setSelected(null);
        setError(res.detail || res.error || 'Pedido no encontrado');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Generate PDF label for selected order
  const handleGenerate = async () => {
    if (!selected?.id) return;
    setError('');
    setLoading(true);
    try {
      const form = new FormData();
      form.append('order_id', selected.id);
      const res = await api.post('/etiquetas/generate', form);
      // The generate endpoint returns an object with ok and pdf_url on
      // success.  Construct the full URL using the API base so that the
      // React app can run against non‑localhost backends.  Always check
      // pdf_url before opening to avoid opening undefined.
      if (res && res.pdf_url) {
        const url = `${API_BASE_URL}${res.pdf_url}`;
        window.open(url, '_blank');
      } else {
        setError('No se pudo generar la etiqueta');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>Etiquetas</h2>
      <form onSubmit={handleSearch} style={{ marginBottom: '10px' }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar pedido…"
          required
        />
        <button type="submit" disabled={loading} style={{ marginLeft: '5px' }}>
          Buscar
        </button>
      </form>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {loading && <p>Procesando…</p>}
      <div style={{ display: 'flex', marginTop: '10px' }}>
        <div style={{ width: '40%', marginRight: '10px' }}>
          <h3>Resultados</h3>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {results.map((order) => (
              <li key={order.id || order.pedido || order.name} style={{ marginBottom: '5px' }}>
                <button type="button" onClick={() => handleSelect(order.id || order.pedido || order.name)}>
                  {order.name || order.pedido || order.pedido_name || order.id}
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div style={{ flex: 1 }}>
          {selected && (
            <div>
              <h3>Detalle del pedido</h3>
              <pre style={{ backgroundColor: '#f8f8f8', padding: '8px', overflowX: 'auto' }}>
                {JSON.stringify(selected, null, 2)}
              </pre>
              <button type="button" onClick={handleGenerate} disabled={loading || !selected?.id}>
                Generar etiqueta PDF
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default EtiquetasPage;