import React, { useEffect, useState } from 'react';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import { getSnapshot, mark } from '../../services/relojHomeOffice';
import { formatDateTime } from '../../utils/date';

/**
 * Page component for the home office clock. Displays the current
 * snapshot for the logged‑in user and allows them to queue a new
 * mark. Requires the `reloj_home_office` view permission. If the
 * user is not enabled the snapshot will indicate so.
 */
export default function RelojHomeOfficePage() {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionMsg, setActionMsg] = useState('');
  const [actionLoading, setActionLoading] = useState(false);

  const loadSnapshot = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSnapshot();
      setSnapshot(res);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSnapshot();
  }, []);

  const handleMark = async () => {
    setActionLoading(true);
    setActionMsg('');
    try {
      const res = await mark();
      if (typeof res === 'string') {
        setActionMsg(res);
      } else if (res && typeof res.msg !== 'undefined') {
        setActionMsg(res.msg);
      } else {
        setActionMsg(JSON.stringify(res));
      }
      // Refresh snapshot after mark
      await loadSnapshot();
    } catch (err) {
      setActionMsg(err?.message || String(err));
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div>
      <h2>Reloj Home Office</h2>
      {loading && <Loader />}
      {error && <ErrorMessage message={error} />}
      {!loading && !error && snapshot && (
        <div>
          <div style={{ marginBottom: '10px' }}>
            <strong>Habilitado para tu usuario:</strong> {snapshot.enabled ? 'Sí' : 'No'}
          </div>
          <div style={{ marginBottom: '10px' }}>
            <strong>Módulo activado:</strong> {snapshot.module_enabled ? 'Sí' : 'No'}
          </div>
          <div style={{ marginBottom: '10px' }}>
            <strong>CI configurada:</strong> {snapshot.has_ref_code ? 'Sí' : 'No'}
          </div>
          {snapshot.last_event_ts && (
            <div style={{ marginBottom: '10px' }}>
              <strong>Última marcada:</strong> {formatDateTime(snapshot.last_event_ts)} ({snapshot.last_event_state})
              {snapshot.last_event_error && (
                <>
                  {' '}
                  <em style={{ color: 'red' }}>Error: {snapshot.last_event_error}</em>
                </>
              )}
            </div>
          )}
          {snapshot.last_event_source && (
            <div style={{ marginBottom: '10px' }}>
              <strong>Fuente:</strong> {snapshot.last_event_source}
            </div>
          )}
          <button onClick={handleMark} disabled={actionLoading || !snapshot.enabled || !snapshot.module_enabled || !snapshot.has_ref_code}>
            {actionLoading ? 'Enviando...' : 'Marcar'}
          </button>
          {actionMsg && <p style={{ marginTop: '10px' }}>{actionMsg}</p>}
        </div>
      )}
    </div>
  );
}