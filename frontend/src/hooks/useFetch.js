import { useState, useEffect } from 'react';

/**
 * Generic hook to fetch data from an async function.
 *
 * It accepts a function that returns a promise (for example a
 * service call) and an array of dependencies. When any dependency
 * changes the provided function is invoked. The returned object
 * contains the current data, loading state and error message (if
 * any). Consumers can also manually re‑trigger the fetch by
 * calling the returned `refetch` function.
 *
 * @param {() => Promise<any>} fetchFunc function that returns a promise
 * @param {Array<any>} deps dependency array
 * @returns {{ data: any, loading: boolean, error: string | null, refetch: () => Promise<void> }}
 */
export default function useFetch(fetchFunc, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const run = async () => {
    setLoading(true);
    try {
      const result = await fetchFunc();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let ignore = false;
    (async () => {
      setLoading(true);
      try {
        const result = await fetchFunc();
        if (!ignore) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (!ignore) {
          setError(err?.message || String(err));
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    })();
    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, refetch: run };
}