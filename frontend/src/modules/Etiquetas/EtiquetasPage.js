import React, { useState } from 'react';
import api, { API_BASE_URL } from '../../services/api';

/**
 * Página para interactuar con el módulo de etiquetas vía API.
 * Permite buscar pedidos, ver detalles y generar etiquetas de envío.
 */
const EtiquetasPage = () => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Buscar pedidos en Odoo
  const handleSearch = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.get(`/etiquetas/api/orders/search?q=${encodeURIComponent(query)}`);
      if (Array.isArray(res)) {
        setResults(res);
      } else if (res && res.error) {
        setResults([]);
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

  // Obtener detalle de un pedido seleccionado
  const handleSelect = async (orderId) => {
    setError('');
    setLoading(true);
    try {
      const res = await api.get(`/etiquetas/api/orders/${orderId}`);
      if (res && !res.error) {
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

  // Generar PDF de etiqueta para el pedido seleccionado
  const handleGenerate = async () => {
    if (!selected?.id) return;
    setError('');
    setLoading(true);
    try {
      const form = new FormData();
      form.append('order_id', selected.id);
      const res = await api.post('/etiquetas/generate', form);
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
              <li
                key={order.id || order.pedido || order.name}
                style={{ marginBottom: '5px' }}
              >
                <button
                  type="button"
                  onClick={() => handleSelect(order.id || order.pedido || order.name)}
                >
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
              <pre
                style={{
                  backgroundColor: '#f8f8f8',
                  padding: '8px',
                  overflowX: 'auto',
                }}
              >
                {JSON.stringify(selected, null, 2)}
              </pre>
              <button
                type="button"
                onClick={handleGenerate}
                disabled={loading || !selected?.id}
              >
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
