'use client';

import { useCallback, useRef, useState } from 'react';

/**
 * Returns [callbackRef, inView] — attach callbackRef to a DOM element's
 * ref prop and inView flips to true once the element enters the viewport.
 * Fires only once (no re-trigger on scroll back).
 */
export function useInView<T extends Element = HTMLDivElement>(
  threshold = 0.15,
): [React.RefCallback<T>, boolean] {
  const [inView, setInView] = useState(false);
  const observerRef = useRef<IntersectionObserver | null>(null);

  const callbackRef = useCallback(
    (node: T | null) => {
      // Clean up previous observer
      if (observerRef.current) {
        observerRef.current.disconnect();
        observerRef.current = null;
      }

      if (!node || inView) return;

      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) {
            setInView(true);
            observer.disconnect();
          }
        },
        { threshold },
      );

      observer.observe(node);
      observerRef.current = observer;
    },
    [threshold, inView],
  );

  return [callbackRef, inView];
}
