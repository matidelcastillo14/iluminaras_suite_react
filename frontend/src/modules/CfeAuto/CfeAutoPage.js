import React, { useState, useEffect } from 'react';
import api, { API_BASE_URL } from '../../services/api';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import Table from '../../components/Table';

/**
 * Página para el módulo CFE Auto.
 *
 * Esta página lista los últimos CFEs procesados automáticamente y permite
 * forzar un escaneo inmediato mediante el botón “Actualizar”.  Cada fila
 * incluye enlaces para descargar el recibo PDF y la etiqueta de cambio si
 * están disponibles.
 */
const CfeAutoPage = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Cargar CFEs desde el backend
  const fetchItems = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get('/cfe/auto/api/cfes');
      if (Array.isArray(res)) {
        setItems(res);
      } else if (res && res.error) {
        setItems([]);
        setError(res.detail || res.error || 'No se pudieron obtener CFEs');
      } else {
        setItems([]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();
  }, []);

  // Forzar poll manual para nuevos CFEs
  const handlePoll = async () => {
    try {
      await api.post('/cfe/auto/api/cfes/poll_now');
      fetchItems();
    } catch (err) {
      setError(err.message);
    }
  };

  // Abrir PDF en nueva pestaña
  const handleOpenPdf = (relUrl) => {
    if (relUrl) {
      const url = `${API_BASE_URL}${relUrl}`;
      window.open(url, '_blank');
    }
  };

  // Preparar datos para la tabla
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
    it.source_type,
    it.source_id,
    it.status,
    it.attempts,
    it.last_error || '',
    it.cfe,
    it.receptor,
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
      {!loading && (
        <Table headers={tableHeaders} rows={tableRows} />
      )}
      {!loading && !error && items.length === 0 && (
        <p>No hay CFEs registrados.</p>
      )}
    </div>
  );
};

export default CfeAutoPage;
