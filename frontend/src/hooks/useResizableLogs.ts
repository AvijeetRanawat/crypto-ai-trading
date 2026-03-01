import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { STORAGE_KEYS } from "../utils/constants";

const DEFAULT_HEIGHT = 120;
const MIN_HEIGHT = 80;
const MAX_HEIGHT = 420;

export function useResizableLogs() {
  const [logsHeight, setLogsHeight] = useState<number>(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.logsHeight);
    return stored ? Number(stored) : DEFAULT_HEIGHT;
  });
  const resizingRef = useRef(false);

  useEffect(() => {
    const onMouseMove = (event: MouseEvent) => {
      if (!resizingRef.current) return;
      const desired = Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, window.innerHeight - event.clientY - 16));
      setLogsHeight(desired);
      localStorage.setItem(STORAGE_KEYS.logsHeight, String(Math.round(desired)));
    };

    const onMouseUp = () => {
      if (!resizingRef.current) return;
      resizingRef.current = false;
      document.body.style.cursor = "default";
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);

    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  const onResizeMouseDown = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    resizingRef.current = true;
    document.body.style.cursor = "row-resize";
    event.preventDefault();
  }, []);

  return { logsHeight, onResizeMouseDown };
}
