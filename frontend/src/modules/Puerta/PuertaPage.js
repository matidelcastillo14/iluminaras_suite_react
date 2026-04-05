import React, { useEffect, useState } from 'react';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import {
  getHealth,
  openDoor,
  shutterUp,
  shutterDown,
  shutterStop,
} from '../../services/puerta';

/**
 * Page component for door and shutter controls. Shows basic health
 * diagnostics and provides buttons to trigger actions. Requires the
 * `puerta` view permission. If the API endpoints are not available
 * yet the page will show an error.
 */
export default function PuertaPage() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState('');

  useEffect(() => {
    async function fetchHealth() {
      setLoading(true);
      setError(null);
      try {
        const res = await getHealth();
        setHealth(res);
      } catch (err) {
        setError(err?.message || String(err));
      } finally {
        setLoading(false);
      }
    }
    fetchHealth();
  }, []);

  const runAction = async (actionFn) => {
    setMessage('');
    try {
      const res = await actionFn();
      if (typeof res === 'string') {
        setMessage(res);
      } else if (res && typeof res.msg !== 'undefined') {
        setMessage(res.msg);
      } else {
        setMessage(JSON.stringify(res));
      }
    } catch (err) {
      setMessage(err?.message || String(err));
    }
  };

  return (
    <div>
      <h2>Control de Puerta y Cortina</h2>
      {loading && <Loader />}
      {error && <ErrorMessage message={error} />}
      {!loading && !error && (
        <div>
          <div style={{ marginBottom: '10px' }}>
            <h3>Estado del controlador</h3>
            <pre style={{ background: '#f7f7f7', padding: '10px', maxHeight: '200px', overflow: 'auto' }}>
              {JSON.stringify(health, null, 2)}
            </pre>
          </div>
          <div>
            <h3>Acciones</h3>
            <button onClick={() => runAction(openDoor)} style={{ marginRight: '10px' }}>
              Abrir puerta
            </button>
            <button onClick={() => runAction(shutterUp)} style={{ marginRight: '10px' }}>
              Subir cortina
            </button>
            <button onClick={() => runAction(shutterDown)} style={{ marginRight: '10px' }}>
              Bajar cortina
            </button>
            <button onClick={() => runAction(shutterStop)}>Detener cortina</button>
          </div>
          {message && <p style={{ marginTop: '10px' }}>{message}</p>}
        </div>
      )}
    </div>
  );
}