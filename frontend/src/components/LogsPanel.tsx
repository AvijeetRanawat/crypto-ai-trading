import { useEffect, useRef, useState } from "react";

interface LogsPanelProps {
  logs: string;
  height: number;
}

export function LogsPanel({ logs, height }: LogsPanelProps) {
  const logsRef = useRef<HTMLPreElement | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (!logsRef.current || !autoScroll) return;
    logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [logs, autoScroll]);

  const handleScroll = () => {
    if (!logsRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = logsRef.current;
    // Re-enable auto-scroll when user scrolls near bottom (within 40px)
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  };

  return (
    <section className="logs-bar glass" style={{ height: `${height}px` }}>
      <div className="logs-title">
        SYSTEM LOG {autoScroll ? "· AUTO-SCROLL" : "· PAUSED (scroll down to resume)"}
      </div>
      <pre className="log-body" ref={logsRef} onScroll={handleScroll}>
        {logs || "..."}
      </pre>
    </section>
  );
}
