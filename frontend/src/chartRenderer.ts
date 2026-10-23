// Keep the large charting bundle lazy, and the UI independently testable.
export async function loadChartRenderer() {
  return (await import('vega-embed')).default;
}
