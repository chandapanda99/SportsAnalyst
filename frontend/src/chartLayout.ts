/** Let each chart occupy its own height instead of sharing its neighbour's row. */
export function chartLayout(node: HTMLElement) {
  if (typeof ResizeObserver === 'undefined') return;

  const measure = () => {
    // The grid uses one-pixel rows. Reserve one extra pixel for the divider.
    const rows = Math.ceil(node.getBoundingClientRect().height) + 1;
    node.style.setProperty('--chart-rows', String(Math.max(1, rows)));
  };
  const observer = new ResizeObserver(measure);
  observer.observe(node);
  measure();
  return {destroy: () => observer.disconnect()};
}
