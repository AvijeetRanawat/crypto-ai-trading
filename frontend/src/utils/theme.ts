export interface ThemeTokens {
  chartText: string;
  chartGrid: string;
  chartBorder: string;
  chartYTick: string;
}

export function getThemeTokens(): ThemeTokens {
  const css = getComputedStyle(document.documentElement);
  return {
    chartText: css.getPropertyValue("--chart-text").trim() || "#71717a",
    chartGrid: css.getPropertyValue("--chart-grid").trim() || "rgba(255,255,255,0.03)",
    chartBorder: css.getPropertyValue("--chart-border").trim() || "rgba(255,255,255,0.08)",
    chartYTick: css.getPropertyValue("--chart-y-tick").trim() || "#4b5563",
  };
}
