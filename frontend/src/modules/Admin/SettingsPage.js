import React, { useEffect, useState } from 'react';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import { listSettings, updateSettings } from '../../services/admin';

/**
 * Settings management page. Lists all configuration keys and allows
 * updating their values. A simple key/value form is rendered; to
 * save changes press the Guardar button. Settings that require
 * special widgets can be extended later.
 */
export default function SettingsPage() {
  const [settings, setSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    async function fetchSettings() {
      setLoading(true);
      setError(null);
      try {
        const res = await listSettings();
        setSettings(res.settings || res);
      } catch (err) {
        setError(err?.message || String(err));
      } finally {
        setLoading(false);
      }
    }
    fetchSettings();
  }, []);

  const handleChange = (key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setMsg('');
    try {
      await updateSettings(settings);
      setMsg('Configuración guardada.');
    } catch (err) {
      setMsg(err?.message || String(err));
    }
  };

  return (
    <div>
      <h3>Configuración</h3>
      {loading && <Loader />}
      {error && <ErrorMessage message={error} />}
      {msg && <p>{msg}</p>}
      {!loading && !error && (
        <form onSubmit={handleSave}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th>Clave</th>
                <th>Valor</th>
              </tr>
            </thead>
            <tbody>
              {Object.keys(settings).map((key) => (
                <tr key={key}>
                  <td style={{ width: '30%', verticalAlign: 'top' }}>{key}</td>
                  <td>
                    <input
                      type="text"
                      value={settings[key] ?? ''}
                      onChange={(e) => handleChange(key, e.target.value)}
                      style={{ width: '100%' }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: '10px' }}>
            <button type="submit">Guardar</button>
          </div>
        </form>
      )}
    </div>
  );
}