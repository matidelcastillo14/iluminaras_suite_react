import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { buildApiUrl, downloadFile } from '../../services/api';
import { getRecentCfes, pollCfesNow } from '../../services/cfeAuto';

const STATUS_LABELS = {
  ok: 'OK',
  error: 'Error',
  processing: 'Procesando',
  pending: 'Pendiente',
};

const fmtDate = (value) => {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
};

const buttonStyle = {
  padding: '8px 14px',
  borderRadius: '999px',
  border: '1px solid #2563eb',
  background: '#fff',
  color: '#2563eb',
  cursor: 'pointer',
};

const mutedButtonStyle = {
  ...buttonStyle,
  border: '1px solid #d0d7de',
  color: '#334155',
};

const CfeAutoPage = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState('');
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');

  const fetchItems = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const res = await getRecentCfes();
      const rows = Array.isArray(res?.items) ? res.items : [];
      setItems(rows);
      setUpdatedAt(new Date().toISOString());
      setError('');
    } catch (err) {
      setError(err?.message || 'No se pudieron cargar los CFEs');
      if (!silent) setItems([]);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      fetchItems({ silent: true });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [fetchItems]);

  const handlePoll = async () => {
    setPolling(true);
    setError('');
    try {
      await pollCfesNow();
      await fetchItems();
    } catch (err) {
      setError(err?.message || 'No se pudo actualizar ahora');
    } finally {
      setPolling(false);
    }
  };

  const filteredItems = useMemo(() => {
    const term = query.trim().toLowerCase();
    return items.filter((item) => {
      const matchStatus = filter === 'all' || (item.status || '').toLowerCase() === filter;
      const haystack = [
        item.fecha,
        item.tipo,
        item.serie,
        item.numero,
        item.cfe,
        item.receptor,
        item.last_error,
      ].join(' ').toLowerCase();
      const matchQuery = !term || haystack.includes(term);
      return matchStatus && matchQuery;
    });
  }, [items, filter, query]);

  const openPdf = (url) => {
    if (!url) return;
    window.open(buildApiUrl(url), '_blank', 'noopener,noreferrer');
  };

  const onDownload = async (url, filename) => {
    if (!url) return;
    await downloadFile(url, filename);
  };

  return (
    <div style={{ padding: '20px 24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, marginBottom: 18, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 28 }}>CFEs recientes</h1>
          <div style={{ marginTop: 6, color: '#475569' }}>
            Actualiza cada 5s · muestra últimos {items.length || 0}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <button type="button" onClick={handlePoll} disabled={loading || polling} style={buttonStyle}>
            {polling ? 'Actualizando...' : 'Actualizar ahora'}
          </button>
          <div style={{ color: '#64748b' }}>Actualizado: {fmtDate(updatedAt)}</div>
        </div>
      </div>

      <div style={{ border: '1px solid #e5e7eb', borderRadius: 18, padding: 18, background: '#fff' }}>
        <p style={{ marginTop: 0, color: '#475569' }}>
          Click en <strong>Abrir</strong> para abrir el PDF en una pestaña nueva, o en <strong>Descargar</strong> para bajarlo directo.
        </p>

        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar por receptor, número, error..."
            style={{ minWidth: 280, padding: '10px 12px', borderRadius: 10, border: '1px solid #d0d7de' }}
          />
          <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid #d0d7de' }}>
            <option value="all">Todos los estados</option>
            <option value="ok">OK</option>
            <option value="error">Error</option>
            <option value="processing">Procesando</option>
            <option value="pending">Pendiente</option>
          </select>
        </div>

        {error ? <div style={{ marginBottom: 12, color: '#b91c1c' }}>{error}</div> : null}
        {loading ? <div>Cargando...</div> : null}

        {!loading && (
          <div style={{ overflowX: 'auto', maxHeight: '70vh' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>
                  <th style={{ padding: '12px 10px' }}>Fecha</th>
                  <th style={{ padding: '12px 10px' }}>Tipo</th>
                  <th style={{ padding: '12px 10px' }}>Serie</th>
                  <th style={{ padding: '12px 10px' }}>Número</th>
                  <th style={{ padding: '12px 10px' }}>Receptor</th>
                  <th style={{ padding: '12px 10px' }}>CFE</th>
                  <th style={{ padding: '12px 10px' }}>Cambio</th>
                  <th style={{ padding: '12px 10px' }}>Estado</th>
                  <th style={{ padding: '12px 10px' }}>Origen</th>
                  <th style={{ padding: '12px 10px' }}>Error</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item) => {
                  const receiptName = `cfe_${item.serie || ''}${item.numero || item.source_id || ''}.pdf`;
                  const changeName = `cambio_${item.serie || ''}${item.numero || item.source_id || ''}.pdf`;
                  return (
                    <tr key={`${item.source_type}-${item.source_id}`} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td style={{ padding: '12px 10px', whiteSpace: 'nowrap' }}>{item.fecha || fmtDate(item.updated_at)}</td>
                      <td style={{ padding: '12px 10px' }}>{item.tipo || '-'}</td>
                      <td style={{ padding: '12px 10px' }}>{item.serie || '-'}</td>
                      <td style={{ padding: '12px 10px' }}>{item.numero || '-'}</td>
                      <td style={{ padding: '12px 10px' }}>{item.receptor || '-'}</td>
                      <td style={{ padding: '12px 10px', whiteSpace: 'nowrap' }}>
                        {item.pdf_url ? (
                          <div style={{ display: 'flex', gap: 8 }}>
                            <button type="button" style={buttonStyle} onClick={() => openPdf(item.pdf_url)}>Abrir</button>
                            <button type="button" style={mutedButtonStyle} onClick={() => onDownload(item.download_pdf_url || item.pdf_url, receiptName)}>Descargar</button>
                          </div>
                        ) : '-'}
                      </td>
                      <td style={{ padding: '12px 10px', whiteSpace: 'nowrap' }}>
                        {item.change_pdf_url ? (
                          <div style={{ display: 'flex', gap: 8 }}>
                            <button type="button" style={buttonStyle} onClick={() => openPdf(item.change_pdf_url)}>Abrir</button>
                            <button type="button" style={mutedButtonStyle} onClick={() => onDownload(item.download_change_pdf_url || item.change_pdf_url, changeName)}>Descargar</button>
                          </div>
                        ) : '-'}
                      </td>
                      <td style={{ padding: '12px 10px' }}>{STATUS_LABELS[item.status] || item.status || '-'}</td>
                      <td style={{ padding: '12px 10px' }}>{item.source_type || '-'} / {item.source_id || '-'}</td>
                      <td style={{ padding: '12px 10px', color: item.last_error ? '#b91c1c' : '#64748b' }}>{item.last_error || '-'}</td>
                    </tr>
                  );
                })}
                {!filteredItems.length ? (
                  <tr>
                    <td colSpan={10} style={{ padding: '16px 10px', color: '#64748b' }}>No hay CFEs para mostrar.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default CfeAutoPage;
