// Small single-series bar chart in the accent colour: a goal line, a tooltip on
// tap or hover (handled in gym-progress.js for every [data-chart]) and a table view.
import { esc } from './util.js';

/**
 * items: [{ label, value, tip }]; options: { goal, aria, columns: [[title, (item) => text], …] }.
 */
export function barChart(items, { goal = 0, aria = '', hint = 'Нажмите на столбик, чтобы увидеть день.', columns = [] } = {}) {
  const W = 320;
  const H = 120;
  const base = H - 18;
  const top = Math.max(1, goal, ...items.map((i) => i.value || 0));
  const step = W / items.length;
  const bar = Math.min(26, step - 8);
  const y = (v) => base - (v / top) * (H - 30);
  const bars = items.map((item, i) => {
    const x = i * step + (step - bar) / 2;
    const h = base - y(item.value || 0);
    const mark = item.value
      ? `<path class="bar" d="M${x} ${base}V${base - Math.max(h, 6) + 4}a4 4 0 0 1 4 -4h${bar - 8}a4 4 0 0 1 4 4V${base}Z"/>`
      : `<rect class="bar zero" x="${x}" y="${base - 2}" width="${bar}" height="2" rx="1"/>`;
    return `<g class="tip-target" data-tip="${esc(item.tip)}" tabindex="0"><rect class="hit" x="${i * step}" y="0" width="${step}" height="${H}"/>${mark}
      <text class="axis" x="${i * step + step / 2}" y="${H - 4}" text-anchor="middle">${esc(item.label)}</text></g>`;
  }).join('');
  const goalLine = goal ? `<path class="goal" d="M0 ${y(goal)}H${W}"/>` : '';
  const table = columns.length ? `<details class="chart-table"><summary>Таблица</summary><table>
    <thead><tr>${columns.map(([title]) => `<th>${esc(title)}</th>`).join('')}</tr></thead>
    <tbody>${items.map((item) => `<tr>${columns.map(([, cell]) => `<td>${esc(cell(item))}</td>`).join('')}</tr>`).join('')}</tbody></table></details>` : '';
  return `<div class="chart" data-chart><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(aria)}">
    <path class="baseline" d="M0 ${base}H${W}"/>${goalLine}${bars}</svg>
    <p class="chart-tip" aria-live="polite">${esc(hint)}</p>${table}</div>`;
}
