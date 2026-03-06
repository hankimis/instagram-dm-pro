import AnimateOnScroll from "./AnimateOnScroll";

export default function AppPreview() {
  return (
    <section className="px-6 py-24">
      <div className="max-w-5xl mx-auto">
        <AnimateOnScroll>
          <h2 className="text-3xl md:text-4xl font-bold text-center mb-4">
            직관적인 대시보드
          </h2>
          <p className="text-center text-lg mb-12 max-w-2xl mx-auto" style={{ color: "var(--gray-700)" }}>
            한 화면에서 크롤링, DM 발송, 계정 관리까지 모두 가능합니다
          </p>
        </AnimateOnScroll>

        <AnimateOnScroll delay={0.2}>
          <div className="mockup-window max-w-4xl mx-auto" style={{ animation: "float 6s ease-in-out infinite" }}>
            <div className="mockup-titlebar">
              <div className="mockup-dot" style={{ background: "#ff5f57" }} />
              <div className="mockup-dot" style={{ background: "#febc2e" }} />
              <div className="mockup-dot" style={{ background: "#28c840" }} />
              <span className="ml-3 text-xs" style={{ color: "#888" }}>Instagram DM Pro</span>
            </div>
            <div className="mockup-content">
              <div className="grid grid-cols-3 gap-4 mb-4">
                <div className="rounded-lg p-4" style={{ background: "rgba(26,115,232,0.15)" }}>
                  <div className="text-xs mb-1" style={{ color: "#888" }}>수집된 유저</div>
                  <div className="text-2xl font-bold text-white">2,847</div>
                </div>
                <div className="rounded-lg p-4" style={{ background: "rgba(40,200,64,0.15)" }}>
                  <div className="text-xs mb-1" style={{ color: "#888" }}>발송 완료</div>
                  <div className="text-2xl font-bold text-white">1,523</div>
                </div>
                <div className="rounded-lg p-4" style={{ background: "rgba(254,188,46,0.15)" }}>
                  <div className="text-xs mb-1" style={{ color: "#888" }}>응답률</div>
                  <div className="text-2xl font-bold text-white">12.4%</div>
                </div>
              </div>
              <div className="space-y-2">
                {[85, 60, 35].map((w, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full" style={{ background: `rgba(26,115,232,${0.3 + i * 0.2})` }} />
                    <div
                      className="h-3 rounded-full"
                      style={{
                        width: `${w}%`,
                        background: `linear-gradient(90deg, rgba(26,115,232,0.6), rgba(118,75,162,0.6))`,
                      }}
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </AnimateOnScroll>
      </div>
    </section>
  );
}
