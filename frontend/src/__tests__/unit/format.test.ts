import { describe, expect, it } from "vitest";
import { formatPair, formatPct, formatUsd, formatUptime } from "../../utils/format";

describe("format utils", () => {
  it("formats USD with sign and commas", () => {
    expect(formatUsd(1234.5)).toBe("+$1,234.50");
    expect(formatUsd(-98.76)).toBe("-$98.76");
  });

  it("formats percentage with explicit sign for positive values", () => {
    expect(formatPct(2.345)).toBe("+2.35%");
    expect(formatPct(-0.1)).toBe("-0.10%");
  });

  it("formats uptime as HH:MM:SS", () => {
    expect(formatUptime(0, 3661000)).toBe("01:01:01");
  });

  it("formats pair labels from symbols", () => {
    expect(formatPair("BTCUSDT")).toBe("BTC / USDT");
    expect(formatPair("ETHBTC")).toBe("ETH / BTC");
    expect(formatPair("SOLETH")).toBe("SOL / ETH");
    expect(formatPair("")).toBe("");
    expect(formatPair("ABCXYZ")).toBe("ABCXYZ");
  });
});
