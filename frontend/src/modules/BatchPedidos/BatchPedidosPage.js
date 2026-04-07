import React, { useState, useEffect } from 'react';
import api, { API_BASE_URL } from '../../services/api';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import Table from '../../components/Table';

/**
 * Página para el módulo Batch Pedidos.
 *
 * Muestra un listado paginado de pedidos agrupados por batch.  Permite
 * recargar la lista y descargar un XLSX con todos los datos.  Esta página
 * está preparada para integrarse con los endpoints del backend.  Si dichos
 * endpoints no están disponibles o retornan un error, se mostrará el
 * mensaje correspondiente pero la estructura de la página seguirá
 * funcionando.
 */
const BatchPedidosPage = () => {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchList = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get(
        `/inventario/batch-pedidos/api/list?page=${page}&page_size=${pageSize}`
      );
      // Respuesta esperada: { items: [...], total: number }
      if (res && Array.isArray(res.items)) {
        setItems(res.items);
        setTotal(res.total || 0);
      } else if (res && res.error) {
        setItems([]);
        setTotal(0);
        setError(res.detail || res.error || 'Error al cargar lista');
      } else {
        setItems([]);
        setTotal(0);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const handleRefresh = () => {
    fetchList();
  };

  const handleExport = async () => {
    try {
      // Para exportar, enviar filtros actuales (ninguno) y sort default
      const res = await api.post('/inventario/batch-pedidos/api/export_xlsx', {
        filters: {},
        sort_key: 'hora',
        sort_dir: 'desc',
      });
      // La respuesta es un URL relativa al archivo generado.  Abrir en nueva pestaña.
      if (res && res.ok && res.url) {
        const url = `${API_BASE_URL}${res.url}`;
        window.open(url, '_blank');
      } else {
        // La API actual de exportación devuelve un archivo directo sin JSON.
        // Si la API se actualiza para devolver JSON, manejar aquí.
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const headers = [
    'Fecha y hora',
    'Fecha pedido',
    'Batch',
    'ID Web',
    'ID MeliCart',
    'ID Meli',
    'Cliente',
    'Monto',
    'Factura',
    'Ver',
  ];
  const rows = items.map((it) => [
    it.hora || '',
    it.order_date || '',
    it.batch_name || '',
    it.id_web || '',
    it.id_melicart || '',
    it.id_meli || '',
    it.cliente || '',
    it.monto_compra != null ? it.monto_compra.toFixed(2) : '',
    it.n_factura_fmt || '',
    it.link_factura ? (
      <a href={it.link_factura} target="_blank" rel="noopener noreferrer">
        Ver
      </a>
    ) : (
      ''
    ),
  ]);

  // Calcular número de páginas
  const totalPages = Math.ceil(total / pageSize);

  return (
    <div>
      <h2>Pedidos por Batch</h2>
      <div style={{ marginBottom: '10px' }}>
        <button type="button" onClick={handleRefresh} disabled={loading}>
          Recargar
        </button>
        <button
          type="button"
          onClick={handleExport}
          disabled={loading}
          style={{ marginLeft: '10px' }}
        >
          Exportar XLSX
        </button>
      </div>
      {loading && <Loader />}
      <ErrorMessage error={error} />
      {!loading && <Table headers={headers} rows={rows} />}
      {!loading && totalPages > 1 && (
        <div style={{ marginTop: '10px' }}>
          Página {page} de {totalPages}
          <div style={{ marginTop: '5px' }}>
            <button type="button" onClick={() => setPage(1)} disabled={page === 1}>
              Primera
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              style={{ marginLeft: '5px' }}
            >
              Anterior
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              style={{ marginLeft: '5px' }}
            >
              Siguiente
            </button>
            <button
              type="button"
              onClick={() => setPage(totalPages)}
              disabled={page === totalPages}
              style={{ marginLeft: '5px' }}
            >
              Última
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default BatchPedidosPage;
