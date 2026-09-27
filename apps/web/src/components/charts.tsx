/**
 * Small chart primitives, drawn as inline SVG.
 *
 * No charting library: the three shapes this dashboard needs are a line, a row
 * of bars and a number, and pulling in ~100KB of Recharts to draw them would
 * cost more than the whole rest of the bundle.
 *
 * Every chart here is a SINGLE series. That is a deliberate constraint rather
 * than a limitation: orders and rupees are different scales, and putting them
 * on one pair of axes would produce a dual-axis chart whose crossings mean
 * nothing. Two charts side by side compare honestly. It also means identity is
 * never carried by colour - the axis labels do that - so one brand hue is
 * enough and no legend is needed.
 */
import { useEffect, useRef, useState } from 'react';

/** Actual rendered width, so text stays at real pixel sizes instead of being
 *  scaled by a viewBox (which makes labels tiny on phones and huge on desktop). */
function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  return [ref, width] as const;
}

const INK_MUTED = '#71717A';
const GRID = '#E4E4E7';
const SERIES = '#E53935';

export interface SeriesPoint {
  label: string;
  value: number;
  /** Shown in the tooltip; falls back to the value. */
  display?: string;
}

export function TimeSeries({
  points,
  ariaLabel,
  formatValue = (v: number) => String(v),
}: {
  points: SeriesPoint[];
  ariaLabel: string;
  formatValue?: (value: number) => string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);

  const height = 200;
  const pad = { top: 16, right: 12, bottom: 26, left: 40 };
  const plotW = Math.max(width - pad.left - pad.right, 0);
  const plotH = height - pad.top - pad.bottom;

  // Always include zero: a line chart whose baseline floats exaggerates every
  // wobble into a cliff.
  const max = Math.max(1, ...points.map((p) => p.value));
  // Round the top up to something a person would choose, so gridline labels
  // are readable numbers rather than 0, 3.67, 7.33.
  const step = Math.pow(10, Math.floor(Math.log10(max)));
  const niceMax = Math.ceil(max / step) * step || 1;

  const x = (i: number) =>
    points.length <= 1 ? plotW / 2 : (i / (points.length - 1)) * plotW;
  const y = (v: number) => plotH - (v / niceMax) * plotH;

  const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.value)}`).join(' ');
  const area = points.length
    ? `${line} L${x(points.length - 1)},${plotH} L${x(0)},${plotH} Z`
    : '';

  // Thin the x labels so they never collide, whatever the width or range.
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotW / 64))));
  const gridLines = [0, 0.5, 1];

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={ariaLabel}
          onMouseLeave={() => setActive(null)}
        >
          <g transform={`translate(${pad.left},${pad.top})`}>
            {gridLines.map((t) => (
              <g key={t}>
                <line
                  x1={0}
                  x2={plotW}
                  y1={plotH * t}
                  y2={plotH * t}
                  stroke={GRID}
                  strokeWidth={1}
                />
                <text
                  x={-8}
                  y={plotH * t}
                  textAnchor="end"
                  dominantBaseline="middle"
                  fontSize={11}
                  fill={INK_MUTED}
                >
                  {formatValue(Math.round(niceMax * (1 - t)))}
                </text>
              </g>
            ))}

            <path d={area} fill={SERIES} fillOpacity={0.08} />
            <path
              d={line}
              fill="none"
              stroke={SERIES}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />

            {points.map((p, i) =>
              i % labelEvery === 0 ? (
                <text
                  key={p.label}
                  x={x(i)}
                  y={plotH + 18}
                  textAnchor="middle"
                  fontSize={11}
                  fill={INK_MUTED}
                >
                  {p.label}
                </text>
              ) : null,
            )}

            {active !== null && (
              <g pointerEvents="none">
                <line
                  x1={x(active)}
                  x2={x(active)}
                  y1={0}
                  y2={plotH}
                  stroke={INK_MUTED}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                />
                {/* 2px surface ring so the marker reads against the line. */}
                <circle
                  cx={x(active)}
                  cy={y(points[active].value)}
                  r={5}
                  fill={SERIES}
                  stroke="#FFFFFF"
                  strokeWidth={2}
                />
              </g>
            )}

            {/* Hit targets are full-height columns, far easier to hit than a
                5px dot - especially on a phone. */}
            {points.map((p, i) => (
              <rect
                key={`hit-${p.label}`}
                x={x(i) - plotW / Math.max(points.length, 1) / 2}
                y={0}
                width={plotW / Math.max(points.length, 1) || 1}
                height={plotH}
                fill="transparent"
                onMouseEnter={() => setActive(i)}
              />
            ))}
          </g>
        </svg>
      )}

      {active !== null && (
        <div
          className="pointer-events-none absolute z-10 rounded-md bg-on-surface px-space-sm py-space-xs text-body-sm text-white shadow-lg"
          style={{
            left: Math.min(Math.max(pad.left + x(active) - 60, 0), Math.max(width - 130, 0)),
            top: 0,
          }}
          role="status"
        >
          <div className="text-white/70">{points[active].label}</div>
          <div className="font-medium">
            {points[active].display ?? formatValue(points[active].value)}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Horizontal bars with the category and value written next to each one.
 *
 * Chosen over a pie for the same data: people read length far more accurately
 * than angle, and a pie of seven order statuses would need a legend to say
 * which slice is which - carrying identity in colour alone.
 */
export function BarList({
  items,
  emptyLabel = 'Nothing yet.',
}: {
  items: { label: string; value: number; display?: string }[];
  emptyLabel?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));

  if (!items.length || items.every((i) => i.value === 0)) {
    return <p className="py-space-md text-body-sm text-on-surface-variant">{emptyLabel}</p>;
  }

  return (
    <ul className="flex flex-col gap-space-sm">
      {items.map((item) => (
        <li key={item.label} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-space-sm">
            <span className="truncate text-body-sm text-on-surface-medium">{item.label}</span>
            <span className="shrink-0 text-label-md text-on-surface tabular-nums">
              {item.display ?? item.value}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-surface-container">
            <div
              className="h-full rounded-full bg-primary"
              style={{ width: `${Math.max((item.value / max) * 100, item.value > 0 ? 2 : 0)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
