import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../../services/api';
import { getCfes, pollNow } from '../../services/cfeAuto';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import Table from '../../components/Table';

const CfeAutoPage = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchItems = async () => {
    setLoading(true);
    setError('');

    try {
      const res = await getCfes();
      setItems(Array.isArray(res) ? res : []);
    } catch (err) {
      setItems([]);
      setError(err.message || 'No se pudieron obtener CFEs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();
  }, []);

  const handlePoll = async () => {
    setLoading(true);
    setError('');

    try {
      await pollNow();
      await fetchItems();
    } catch (err) {
      setError(err.message || 'No se pudo ejecutar el poll manual');
      setLoading(false);
    }
  };

  const handleOpenPdf = (relUrl) => {
    if (!relUrl) return;
    window.open(`${API_BASE_URL}${relUrl}`, '_blank', 'noopener,noreferrer');
  };

  const tableHeaders = [
    'Fuente',
    'ID Fuente',
    'Estado',
    'Intentos',
    'Último error',
    'CFE',
    'Receptor',
    'Recibo',
    'Cambio',
    'Actualizado',
  ];

  const tableRows = items.map((it) => [
    it.source_type || '',
    it.source_id || '',
    it.status || '',
    it.attempts ?? '',
    it.last_error || '',
    it.cfe || '',
    it.receptor || '',
    it.pdf_url ? (
      <button type="button" onClick={() => handleOpenPdf(it.pdf_url)}>
        Ver
      </button>
    ) : (
      ''
    ),
    it.change_pdf_url ? (
      <button type="button" onClick={() => handleOpenPdf(it.change_pdf_url)}>
        Ver
      </button>
    ) : (
      ''
    ),
    it.updated_at ? new Date(it.updated_at).toLocaleString() : '',
  ]);

  return (
    <div>
      <h2>CFE Automático</h2>
      <div style={{ marginBottom: '10px' }}>
        <button type="button" onClick={handlePoll} disabled={loading}>
          Actualizar
        </button>
      </div>
      {loading && <Loader />}
      <ErrorMessage error={error} />
      {!loading && <Table headers={tableHeaders} rows={tableRows} />}
      {!loading && !error && items.length === 0 && <p>No hay CFEs registrados.</p>}
    </div>
  );
};

export default CfeAutoPage;
