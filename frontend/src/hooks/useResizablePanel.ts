import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { STORAGE_KEYS } from "../utils/constants";

const DEFAULT_WIDTH = 300;

export function useResizablePanel() {
  const [panelWidth, setPanelWidth] = useState<number>(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.panelWidth);
    return stored ? Number(stored) : DEFAULT_WIDTH;
  });
  const resizingRef = useRef(false);

  useEffect(() => {
    const onMouseMove = (event: MouseEvent) => {
      if (!resizingRef.current) return;
      const width = window.innerWidth - event.clientX - 12;
      if (width > 150 && width < 600) {
        setPanelWidth(width);
        localStorage.setItem(STORAGE_KEYS.panelWidth, String(Math.round(width)));
      }
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
    document.body.style.cursor = "col-resize";
    event.preventDefault();
  }, []);

  return { panelWidth, onResizeMouseDown };
}
