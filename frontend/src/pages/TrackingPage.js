import React from 'react';

/**
 * Placeholder page for the tracking module.
 * Provides a link to the legacy interface until this module is migrated.
 */
const TrackingPage = () => {
  return (
    <div>
      <h2>Rastreo</h2>
      <p>Esta sección aún no está migrada a React.</p>
      <p>Puedes acceder a la vista legacy haciendo clic en el siguiente enlace:</p>
      <a
        href="http://localhost:5914/rastreo/deposito"
        target="_blank"
        rel="noopener noreferrer"
      >
        Abrir Rastreo Legacy
      </a>
    </div>
  );
};

export default TrackingPage;