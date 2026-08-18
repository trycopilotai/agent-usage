import type { HistoryPoint } from '../types';

type Props = { points: HistoryPoint[]; label: string };

// Inline SVG rather than a charting library. One less
// dependency for anyone vendoring this, and the shape of the
// data is simple enough that a library would hide more than
// it helped.
const WIDTH = 320;
const HEIGHT = 72;
const PAD = 4;

/** Never treat anything under this as a gap. */
const MIN_GAP_SECONDS = 15 * 60;

/**
 * A gap is judged against how often this series is actually
 * sampled, not against a fixed clock. A fixed threshold drew
 * every point as its own segment whenever collection ran
 * less often than the threshold, which turned a perfectly
 * good series into a row of dots.
 */
function gapThreshold(points: HistoryPoint[]): number {
  const deltas: number[] = [];
  for (let index = 1; index < points.length; index += 1) {
    deltas.push(points[index].collected_at - points[index - 1].collected_at);
  }
  if (deltas.length === 0) return MIN_GAP_SECONDS;
  deltas.sort((a, b) => a - b);
  const median = deltas[Math.floor(deltas.length / 2)];
  return Math.max(MIN_GAP_SECONDS, median * 3);
}

export function HistoryChart({ points, label }: Props) {
  if (points.length < 2) {
    return (
      <p className="muted chart__empty">
        Not enough readings yet to draw {label}. Run collect again.
      </p>
    );
  }

  const first = points[0].collected_at;
  const last = points[points.length - 1].collected_at;
  const span = Math.max(1, last - first);

  const x = (t: number) => PAD + ((t - first) / span) * (WIDTH - PAD * 2);
  const y = (p: number) => HEIGHT - PAD - (p / 100) * (HEIGHT - PAD * 2);

  // Break the line where readings stopped, so a gap in
  // collection is not drawn as a straight line through it.
  const threshold = gapThreshold(points);
  const segments: HistoryPoint[][] = [[]];
  points.forEach((point, index) => {
    const previous = points[index - 1];
    if (previous && point.collected_at - previous.collected_at > threshold) {
      segments.push([]);
    }
    segments[segments.length - 1].push(point);
  });

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`${label}: ${points.length} readings`}
    >
      <line x1={PAD} y1={y(100)} x2={WIDTH - PAD} y2={y(100)} className="chart__grid" />
      <line x1={PAD} y1={y(50)} x2={WIDTH - PAD} y2={y(50)} className="chart__grid" />
      {segments
        .filter((segment) => segment.length > 1)
        .map((segment, index) => (
          <polyline
            key={index}
            className="chart__line"
            points={segment
              .map((point) => `${x(point.collected_at)},${y(point.used_percent)}`)
              .join(' ')}
          />
        ))}
      {points.slice(-1).map((point) => (
        <circle
          key={point.collected_at}
          className="chart__head"
          cx={x(point.collected_at)}
          cy={y(point.used_percent)}
          r={3}
        />
      ))}
    </svg>
  );
}
