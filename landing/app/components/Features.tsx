import AnimateOnScroll from "./AnimateOnScroll";

const features = [
  {
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="11" cy="11" r="8" />
        <path d="M21 21l-4.35-4.35" />
        <path d="M11 8v6M8 11h6" />
      </svg>
    ),
    title: "해시태그 크롤링",
    description:
      "원하는 해시태그에서 타겟 유저를 자동으로 수집합니다. 수천 명의 잠재 고객을 몇 번의 클릭으로 확보하세요.",
  },
  {
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
        <path d="M8 10h.01M12 10h.01M16 10h.01" />
      </svg>
    ),
    title: "스마트 DM 발송",
    description:
      "오타 시뮬레이션과 릴스 브라우징으로 사람처럼 자연스럽게 DM을 발송합니다. 봇 탐지를 우회하는 안전한 발송.",
  },
  {
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
      </svg>
    ),
    title: "멀티 계정 운영",
    description:
      "여러 계정을 동시에 운영하고, 대상을 자동 분배합니다. Chrome 창이 격자로 정렬되어 한눈에 관리할 수 있습니다.",
  },
  {
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    ),
    title: "안전한 운영",
    description:
      "일일/시간당 발송 한도, 차단 자동 감지, 즉시 중단 기능으로 계정을 안전하게 보호합니다.",
  },
  {
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="3" width="7" height="7" />
        <rect x="14" y="3" width="7" height="7" />
        <rect x="3" y="14" width="7" height="7" />
        <rect x="14" y="14" width="7" height="7" />
      </svg>
    ),
    title: "멀티 템플릿",
    description:
      "여러 메시지 템플릿을 등록하고 랜덤으로 발송합니다. 다양한 메시지로 자연스러운 소통을 만드세요.",
  },
  {
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
    title: "스케줄링",
    description:
      "발송 시간, 간격, 릴스 탐색 시간을 세밀하게 설정하세요. 최적의 타이밍에 맞춰 자동 발송됩니다.",
  },
];

export default function Features() {
  return (
    <section className="px-6 py-24" style={{ background: "var(--gray-50)" }}>
      <div className="max-w-6xl mx-auto">
        <AnimateOnScroll>
          <h2 className="text-3xl md:text-4xl font-bold text-center mb-4">
            왜 Instagram DM Pro인가요?
          </h2>
          <p
            className="text-center text-lg mb-16 max-w-2xl mx-auto"
            style={{ color: "var(--gray-700)" }}
          >
            복잡한 인스타그램 마케팅을 심플하게 자동화합니다
          </p>
        </AnimateOnScroll>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map((feature, i) => (
            <AnimateOnScroll key={i} delay={i * 0.08}>
              <div className="feature-card bg-white h-full">
                <div
                  className="w-14 h-14 rounded-xl flex items-center justify-center mb-5"
                  style={{ background: "var(--primary-light)", color: "var(--primary)" }}
                >
                  {feature.icon}
                </div>
                <h3 className="text-xl font-semibold mb-3">{feature.title}</h3>
                <p style={{ color: "var(--gray-700)" }} className="leading-relaxed">
                  {feature.description}
                </p>
              </div>
            </AnimateOnScroll>
          ))}
        </div>
      </div>
    </section>
  );
}
