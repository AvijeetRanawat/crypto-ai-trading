import { afterEach, describe, expect, it, vi } from "vitest";
import { dashboardApi } from "../../services/dashboardApi";

describe("dashboardApi", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns parsed JSON for successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ session_start: "x", session_start_ms: 1 }),
      }),
    );

    const data = await dashboardApi.sessionStart();
    expect(data).toEqual({ session_start: "x", session_start_ms: 1 });
  });

  it("returns null for failed response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
      }),
    );

    const data = await dashboardApi.portfolioSummary();
    expect(data).toBeNull();
  });

  it("builds strategy diagnostics path with symbol and mode", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await dashboardApi.strategyDiagnostics("BTCUSDT", "FUTURES");

    expect(fetchMock).toHaveBeenCalledOnce();
    const firstArg = fetchMock.mock.calls[0][0] as string;
    expect(firstArg).toContain("/api/strategy/diagnostics");
    expect(firstArg).toContain("symbol=BTCUSDT");
    expect(firstArg).toContain("mode=FUTURES");
  });

  it("builds intent path without mode query when mode is omitted", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await dashboardApi.intent();

    expect(fetchMock).toHaveBeenCalledOnce();
    const firstArg = fetchMock.mock.calls[0][0] as string;
    expect(firstArg).toContain("/api/intent");
    expect(firstArg).not.toContain("?mode=");
  });

  it("exercises all endpoint helpers", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await dashboardApi.sessionStart();
    await dashboardApi.warmup("BTCUSDT");
    await dashboardApi.marketHistory("BTCUSDT");
    await dashboardApi.portfolioSummary();
    await dashboardApi.intent("SPOT");
    await dashboardApi.signals("BTCUSDT", 10);
    await dashboardApi.regime("BTCUSDT");
    await dashboardApi.tradesRecent();
    await dashboardApi.lessons();
    await dashboardApi.logs(20);
    await dashboardApi.llmSummary();
    await dashboardApi.llmBreakdown();
    await dashboardApi.rlCost();
    await dashboardApi.rlWeights();
    await dashboardApi.strategyDiagnostics("BTCUSDT", "SPOT");
    await dashboardApi.newsSentiment("BTCUSDT");

    expect(fetchMock).toHaveBeenCalledTimes(16);
  });

  it("returns null when fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    const data = await dashboardApi.newsSentiment("BTCUSDT");
    expect(data).toBeNull();
  });
});
