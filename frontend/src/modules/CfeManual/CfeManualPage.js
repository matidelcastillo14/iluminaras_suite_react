import React, { useState } from 'react';
import api, { API_BASE_URL } from '../../services/api';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';

/**
 * Página para el módulo CFE Manual.
 *
 * Permite buscar pedidos a través del API de CFE manual, ver el detalle del
 * pedido y generar un ticket PDF y el ticket de cambio.  El flujo es
 * similar al módulo de etiquetas pero con endpoints distintos.
 */
const CfeManualPage = () => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Buscar pedidos
  const handleSearch = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.get(`/cfe/manual/api/orders/search?q=${encodeURIComponent(query)}`);
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

  // Seleccionar pedido y obtener detalle
  const handleSelect = async (orderId) => {
    setError('');
    setLoading(true);
    try {
      const res = await api.get(`/cfe/manual/api/orders/${orderId}`);
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

  // Generar ticket PDF y de cambio para el pedido seleccionado
  const handleGenerate = async () => {
    if (!selected?.id) return;
    setError('');
    setLoading(true);
    try {
      const form = new FormData();
      form.append('order_id', selected.id);
      const res = await api.post('/cfe/manual/generate', form);
      if (res && res.pdf_url) {
        const receiptUrl = `${API_BASE_URL}${res.pdf_url}`;
        window.open(receiptUrl, '_blank');
      }
      if (res && res.change_pdf_url) {
        const changeUrl = `${API_BASE_URL}${res.change_pdf_url}`;
        window.open(changeUrl, '_blank');
      }
      if (!res || (!res.pdf_url && !res.change_pdf_url)) {
        setError('No se pudo generar el ticket');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>CFE Manual</h2>
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
      {loading && <Loader />}
      <ErrorMessage error={error} />
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
                Generar ticket
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CfeManualPage;
