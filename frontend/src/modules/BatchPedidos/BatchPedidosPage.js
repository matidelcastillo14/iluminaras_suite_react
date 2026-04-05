import React, { useState, useEffect } from 'react';
import api from '../../services/api';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import Table from '../../components/Table';

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
      const res = await api.get(`/inventario/batch-pedidos/api/list?page=${page}&page_size=${pageSize}`);
      if (res && Array.isArray(res.items)) {
        setItems(res.items);
        setTotal(res.total || 0);
      } else {
        setItems([]);
        setTotal(0);
        setError(res?.detail || res?.error || 'Error al cargar lista');
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

  const handleExport = async () => {
    setError('');
    try {
      const { blob, filename } = await api.download('/inventario/batch-pedidos/api/export_xlsx', {
        method: 'POST',
        body: {
          filters: {},
          sort_key: 'hora',
          sort_dir: 'desc',
        },
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || 'pedidos_por_batch.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    }
  };

  const headers = ['Fecha y hora', 'Fecha pedido', 'Batch', 'ID Web', 'ID MeliCart', 'ID Meli', 'Cliente', 'Monto', 'Factura', 'Ver'];
  const rows = items.map((it) => [
    it.hora || '',
    it.order_date || '',
    it.batch_name || '',
    it.id_web || '',
    it.id_melicart || '',
    it.id_meli || '',
    it.cliente || '',
    it.monto_compra != null ? Number(it.monto_compra).toFixed(2) : '',
    it.n_factura_fmt || '',
    it.link_factura ? (
      <a href={it.link_factura} target="_blank" rel="noopener noreferrer">Ver</a>
    ) : '',
  ]);

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div>
      <h2>Pedidos por Batch</h2>
      <div style={{ marginBottom: '10px' }}>
        <button type="button" onClick={fetchList} disabled={loading}>Recargar</button>
        <button type="button" onClick={handleExport} disabled={loading} style={{ marginLeft: '10px' }}>Exportar XLSX</button>
      </div>
      {loading && <Loader />}
      <ErrorMessage error={error} />
      {!loading && <Table headers={headers} rows={rows} />}
      {!loading && totalPages > 1 && (
        <div style={{ marginTop: '10px' }}>
          Página {page} de {totalPages}
          <div style={{ marginTop: '5px' }}>
            <button type="button" onClick={() => setPage(1)} disabled={page === 1}>Primera</button>
            <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} style={{ marginLeft: '5px' }}>Anterior</button>
            <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} style={{ marginLeft: '5px' }}>Siguiente</button>
            <button type="button" onClick={() => setPage(totalPages)} disabled={page === totalPages} style={{ marginLeft: '5px' }}>Última</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default BatchPedidosPage;
