"use client";

import { useEffect, useRef, useState } from "react";

function useCountUp(end: number, duration = 2000) {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started.current) {
          started.current = true;
          const startTime = performance.now();
          const animate = (now: number) => {
            const progress = Math.min((now - startTime) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            setCount(Math.round(eased * end));
            if (progress < 1) requestAnimationFrame(animate);
          };
          requestAnimationFrame(animate);
        }
      },
      { threshold: 0.5 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [end, duration]);

  return { count, ref };
}

const stats = [
  { value: 10000, suffix: "+", label: "일일 크롤링 가능 유저" },
  { value: 500, suffix: "+", label: "일일 DM 발송 가능" },
  { value: 10, suffix: "개", label: "동시 계정 운영" },
  { value: 99, suffix: "%", label: "발송 성공률" },
];

export default function Stats() {
  return (
    <section className="px-6 py-20" style={{ background: "var(--gray-50)" }}>
      <div className="max-w-5xl mx-auto">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map((stat, i) => (
            <StatItem key={i} {...stat} />
          ))}
        </div>
      </div>
    </section>
  );
}

function StatItem({ value, suffix, label }: { value: number; suffix: string; label: string }) {
  const { count, ref } = useCountUp(value);
  return (
    <div ref={ref} className="text-center">
      <div className="stat-number">
        {count.toLocaleString()}{suffix}
      </div>
      <p className="mt-2 text-sm font-medium" style={{ color: "var(--gray-700)" }}>
        {label}
      </p>
    </div>
  );
}
