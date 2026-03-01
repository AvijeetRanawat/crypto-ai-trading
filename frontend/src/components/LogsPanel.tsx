import { useEffect, useRef } from "react";

interface LogsPanelProps {
  logs: string;
}

export function LogsPanel({ logs }: LogsPanelProps) {
  const logsRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    if (!logsRef.current) return;
    logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [logs]);

  return (
    <section className="logs-bar glass">
      <div className="logs-title">SYSTEM LOG · AUTO-SCROLL</div>
      <pre className="log-body" ref={logsRef}>
        {logs || "..."}
      </pre>
    </section>
  );
}
