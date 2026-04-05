import React, { useState, useEffect } from 'react';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import Table from '../../components/Table';
import {
  listApplications,
  getApplication,
  updateApplication,
  listPositions,
  createPosition,
  updatePosition,
  togglePosition,
  deletePosition,
} from '../../services/postulaciones';
import { formatDateTime } from '../../utils/date';

/**
 * Page component for the Postulaciones module. It provides two tabs:
 * one to view and manage job applications and another to manage
 * positions (puestos). Both consume a JSON API defined in
 * src/services/postulaciones.js. If those endpoints are missing on
 * the backend the page will show error messages.
 */
export default function PostulacionesPage() {
  // Active tab: 'list' or 'positions'
  const [tab, setTab] = useState('list');

  // Search parameters for applications
  const [q, setQ] = useState('');
  const [positionFilter, setPositionFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  // Data state
  const [applications, setApplications] = useState([]);
  const [positions, setPositions] = useState([]);
  const [statuses, setStatuses] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Selected application for detail view
  const [selectedApp, setSelectedApp] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');

  // Position management state
  const [posForm, setPosForm] = useState({ id: null, name: '', sort_order: '' });
  const [posSaving, setPosSaving] = useState(false);
  const [posError, setPosError] = useState(null);

  // Load list of applications on search param change
  useEffect(() => {
    if (tab !== 'list') return;
    async function fetchList() {
      setLoading(true);
      setError(null);
      try {
        const res = await listApplications({ q, positionId: positionFilter, status: statusFilter });
        setApplications(res.applications || []);
        setPositions(res.positions || []);
        setStatuses(res.statuses || []);
        // Reset selection when list reloads
        setSelectedApp(null);
      } catch (err) {
        setError(err?.message || String(err));
      } finally {
        setLoading(false);
      }
    }
    fetchList();
  }, [q, positionFilter, statusFilter, tab]);

  // Load list of positions for positions tab
  useEffect(() => {
    if (tab !== 'positions') return;
    async function fetchPositions() {
      setLoading(true);
      setError(null);
      try {
        const res = await listPositions();
        setPositions(res.positions || res);
      } catch (err) {
        setError(err?.message || String(err));
      } finally {
        setLoading(false);
      }
    }
    fetchPositions();
  }, [tab]);

  // Fetch details when selectedApp id changes
  useEffect(() => {
    if (!selectedApp) return;
    async function fetchDetail() {
      setDetailLoading(true);
      setDetailError(null);
      try {
        const res = await getApplication(selectedApp.id);
        setSelectedApp(res);
      } catch (err) {
        setDetailError(err?.message || String(err));
      } finally {
        setDetailLoading(false);
      }
    }
    fetchDetail();
  }, [selectedApp?.id]);

  // Handlers
  const handleSearchSubmit = (e) => {
    e.preventDefault();
    // triggers useEffect due to dependencies
  };

  const handleSelectApp = (app) => {
    setSelectedApp({ id: app.id });
  };

  const handleSaveApplication = async () => {
    if (!selectedApp) return;
    setSaving(true);
    setSaveMessage('');
    try {
      const payload = {
        status: selectedApp.status,
        admin_note: selectedApp.admin_note,
        position_id: selectedApp.position_id,
      };
      const updated = await updateApplication(selectedApp.id, payload);
      setSelectedApp(updated);
      setSaveMessage('Guardado.');
      // refresh list to reflect changes
      setQ((prev) => prev);
    } catch (err) {
      setSaveMessage(err?.message || String(err));
    } finally {
      setSaving(false);
    }
  };

  const handlePosFormChange = (field, value) => {
    setPosForm((prev) => ({ ...prev, [field]: value }));
  };

  const handlePosSave = async (e) => {
    e.preventDefault();
    setPosSaving(true);
    setPosError(null);
    try {
      if (posForm.id) {
        await updatePosition(posForm.id, {
          name: posForm.name,
          sort_order: parseInt(posForm.sort_order || 0, 10),
        });
      } else {
        await createPosition({ name: posForm.name, sort_order: parseInt(posForm.sort_order || 0, 10) });
      }
      // Reload positions
      const res = await listPositions();
      setPositions(res.positions || res);
      setPosForm({ id: null, name: '', sort_order: '' });
    } catch (err) {
      setPosError(err?.message || String(err));
    } finally {
      setPosSaving(false);
    }
  };

  const handlePosEdit = (pos) => {
    setPosForm({ id: pos.id, name: pos.name, sort_order: pos.sort_order });
  };

  const handlePosToggle = async (pos) => {
    try {
      await togglePosition(pos.id);
      const res = await listPositions();
      setPositions(res.positions || res);
    } catch (err) {
      setPosError(err?.message || String(err));
    }
  };

  const handlePosDelete = async (pos) => {
    if (!window.confirm('¿Eliminar puesto?')) return;
    try {
      await deletePosition(pos.id);
      const res = await listPositions();
      setPositions(res.positions || res);
    } catch (err) {
      setPosError(err?.message || String(err));
    }
  };

  return (
    <div>
      <h2>Postulaciones</h2>
      {/* Tab selector */}
      <div style={{ marginBottom: '10px' }}>
        <button
          onClick={() => setTab('list')}
          style={{ marginRight: '5px', fontWeight: tab === 'list' ? 'bold' : 'normal' }}
        >
          Listado
        </button>
        <button
          onClick={() => setTab('positions')}
          style={{ fontWeight: tab === 'positions' ? 'bold' : 'normal' }}
        >
          Puestos
        </button>
      </div>
      {tab === 'list' && (
        <div style={{ display: 'flex' }}>
          <div style={{ flex: 1 }}>
            {/* Search form */}
            <form onSubmit={handleSearchSubmit} style={{ marginBottom: '10px' }}>
              <input
                type="text"
                placeholder="Buscar..."
                value={q}
                onChange={(e) => setQ(e.target.value)}
                style={{ marginRight: '5px' }}
              />
              <select
                value={positionFilter}
                onChange={(e) => setPositionFilter(e.target.value)}
                style={{ marginRight: '5px' }}
              >
                <option value="">Puesto</option>
                {positions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="">Estado</option>
                {statuses.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <button type="submit" style={{ marginLeft: '5px' }}>
                Buscar
              </button>
            </form>
            {loading && <Loader />}
            {error && <ErrorMessage message={error} />}
            {!loading && !error && applications && applications.length > 0 && (
              <Table
                headers={['ID', 'Nombre', 'Email', 'Puesto', 'Estado', 'Creado']}
                rows={applications.map((app) => [
                  app.id,
                  `${app.first_name || ''} ${app.last_name || ''}`.trim(),
                  app.email,
                  app.position_name || '-',
                  app.status,
                  formatDateTime(app.created_at),
                ])}
                onRowClick={(idx) => handleSelectApp(applications[idx])}
              />
            )}
            {!loading && !error && applications && applications.length === 0 && <p>No hay postulaciones.</p>}
          </div>
          {/* Detail panel */}
          <div style={{ width: '380px', marginLeft: '20px' }}>
            {selectedApp && (
              <div style={{ border: '1px solid #ccc', padding: '10px' }}>
                {detailLoading && <Loader />}
                {detailError && <ErrorMessage message={detailError} />}
                {!detailLoading && !detailError && selectedApp && (
                  <>
                    <h3>Postulación #{selectedApp.id}</h3>
                    <div>
                      <strong>Nombre:</strong> {selectedApp.first_name} {selectedApp.last_name}
                    </div>
                    <div>
                      <strong>Email:</strong> {selectedApp.email}
                    </div>
                    <div>
                      <strong>Teléfono:</strong> {selectedApp.phone || '-'}
                    </div>
                    <div>
                      <strong>Puesto:</strong>{' '}
                      <select
                        value={selectedApp.position_id || ''}
                        onChange={(e) => setSelectedApp((prev) => ({ ...prev, position_id: e.target.value }))}
                      >
                        <option value="">-</option>
                        {positions.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <strong>Estado:</strong>{' '}
                      <select
                        value={selectedApp.status || ''}
                        onChange={(e) => setSelectedApp((prev) => ({ ...prev, status: e.target.value }))}
                      >
                        {statuses.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <strong>Nota admin:</strong>
                      <br />
                      <textarea
                        value={selectedApp.admin_note || ''}
                        onChange={(e) => setSelectedApp((prev) => ({ ...prev, admin_note: e.target.value }))}
                        rows={4}
                        style={{ width: '100%' }}
                      />
                    </div>
                    {selectedApp.files && selectedApp.files.length > 0 && (
                      <div>
                        <strong>Archivos:</strong>
                        <ul>
                          {selectedApp.files.map((f) => (
                            <li key={f.id}>
                              <a href={f.url} target="_blank" rel="noopener noreferrer">
                                {f.name || f.original_filename || 'Archivo'}
                              </a>
                              {' | '}
                              <a href={f.download_url} target="_blank" rel="noopener noreferrer">
                                Descargar
                              </a>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div style={{ marginTop: '10px' }}>
                      <button onClick={handleSaveApplication} disabled={saving}>
                        {saving ? 'Guardando...' : 'Guardar'}
                      </button>
                      {saveMessage && <span style={{ marginLeft: '10px' }}>{saveMessage}</span>}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      )}
      {tab === 'positions' && (
        <div>
          {loading && <Loader />}
          {error && <ErrorMessage message={error} />}
          {!loading && !error && (
            <div style={{ display: 'flex' }}>
              <div style={{ flex: 1 }}>
                <h3>Listado de puestos</h3>
                {positions && positions.length > 0 ? (
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>Nombre</th>
                        <th>Orden</th>
                        <th>Activo</th>
                        <th>Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map((p) => (
                        <tr key={p.id}>
                          <td>{p.id}</td>
                          <td>{p.name}</td>
                          <td>{p.sort_order}</td>
                          <td>{p.is_active ? 'Sí' : 'No'}</td>
                          <td>
                            <button onClick={() => handlePosEdit(p)}>Editar</button>{' '}
                            <button onClick={() => handlePosToggle(p)}>
                              {p.is_active ? 'Desactivar' : 'Activar'}
                            </button>{' '}
                            <button onClick={() => handlePosDelete(p)}>Eliminar</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p>No hay puestos.</p>
                )}
              </div>
              <div style={{ width: '320px', marginLeft: '20px' }}>
                <h3>{posForm.id ? 'Editar puesto' : 'Nuevo puesto'}</h3>
                {posError && <ErrorMessage message={posError} />}
                <form onSubmit={handlePosSave}>
                  <div>
                    <label>
                      Nombre
                      <br />
                      <input
                        type="text"
                        value={posForm.name}
                        onChange={(e) => handlePosFormChange('name', e.target.value)}
                        required
                      />
                    </label>
                  </div>
                  <div>
                    <label>
                      Orden
                      <br />
                      <input
                        type="number"
                        value={posForm.sort_order}
                        onChange={(e) => handlePosFormChange('sort_order', e.target.value)}
                      />
                    </label>
                  </div>
                  <div style={{ marginTop: '10px' }}>
                    <button type="submit" disabled={posSaving}>
                      {posSaving ? 'Guardando...' : 'Guardar'}
                    </button>
                    {posForm.id && (
                      <button
                        type="button"
                        onClick={() => setPosForm({ id: null, name: '', sort_order: '' })}
                        style={{ marginLeft: '10px' }}
                      >
                        Cancelar
                      </button>
                    )}
                  </div>
                </form>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}