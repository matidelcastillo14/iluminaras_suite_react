import React, { useState } from 'react';
import api from '../../services/api';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';

const RastreoVentasPage = () => {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [note, setNote] = useState('');
  const [overrideStatus, setOverrideStatus] = useState('DELIVERED');

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError('');
    setResults([]);
    setSelected(null);
    try {
      const res = await api.get(`/rastreo/api/admin/shipments/search?q=${encodeURIComponent(query.trim())}`);
      setResults(res.items || []);
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
      const res = await api.get(`/rastreo/api/admin/shipments/${encodeURIComponent(code)}`);
      setSelected(res);
      setNote('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const reloadSelected = async (code) => {
    const res = await api.get(`/rastreo/api/admin/shipments/${encodeURIComponent(code)}`);
    setSelected(res);
  };

  const handleOverride = async () => {
    if (!selected?.code) return;
    setLoading(true);
    setError('');
    try {
      await api.post(`/rastreo/api/admin/shipments/${encodeURIComponent(selected.code)}/override`, {
        new_status: overrideStatus,
        note,
      });
      await reloadSelected(selected.code);
      setNote('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    if (!selected?.code) return;
    setLoading(true);
    setError('');
    try {
      await api.post(`/rastreo/api/admin/shipments/${encodeURIComponent(selected.code)}/reset`, { note });
      await reloadSelected(selected.code);
      setNote('');
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
        <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Código, pedido o ID..." required />
        <button type="submit" disabled={loading} style={{ marginLeft: '5px' }}>Buscar</button>
      </form>
      {loading && <Loader />}
      <ErrorMessage error={error} />
      {!loading && results.length > 0 && (
        <div>
          <h3>Resultados</h3>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {results.map((r) => (
              <li key={r.code} style={{ marginBottom: '4px' }}>
                <button type="button" onClick={() => handleSelect(r.code)}>
                  {r.order_name || r.id_web || r.code} - {r.status}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {!loading && selected && (
        <div style={{ marginTop: '10px' }}>
          <h3>Detalle del envío</h3>
          <pre style={{ backgroundColor: '#f8f8f8', padding: '8px', overflowX: 'auto' }}>{JSON.stringify(selected, null, 2)}</pre>
          <div style={{ marginTop: '10px' }}>
            <select value={overrideStatus} onChange={(e) => setOverrideStatus(e.target.value)}>
              {(selected.override_statuses || []).map((st) => (
                <option key={st} value={st}>{st}</option>
              ))}
            </select>
            <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Nota (opcional)" style={{ marginLeft: '5px' }} />
            <button type="button" onClick={handleOverride} style={{ marginLeft: '5px' }}>Override</button>
            <button type="button" onClick={handleReset} style={{ marginLeft: '5px' }}>Reset</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default RastreoVentasPage;
