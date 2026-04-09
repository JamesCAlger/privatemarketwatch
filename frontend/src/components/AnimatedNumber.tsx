'use client';

import { useEffect, useRef, useState } from 'react';

interface AnimatedNumberProps {
  value: number;
  duration?: number;
  formatter: (n: number) => string;
  /** When provided, animation waits until inView is true. */
  inView?: boolean;
}

export default function AnimatedNumber({ value, duration = 2000, formatter, inView }: AnimatedNumberProps) {
  const [display, setDisplay] = useState(formatter(0));
  const hasAnimated = useRef(false);

  // If no inView prop provided, animate immediately (backwards-compatible)
  const shouldAnimate = inView ?? true;

  useEffect(() => {
    if (hasAnimated.current || !shouldAnimate) return;
    hasAnimated.current = true;

    const start = performance.now();

    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic for a nice deceleration
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(eased * value);
      setDisplay(formatter(current));
      if (progress < 1) {
        requestAnimationFrame(tick);
      }
    }

    requestAnimationFrame(tick);
  }, [value, duration, formatter, shouldAnimate]);

  return <span>{display}</span>;
}
