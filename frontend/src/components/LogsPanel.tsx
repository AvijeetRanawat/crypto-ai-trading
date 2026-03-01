import { useEffect, useRef } from "react";

interface LogsPanelProps {
  logs: string;
  height: number;
}

export function LogsPanel({ logs, height }: LogsPanelProps) {
  const logsRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    if (!logsRef.current) return;
    logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [logs]);

  return (
    <section className="logs-bar glass" style={{ height: `${height}px` }}>
      <div className="logs-title">SYSTEM LOG · AUTO-SCROLL</div>
      <pre className="log-body" ref={logsRef}>
        {logs || "..."}
      </pre>
    </section>
  );
}
