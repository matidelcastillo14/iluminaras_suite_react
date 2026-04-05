import React, { useEffect, useState } from 'react';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import { listModules, toggleModule } from '../../services/admin';

/**
 * Modules management page. Lists all modules with their current
 * internal and public enabled state. Allows toggling each state
 * individually via checkboxes. Changes are saved immediately upon
 * toggle. It assumes the backend exposes a listModules() and
 * toggleModule() API.
 */
export default function ModulesPage() {
  const [modules, setModules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState('');

  const loadModules = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listModules();
      setModules(res.modules || res);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadModules();
  }, []);

  const handleToggle = async (modKey, field, value) => {
    setMsg('');
    try {
      const payload = {};
      payload[field] = value;
      await toggleModule(modKey, payload);
      await loadModules();
    } catch (err) {
      setMsg(err?.message || String(err));
    }
  };

  return (
    <div>
      <h3>Módulos</h3>
      {loading && <Loader />}
      {error && <ErrorMessage message={error} />}
      {msg && <p>{msg}</p>}
      {!loading && !error && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th>Clave</th>
              <th>Nombre</th>
              <th>Descripción</th>
              <th>Interno habilitado</th>
              <th>Público habilitado</th>
            </tr>
          </thead>
          <tbody>
            {modules.map((m) => (
              <tr key={m.key}>
                <td>{m.key}</td>
                <td>{m.name || m.key}</td>
                <td>{m.description || ''}</td>
                <td>
                  <input
                    type="checkbox"
                    checked={!!m.internal_enabled}
                    onChange={(e) => handleToggle(m.key, 'internal', e.target.checked)}
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={!!m.public_enabled}
                    onChange={(e) => handleToggle(m.key, 'public', e.target.checked)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}