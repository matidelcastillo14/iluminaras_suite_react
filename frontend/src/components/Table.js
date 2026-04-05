import React from 'react';

/**
 * Reusable table component.  Accepts an array of header labels and a
 * two‑dimensional array of cell values.  This component handles basic
 * styling such as borders and padding to produce a clean tabular view.
 *
 * Example usage:
 *
 * <Table
 *   headers={['Name', 'Age']}
 *   rows={[[person.name, person.age]]}
 * />
 */
const Table = ({ headers, rows, onRowClick, renderCell }) => {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          {headers.map((h, idx) => (
            <th
              key={idx}
              style={{ borderBottom: '1px solid #ddd', textAlign: 'left', padding: '8px' }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rIdx) => (
          <tr
            key={rIdx}
            onClick={() => onRowClick && onRowClick(rIdx)}
            style={{ cursor: onRowClick ? 'pointer' : undefined }}
          >
            {row.map((cell, cIdx) => (
              <td
                key={cIdx}
                style={{ padding: '8px', borderBottom: '1px solid #eee' }}
              >
                {renderCell ? renderCell(rIdx, cIdx, cell) : cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
};

export default Table;
