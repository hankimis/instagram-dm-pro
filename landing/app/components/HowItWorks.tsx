import AnimateOnScroll from "./AnimateOnScroll";

const steps = [
  {
    num: "01",
    title: "프로그램 다운로드",
    description: "Windows 또는 macOS용 프로그램을 다운로드하고 실행하세요.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
    ),
  },
  {
    num: "02",
    title: "인스타그램 계정 연동",
    description: "Chrome 브라우저를 통해 안전하게 인스타그램 계정에 로그인합니다.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    ),
  },
  {
    num: "03",
    title: "해시태그 설정 & 크롤링",
    description: "타겟 해시태그를 입력하면 관련 유저를 자동으로 수집합니다.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="11" cy="11" r="8" />
        <path d="M21 21l-4.35-4.35" />
      </svg>
    ),
  },
  {
    num: "04",
    title: "DM 템플릿 작성 & 발송",
    description: "메시지 템플릿을 만들고 시작 버튼을 누르면 자동으로 발송됩니다.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="22" y1="2" x2="11" y2="13" />
        <polygon points="22 2 15 22 11 13 2 9 22 2" />
      </svg>
    ),
  },
];

export default function HowItWorks() {
  return (
    <section className="px-6 py-24">
      <div className="max-w-6xl mx-auto">
        <AnimateOnScroll>
          <h2 className="text-3xl md:text-4xl font-bold text-center mb-4">
            간단한 4단계로 시작
          </h2>
          <p className="text-center text-lg mb-16 max-w-2xl mx-auto" style={{ color: "var(--gray-700)" }}>
            복잡한 설정 없이, 다운로드하고 바로 사용하세요
          </p>
        </AnimateOnScroll>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {steps.map((step, i) => (
            <AnimateOnScroll key={i} delay={i * 0.1}>
              <div className="step-card text-center">
                <div
                  className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-5"
                  style={{ background: "var(--primary-light)", color: "var(--primary)" }}
                >
                  {step.icon}
                </div>
                <div
                  className="text-xs font-bold tracking-wider mb-3"
                  style={{ color: "var(--primary)" }}
                >
                  STEP {step.num}
                </div>
                <h3 className="text-lg font-semibold mb-2">{step.title}</h3>
                <p className="text-sm leading-relaxed" style={{ color: "var(--gray-700)" }}>
                  {step.description}
                </p>
              </div>
            </AnimateOnScroll>
          ))}
        </div>
      </div>
    </section>
  );
}
