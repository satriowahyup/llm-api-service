export function formatUsd(cost: number): string {
  if (!Number.isFinite(cost) || cost <= 0) {
    return "$0.00";
  }
  if (cost < 0.0001) {
    return `$${cost.toFixed(7).replace(/0+$/, "")}`;
  }
  if (cost < 0.01) {
    return `$${cost.toFixed(5).replace(/0+$/, "")}`;
  }
  return `$${cost.toFixed(4)}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) {
    return "n/a";
  }
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(2)}s`;
  }
  return `${Math.round(ms)}ms`;
}

export function formatTps(tps: number | null | undefined): string {
  if (tps === null || tps === undefined || !Number.isFinite(tps) || tps <= 0) {
    return "n/a";
  }
  return `${tps.toFixed(1)} tok/s`;
}

export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
