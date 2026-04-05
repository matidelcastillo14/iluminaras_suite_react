import React from 'react';

/**
 * Generic error message component.
 * Accepts either `error` or `message` to remain compatible with pages
 * created during the migration.
 */
const ErrorMessage = ({ error, message }) => {
  const text = error || message;
  if (!text) return null;
  return <div style={{ color: 'red', margin: '10px 0' }}>{text}</div>;
};

export default ErrorMessage;
