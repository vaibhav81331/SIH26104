// App-wide state: server meta, the replay clock, and the live event stream.

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

export function AppProvider({ children }) {
  const [meta, setMeta] = useState(null);
  const [clock, setClock] = useState(null); // { mode, asOf, dates, liveAvailable }
  const [version, setVersion] = useState(0); // bumps whenever data behind the views changes
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const playRef = useRef(null);
  const [playing, setPlaying] = useState(false);

  const load = useCallback(async () => {
    try {
      const [m, r] = await Promise.all([api.get("/meta"), api.get("/replay")]);
      setMeta(m);
      setClock(r);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Server-sent events: alert transitions, deliveries, clock changes.
  useEffect(() => {
    let es;
    try {
      es = new EventSource("/v1/stream/alerts");
    } catch {
      return undefined;
    }
    const push = (type) => (ev) => {
      const data = JSON.parse(ev.data);
      setEvents((xs) => [{ type, data, at: new Date().toLocaleTimeString() }, ...xs].slice(0, 200));
      if (type === "asof") {
        setClock((c) => (c ? { ...c, asOf: data.asOf, mode: data.mode } : c));
        setVersion((v) => v + 1);
      }
    };
    for (const t of ["transitions", "deliveries", "asof", "hap"]) es.addEventListener(t, push(t));
    return () => es.close();
  }, []);

  const setAsOf = useCallback(async (date) => {
    const r = await api.post("/replay/asof", { date, by: "dashboard" });
    setClock((c) => ({ ...c, asOf: r.asOf, mode: r.mode }));
    setVersion((v) => v + 1);
  }, []);

  const step = useCallback(
    async (delta) => {
      if (!clock) return false;
      const i = clock.dates.indexOf(clock.asOf) + delta;
      if (i < 0 || i >= clock.dates.length) return false;
      await setAsOf(clock.dates[i]);
      return true;
    },
    [clock, setAsOf],
  );

  // The play interval must always call the *current* step(), which closes over
  // the latest clock; capturing it once would replay the same day forever.
  const stepRef = useRef(step);
  stepRef.current = step;

  const togglePlay = useCallback(() => {
    if (playRef.current) {
      clearInterval(playRef.current);
      playRef.current = null;
      setPlaying(false);
      return;
    }
    setPlaying(true);
    playRef.current = setInterval(async () => {
      const ok = await stepRef.current(1).catch(() => false);
      if (!ok) {
        clearInterval(playRef.current);
        playRef.current = null;
        setPlaying(false);
      }
    }, 1600);
  }, []);

  useEffect(() => () => playRef.current && clearInterval(playRef.current), []);

  const refreshLive = useCallback(async () => {
    const r = await api.post("/live/refresh");
    setClock((c) => ({ ...c, asOf: r.asOf, mode: r.mode, liveAvailable: true }));
    setVersion((v) => v + 1);
    return r;
  }, []);

  return (
    <Ctx.Provider value={{ meta, clock, version, events, error, setAsOf, step, togglePlay, playing, refreshLive, reload: load, bump: () => setVersion((v) => v + 1) }}>
      {children}
    </Ctx.Provider>
  );
}

/** Fetch a path whenever the app data version changes. */
export function useData(path, deps = []) {
  const { version } = useApp();
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    if (!path) return undefined;
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    api
      .get(path)
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((error) => alive && setState({ data: null, error: error.message, loading: false }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, version, ...deps]);
  return state;
}
