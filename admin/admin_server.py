"""
어드민 서버 - 라이선스 발급/관리, 고객사 관리
웹 UI 내장 (로그인 -> 대시보드 -> 고객사/라이선스 관리)

실행: python start_admin.py
접속: http://localhost:9090
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# ── 플랜별 기본값 ──
PLAN_PRESETS = {
    "basic": {
        "label": "Basic",
        "max_crawl_accounts": 1,
        "max_dm_accounts": 1,
        "max_daily_dm": 50,
        "max_hashtags": 5,
        "can_schedule": False,
        "can_analyze": False,
        "can_export": False,
    },
    "pro": {
        "label": "Pro",
        "max_crawl_accounts": 3,
        "max_dm_accounts": 3,
        "max_daily_dm": 200,
        "max_hashtags": 20,
        "can_schedule": True,
        "can_analyze": True,
        "can_export": True,
    },
    "enterprise": {
        "label": "Enterprise",
        "max_crawl_accounts": 10,
        "max_dm_accounts": 5,
        "max_daily_dm": 9999,
        "max_hashtags": 9999,
        "can_schedule": True,
        "can_analyze": True,
        "can_export": True,
    },
}

# ── DB 설정 ──
# Supabase/PostgreSQL: DATABASE_URL 환경변수 사용
# 로컬 테스트: SQLite 폴백
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL:
    # Supabase pooler 등 PostgreSQL 연결 시 SSL 필요
    if "sslmode" not in DATABASE_URL:
        DATABASE_URL += "?sslmode=require" if "?" not in DATABASE_URL else "&sslmode=require"
    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
else:
    DB_PATH = os.environ.get("DATABASE_PATH", "admin_data.db")
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
AdminSession = sessionmaker(bind=engine)
Base = declarative_base()


# ── 모델 ──

class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_name = Column(String, nullable=False)
    contact_name = Column(String)
    contact_email = Column(String)
    contact_phone = Column(String)
    plan = Column(String, default="basic")
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class License(Base):
    __tablename__ = "licenses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    license_key = Column(String, unique=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    machine_id = Column(String)
    plan = Column(String, default="basic")
    max_crawl_accounts = Column(Integer, default=1)
    max_dm_accounts = Column(Integer, default=1)
    max_daily_dm = Column(Integer, default=50)
    max_hashtags = Column(Integer, default=5)
    can_schedule = Column(Boolean, default=False)
    can_analyze = Column(Boolean, default=False)
    can_export = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    activated_at = Column(DateTime)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)


# ── 헬퍼 ──

def get_db():
    db = AdminSession()
    try:
        yield db
    finally:
        db.close()


def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def generate_license_key() -> str:
    parts = [secrets.token_hex(2).upper() for _ in range(4)]
    return "-".join(parts)


def license_to_dict(lic, customer_name: str = "?") -> dict:
    now = datetime.utcnow()
    is_expired = lic.expires_at and lic.expires_at < now
    days_left = (lic.expires_at - now).days if lic.expires_at and not is_expired else 0
    return {
        "id": lic.id,
        "license_key": lic.license_key,
        "customer_id": lic.customer_id,
        "customer_name": customer_name,
        "plan": lic.plan,
        "is_active": lic.is_active,
        "is_expired": is_expired,
        "days_left": max(days_left, 0),
        "machine_id": lic.machine_id,
        "max_crawl_accounts": lic.max_crawl_accounts,
        "max_dm_accounts": lic.max_dm_accounts,
        "max_daily_dm": lic.max_daily_dm,
        "max_hashtags": lic.max_hashtags,
        "can_schedule": lic.can_schedule,
        "can_analyze": lic.can_analyze,
        "can_export": lic.can_export,
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
        "activated_at": lic.activated_at.isoformat() if lic.activated_at else None,
        "created_at": lic.created_at.isoformat() if lic.created_at else None,
    }


# ── FastAPI 앱 ──

app = FastAPI(title="Instagram Service Admin", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ── 스키마 ──

class SignupRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class CustomerCreate(BaseModel):
    company_name: str
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    plan: str = "basic"
    duration_days: int = 365
    notes: str = ""
    auto_license: bool = True


class LicenseCreate(BaseModel):
    customer_id: int
    plan: str = "basic"
    duration_days: int = 365


class LicenseActivateRequest(BaseModel):
    license_key: str
    machine_id: str


class LicenseVerifyRequest(BaseModel):
    license_key: str
    machine_id: str


# ── 초기 관리자 생성 ──

@app.on_event("startup")
def create_default_admin():
    db = AdminSession()
    if not db.query(AdminUser).filter_by(is_admin=True).first():
        admin = AdminUser(
            email="admin@admin.com",
            password_hash=hash_password("admin1234"),
            name="관리자",
            is_admin=True,
        )
        db.add(admin)
        db.commit()
    db.close()


# ── 플랜 정보 API ──

@app.get("/api/plans")
def get_plans():
    return PLAN_PRESETS


# ── 웹 UI ──

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Instagram Service Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;color:#333}
.login-wrap{display:flex;justify-content:center;align-items:center;min-height:100vh}
.login-box{background:#fff;padding:40px;border-radius:12px;box-shadow:0 2px 20px rgba(0,0,0,.1);width:380px}
.login-box h1{text-align:center;margin-bottom:8px;color:#4f46e5;font-size:24px}
.login-box p{text-align:center;color:#888;margin-bottom:24px;font-size:14px}
.form-group{margin-bottom:16px}
.form-group label{display:block;font-size:13px;font-weight:600;margin-bottom:4px;color:#555}
.form-group input,.form-group select,.form-group textarea{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:8px;font-size:14px;outline:none}
.form-group input:focus,.form-group select:focus{border-color:#4f46e5}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.btn{width:100%;padding:12px;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer}
.btn-primary{background:#4f46e5;color:#fff}.btn-primary:hover{background:#4338ca}
.btn-danger{background:#ef4444;color:#fff}
.btn-sm{width:auto;padding:6px 16px;font-size:13px}
.btn-outline{background:transparent;border:1px solid #4f46e5;color:#4f46e5}
.btn-green{background:#22c55e;color:#fff}
.error{color:#ef4444;font-size:13px;text-align:center;margin-top:8px}
.success{color:#22c55e;font-size:13px;text-align:center;margin-top:8px}
.tabs{display:flex;gap:0;background:#fff;border-bottom:2px solid #e5e7eb}
.tab{padding:14px 28px;cursor:pointer;font-weight:600;color:#888;border-bottom:2px solid transparent;margin-bottom:-2px}
.tab.active{color:#4f46e5;border-bottom-color:#4f46e5}.tab:hover{color:#4f46e5}
header{background:#4f46e5;color:#fff;padding:0 24px;display:flex;align-items:center;justify-content:space-between;height:56px}
header h1{font-size:18px}
header .user-info{font-size:14px;display:flex;align-items:center;gap:12px}
header .logout-btn{background:rgba(255,255,255,.2);border:none;color:#fff;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px}
.container{max-width:1200px;margin:0 auto;padding:24px}
.card{background:#fff;border-radius:12px;box-shadow:0 1px 8px rgba(0,0,0,.06);padding:24px;margin-bottom:20px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
.stat-card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 8px rgba(0,0,0,.06);text-align:center}
.stat-card .num{font-size:32px;font-weight:700;color:#4f46e5}
.stat-card .label{font-size:13px;color:#888;margin-top:4px}
table{width:100%;border-collapse:collapse}
th,td{padding:12px 16px;text-align:left;border-bottom:1px solid #f0f0f0;font-size:14px}
th{font-weight:600;color:#888;font-size:12px;text-transform:uppercase}
tr:hover{background:#f8f9ff}
.badge{padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;display:inline-block}
.badge-green{background:#dcfce7;color:#16a34a}
.badge-red{background:#fee2e2;color:#dc2626}
.badge-blue{background:#dbeafe;color:#2563eb}
.badge-yellow{background:#fef9c3;color:#a16207}
.badge-purple{background:#f3e8ff;color:#7c3aed}
.badge-gray{background:#f3f4f6;color:#6b7280}
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.4);display:flex;justify-content:center;align-items:center;z-index:100}
.modal{background:#fff;border-radius:12px;padding:32px;width:520px;max-height:90vh;overflow-y:auto}
.modal h2{margin-bottom:20px;font-size:20px}
.modal-actions{display:flex;gap:8px;margin-top:20px;justify-content:flex-end}
.license-key{font-family:monospace;font-size:18px;font-weight:700;color:#4f46e5;background:#f0f0ff;padding:12px 20px;border-radius:8px;text-align:center;margin:16px 0;letter-spacing:2px;user-select:all}
.empty{text-align:center;padding:40px;color:#aaa}
.hidden{display:none!important}
.link{color:#4f46e5;cursor:pointer;text-decoration:underline}
.detail-grid{display:grid;grid-template-columns:140px 1fr;gap:8px 16px;font-size:14px;margin-bottom:20px}
.detail-grid b{color:#555}
.plan-compare{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0}
.plan-card{border:2px solid #e5e7eb;border-radius:10px;padding:16px;text-align:center;cursor:pointer;transition:.2s}
.plan-card:hover{border-color:#4f46e5}
.plan-card.selected{border-color:#4f46e5;background:#f0f0ff}
.plan-card h4{font-size:16px;margin-bottom:8px}
.plan-card ul{list-style:none;font-size:12px;color:#666;line-height:1.8;text-align:left}
.plan-card ul li::before{content:"";margin-right:4px}
.feature-tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px}
.feature-on{background:#dcfce7;color:#16a34a}
.feature-off{background:#fee2e2;color:#dc2626}
.separator{border:none;border-top:1px solid #e5e7eb;margin:16px 0}
</style>
</head>
<body>

<!-- 로그인 -->
<div id="loginPage" class="login-wrap">
  <div class="login-box">
    <h1>Instagram Service</h1>
    <p>어드민 관리자 로그인</p>
    <div id="loginForm">
      <div class="form-group"><label>이메일</label><input type="email" id="loginEmail" value="admin@admin.com"/></div>
      <div class="form-group"><label>비밀번호</label><input type="password" id="loginPassword" value="admin1234"/></div>
      <button class="btn btn-primary" onclick="doLogin()">로그인</button>
      <div id="loginError" class="error"></div>
      <p style="text-align:center;margin-top:16px;font-size:13px;color:#888">계정이 없나요? <span class="link" onclick="showSignup()">회원가입</span></p>
    </div>
    <div id="signupForm" class="hidden">
      <div class="form-group"><label>이름</label><input id="signupName"/></div>
      <div class="form-group"><label>이메일</label><input type="email" id="signupEmail"/></div>
      <div class="form-group"><label>비밀번호</label><input type="password" id="signupPassword"/></div>
      <button class="btn btn-primary" onclick="doSignup()">회원가입</button>
      <div id="signupMsg" class="error"></div>
      <p style="text-align:center;margin-top:16px;font-size:13px;color:#888">이미 계정이 있나요? <span class="link" onclick="showLogin()">로그인</span></p>
    </div>
  </div>
</div>

<!-- 메인 -->
<div id="mainPage" class="hidden">
  <header>
    <h1>Instagram Service Admin</h1>
    <div class="user-info"><span id="userName"></span><button class="logout-btn" onclick="doLogout()">로그아웃</button></div>
  </header>
  <div class="container">
    <div class="tabs">
      <div class="tab active" data-tab="dashboard" onclick="switchTab('dashboard')">대시보드</div>
      <div class="tab" data-tab="customers" onclick="switchTab('customers')">고객사 관리</div>
      <div class="tab" data-tab="licenses" onclick="switchTab('licenses')">라이선스 관리</div>
    </div>

    <!-- 대시보드 -->
    <div id="tab-dashboard" class="card">
      <div class="stats" id="statsCards"></div>
      <h3 style="margin-bottom:12px">최근 발급 라이선스</h3>
      <table><thead><tr><th>키</th><th>고객사</th><th>플랜</th><th>만료일</th><th>남은일</th><th>상태</th></tr></thead>
      <tbody id="recentLicenses"></tbody></table>
    </div>

    <!-- 고객사 -->
    <div id="tab-customers" class="card hidden">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <h3>고객사 목록</h3>
        <button class="btn btn-primary btn-sm" onclick="showAddCustomer()">+ 고객사 등록</button>
      </div>
      <table><thead><tr><th>업체명</th><th>담당자</th><th>연락처</th><th>플랜</th><th>라이선스</th><th>등록일</th><th>관리</th></tr></thead>
      <tbody id="customerList"></tbody></table>
      <div id="customerEmpty" class="empty hidden">등록된 고객사가 없습니다.</div>
    </div>

    <!-- 라이선스 -->
    <div id="tab-licenses" class="card hidden">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <h3>라이선스 목록</h3>
        <button class="btn btn-primary btn-sm" onclick="showAddLicense()">+ 라이선스 발급</button>
      </div>
      <table><thead><tr><th>키</th><th>고객사</th><th>플랜</th><th>만료일</th><th>남은일</th><th>기기</th><th>상태</th><th>관리</th></tr></thead>
      <tbody id="licenseList"></tbody></table>
      <div id="licenseEmpty" class="empty hidden">발급된 라이선스가 없습니다.</div>
    </div>
  </div>
</div>

<!-- 고객사 추가 모달 -->
<div id="addCustomerModal" class="modal-overlay hidden">
  <div class="modal">
    <h2>고객사 등록</h2>
    <div class="form-group"><label>업체명 *</label><input id="cName"/></div>
    <div class="form-row">
      <div class="form-group"><label>담당자명</label><input id="cContact"/></div>
      <div class="form-group"><label>전화번호</label><input id="cPhone"/></div>
    </div>
    <div class="form-group"><label>이메일</label><input id="cEmail"/></div>
    <hr class="separator">
    <label style="font-size:13px;font-weight:600;color:#555;margin-bottom:8px;display:block">플랜 선택</label>
    <div class="plan-compare" id="planCards"></div>
    <input type="hidden" id="cPlan" value="basic"/>
    <div class="form-row">
      <div class="form-group"><label>유효기간</label>
        <select id="cDuration">
          <option value="30">1개월 (30일)</option>
          <option value="90">3개월 (90일)</option>
          <option value="180">6개월 (180일)</option>
          <option value="365" selected>1년 (365일)</option>
          <option value="730">2년 (730일)</option>
        </select>
      </div>
      <div class="form-group"><label>라이선스 자동 발급</label>
        <select id="cAutoLicense"><option value="1" selected>등록 시 바로 발급</option><option value="0">나중에 수동 발급</option></select>
      </div>
    </div>
    <div class="form-group"><label>메모</label><textarea id="cNotes" rows="2"></textarea></div>
    <div class="modal-actions">
      <button class="btn btn-outline btn-sm" onclick="closeModal('addCustomerModal')">취소</button>
      <button class="btn btn-primary btn-sm" onclick="addCustomer()">등록</button>
    </div>
  </div>
</div>

<!-- 라이선스 발급 모달 -->
<div id="addLicenseModal" class="modal-overlay hidden">
  <div class="modal">
    <h2>라이선스 발급</h2>
    <div class="form-group"><label>고객사 *</label><select id="lCustomer"></select></div>
    <label style="font-size:13px;font-weight:600;color:#555;margin-bottom:8px;display:block">플랜 선택</label>
    <div class="plan-compare" id="planCards2"></div>
    <input type="hidden" id="lPlan" value="basic"/>
    <div class="form-group"><label>유효기간</label>
      <select id="lDays">
        <option value="30">1개월</option><option value="90">3개월</option>
        <option value="180">6개월</option><option value="365" selected>1년</option><option value="730">2년</option>
      </select>
    </div>
    <div class="modal-actions">
      <button class="btn btn-outline btn-sm" onclick="closeModal('addLicenseModal')">취소</button>
      <button class="btn btn-primary btn-sm" onclick="addLicense()">발급</button>
    </div>
  </div>
</div>

<!-- 라이선스 발급 결과 -->
<div id="licenseResultModal" class="modal-overlay hidden">
  <div class="modal" style="text-align:center">
    <h2>라이선스 발급 완료</h2>
    <p style="color:#888;margin-bottom:8px">아래 키를 고객사에 전달하세요</p>
    <div class="license-key" id="newLicenseKey"></div>
    <p style="font-size:13px;color:#888">만료일: <span id="newLicenseExpiry"></span></p>
    <div class="modal-actions" style="justify-content:center">
      <button class="btn btn-primary btn-sm" onclick="copyKey()">키 복사</button>
      <button class="btn btn-outline btn-sm" onclick="closeModal('licenseResultModal')">닫기</button>
    </div>
  </div>
</div>

<!-- 고객사 상세 모달 -->
<div id="customerDetailModal" class="modal-overlay hidden">
  <div class="modal"><h2 id="detailCompanyName"></h2><div id="detailContent"></div>
    <div class="modal-actions"><button class="btn btn-outline btn-sm" onclick="closeModal('customerDetailModal')">닫기</button></div>
  </div>
</div>

<!-- 라이선스 상세 모달 -->
<div id="licenseDetailModal" class="modal-overlay hidden">
  <div class="modal"><h2>라이선스 상세 정보</h2><div id="licenseDetailContent"></div>
    <div class="modal-actions"><button class="btn btn-outline btn-sm" onclick="closeModal('licenseDetailModal')">닫기</button></div>
  </div>
</div>

<script>
const API='';
let currentUser=null;
const PLANS = {
    basic:{label:'Basic',max_crawl_accounts:1,max_dm_accounts:1,max_daily_dm:50,max_hashtags:5,can_schedule:false,can_analyze:false,can_export:false},
    pro:{label:'Pro',max_crawl_accounts:3,max_dm_accounts:3,max_daily_dm:200,max_hashtags:20,can_schedule:true,can_analyze:true,can_export:true},
    enterprise:{label:'Enterprise',max_crawl_accounts:10,max_dm_accounts:5,max_daily_dm:9999,max_hashtags:9999,can_schedule:true,can_analyze:true,can_export:true}
};

function planBadge(plan) {
    const colors = {basic:'badge-blue',pro:'badge-purple',enterprise:'badge-yellow'};
    const labels = {basic:'Basic',pro:'Pro',enterprise:'Enterprise'};
    return `<span class="badge ${colors[plan]||'badge-gray'}">${labels[plan]||plan}</span>`;
}

function statusBadge(l) {
    if (!l.is_active) return '<span class="badge badge-red">비활성</span>';
    if (l.is_expired) return '<span class="badge badge-red">만료</span>';
    if (l.days_left <= 30) return `<span class="badge badge-yellow">만료 ${l.days_left}일전</span>`;
    return '<span class="badge badge-green">활성</span>';
}

function featureTag(on, label) {
    return `<span class="feature-tag ${on?'feature-on':'feature-off'}">${on?'O':'X'} ${label}</span>`;
}

function renderPlanCards(containerId, hiddenInputId) {
    const el = document.getElementById(containerId);
    el.innerHTML = Object.entries(PLANS).map(([key,p]) => `
        <div class="plan-card ${key==='basic'?'selected':''}" data-plan="${key}" onclick="selectPlan('${containerId}','${hiddenInputId}','${key}')">
            <h4>${p.label}</h4>
            <ul>
                <li>크롤링 계정 ${p.max_crawl_accounts}개</li>
                <li>DM 계정 ${p.max_dm_accounts}개</li>
                <li>일일 DM ${p.max_daily_dm >= 9999?'무제한':p.max_daily_dm+'건'}</li>
                <li>해시태그 ${p.max_hashtags >= 9999?'무제한':p.max_hashtags+'개'}</li>
                <li>${p.can_schedule?'O':'X'} 스케줄링</li>
                <li>${p.can_analyze?'O':'X'} 유저 분석</li>
                <li>${p.can_export?'O':'X'} Excel 내보내기</li>
            </ul>
        </div>`).join('');
}

function selectPlan(containerId, hiddenInputId, plan) {
    document.getElementById(hiddenInputId).value = plan;
    document.querySelectorAll(`#${containerId} .plan-card`).forEach(c => c.classList.toggle('selected', c.dataset.plan===plan));
}

// ── 로그인 ──
function showSignup(){document.getElementById('loginForm').classList.add('hidden');document.getElementById('signupForm').classList.remove('hidden')}
function showLogin(){document.getElementById('signupForm').classList.add('hidden');document.getElementById('loginForm').classList.remove('hidden')}

async function doLogin(){
    const email=document.getElementById('loginEmail').value,pw=document.getElementById('loginPassword').value;
    try{const r=await fetch(API+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password:pw})});
    const d=await r.json();if(r.ok&&d.ok){currentUser=d.user;enterDashboard()}else{document.getElementById('loginError').textContent=d.detail||'로그인 실패'}}
    catch(e){document.getElementById('loginError').textContent='서버 연결 실패'}}

async function doSignup(){
    const name=document.getElementById('signupName').value,email=document.getElementById('signupEmail').value,pw=document.getElementById('signupPassword').value;
    const m=document.getElementById('signupMsg');
    try{const r=await fetch(API+'/api/auth/signup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password:pw,name})});
    const d=await r.json();if(r.ok&&d.ok){m.className='success';m.textContent='회원가입 완료!';setTimeout(showLogin,1500)}else{m.className='error';m.textContent=d.detail||'가입 실패'}}
    catch(e){m.className='error';m.textContent='서버 연결 실패'}}

function doLogout(){currentUser=null;document.getElementById('mainPage').classList.add('hidden');document.getElementById('loginPage').classList.remove('hidden')}

function enterDashboard(){
    document.getElementById('loginPage').classList.add('hidden');
    document.getElementById('mainPage').classList.remove('hidden');
    document.getElementById('userName').textContent=currentUser.name||currentUser.email;
    loadDashboard();
}

// ── 탭 ──
function switchTab(name){
    document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
    ['dashboard','customers','licenses'].forEach(n=>document.getElementById('tab-'+n).classList.toggle('hidden',n!==name));
    if(name==='dashboard')loadDashboard();if(name==='customers')loadCustomers();if(name==='licenses')loadLicenses();
}

// ── 대시보드 ──
async function loadDashboard(){
    const[customers,licenses]=await Promise.all([fetch(API+'/api/customers').then(r=>r.json()),fetch(API+'/api/licenses').then(r=>r.json())]);
    const active=licenses.filter(l=>l.is_active&&!l.is_expired).length;
    const expiring=licenses.filter(l=>l.is_active&&!l.is_expired&&l.days_left<=30).length;
    document.getElementById('statsCards').innerHTML=`
        <div class="stat-card"><div class="num">${customers.length}</div><div class="label">등록 고객사</div></div>
        <div class="stat-card"><div class="num">${licenses.length}</div><div class="label">전체 라이선스</div></div>
        <div class="stat-card"><div class="num">${active}</div><div class="label">활성 라이선스</div></div>
        <div class="stat-card"><div class="num" style="color:${expiring?'#ef4444':'#4f46e5'}">${expiring}</div><div class="label">만료 임박 (30일 이내)</div></div>`;
    const recent=licenses.slice(0,8);
    document.getElementById('recentLicenses').innerHTML=recent.length?recent.map(l=>`<tr>
        <td style="font-family:monospace;font-size:12px" class="link" onclick="showLicenseDetail(${l.id})">${l.license_key}</td>
        <td>${l.customer_name}</td><td>${planBadge(l.plan)}</td>
        <td>${l.expires_at?l.expires_at.split('T')[0]:'-'}</td>
        <td>${l.is_expired?'-':l.days_left+'일'}</td>
        <td>${statusBadge(l)}</td></tr>`).join(''):'<tr><td colspan="6" class="empty">아직 발급된 라이선스가 없습니다.</td></tr>';
}

// ── 고객사 ──
let _allLicenses=[];
async function loadCustomers(){
    const[data,lics]=await Promise.all([fetch(API+'/api/customers').then(r=>r.json()),fetch(API+'/api/licenses').then(r=>r.json())]);
    _allLicenses=lics;
    const el=document.getElementById('customerList'),empty=document.getElementById('customerEmpty');
    if(!data.length){el.innerHTML='';empty.classList.remove('hidden');return}
    empty.classList.add('hidden');
    el.innerHTML=data.map(c=>{
        const cLics=lics.filter(l=>l.customer_id===c.id);
        const activeCount=cLics.filter(l=>l.is_active&&!l.is_expired).length;
        return `<tr>
        <td><span class="link" onclick="showCustomerDetail(${c.id})">${c.company_name}</span></td>
        <td>${c.contact_name||'-'}</td>
        <td>${c.contact_email||c.contact_phone||'-'}</td>
        <td>${planBadge(c.plan)}</td>
        <td>${activeCount}/${cLics.length}개</td>
        <td>${c.created_at?c.created_at.split('T')[0]:'-'}</td>
        <td><button class="btn btn-outline btn-sm" onclick="showCustomerDetail(${c.id})">상세</button></td></tr>`}).join('');
}

function showAddCustomer(){renderPlanCards('planCards','cPlan');document.getElementById('addCustomerModal').classList.remove('hidden')}

async function addCustomer(){
    const body={
        company_name:document.getElementById('cName').value,
        contact_name:document.getElementById('cContact').value,
        contact_email:document.getElementById('cEmail').value,
        contact_phone:document.getElementById('cPhone').value,
        plan:document.getElementById('cPlan').value,
        duration_days:parseInt(document.getElementById('cDuration').value),
        notes:document.getElementById('cNotes').value,
        auto_license:document.getElementById('cAutoLicense').value==='1'
    };
    if(!body.company_name){alert('업체명을 입력해주세요.');return}
    const r=await fetch(API+'/api/customers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    closeModal('addCustomerModal');
    ['cName','cContact','cEmail','cPhone','cNotes'].forEach(id=>document.getElementById(id).value='');
    if(d.license_key){
        document.getElementById('newLicenseKey').textContent=d.license_key;
        document.getElementById('newLicenseExpiry').textContent=d.expires_at?d.expires_at.split('T')[0]:'';
        document.getElementById('licenseResultModal').classList.remove('hidden');
    }
    loadCustomers();
}

async function showCustomerDetail(id){
    const data=await fetch(API+'/api/customers/'+id).then(r=>r.json());
    document.getElementById('detailCompanyName').textContent=data.company_name;
    const p=PLANS[data.plan]||{};
    let html=`<div class="detail-grid">
        <b>담당자</b><span>${data.contact_name||'-'}</span>
        <b>이메일</b><span>${data.contact_email||'-'}</span>
        <b>전화번호</b><span>${data.contact_phone||'-'}</span>
        <b>플랜</b><span>${planBadge(data.plan)}</span>
        <b>메모</b><span>${data.notes||'-'}</span>
    </div><hr class="separator"><h3 style="margin-bottom:12px">발급된 라이선스</h3>`;
    if(data.licenses&&data.licenses.length){
        html+='<table><thead><tr><th>키</th><th>플랜</th><th>만료일</th><th>남은일</th><th>상태</th></tr></thead><tbody>';
        data.licenses.forEach(l=>{
            const now=new Date(),exp=l.expires_at?new Date(l.expires_at):null;
            const expired=exp&&exp<now;const days=exp&&!expired?Math.ceil((exp-now)/86400000):0;
            html+=`<tr>
                <td style="font-family:monospace;font-size:12px" class="link" onclick="showLicenseDetail(${l.id})">${l.license_key}</td>
                <td>${planBadge(l.plan)}</td>
                <td>${l.expires_at?l.expires_at.split('T')[0]:'-'}</td>
                <td>${expired?'-':days+'일'}</td>
                <td>${!l.is_active?'<span class="badge badge-red">비활성</span>':expired?'<span class="badge badge-red">만료</span>':'<span class="badge badge-green">활성</span>'}</td></tr>`});
        html+='</tbody></table>';
    }else html+='<div class="empty">발급된 라이선스가 없습니다.</div>';
    document.getElementById('detailContent').innerHTML=html;
    document.getElementById('customerDetailModal').classList.remove('hidden');
}

// ── 라이선스 ──
async function loadLicenses(){
    const data=await fetch(API+'/api/licenses').then(r=>r.json());
    _allLicenses=data;
    const el=document.getElementById('licenseList'),empty=document.getElementById('licenseEmpty');
    if(!data.length){el.innerHTML='';empty.classList.remove('hidden');return}
    empty.classList.add('hidden');
    el.innerHTML=data.map(l=>`<tr>
        <td style="font-family:monospace;font-size:12px"><span class="link" onclick="showLicenseDetail(${l.id})">${l.license_key}</span></td>
        <td>${l.customer_name}</td><td>${planBadge(l.plan)}</td>
        <td>${l.expires_at?l.expires_at.split('T')[0]:'-'}</td>
        <td>${l.is_expired?'-':l.days_left+'일'}</td>
        <td style="font-size:11px;color:#888">${l.machine_id?l.machine_id.substring(0,12)+'...':'미활성화'}</td>
        <td>${statusBadge(l)}</td>
        <td>${l.is_active&&!l.is_expired?'<button class="btn btn-danger btn-sm" onclick="deactivateLicense('+l.id+')">비활성화</button>':'-'}</td></tr>`).join('');
}

function showLicenseDetail(id){
    const l=_allLicenses.find(x=>x.id===id);if(!l)return;
    const p=PLANS[l.plan]||{};
    document.getElementById('licenseDetailContent').innerHTML=`
        <div class="license-key">${l.license_key}</div>
        <div class="detail-grid">
            <b>고객사</b><span>${l.customer_name}</span>
            <b>플랜</b><span>${planBadge(l.plan)}</span>
            <b>상태</b><span>${statusBadge(l)}</span>
            <b>발급일</b><span>${l.created_at?l.created_at.split('T')[0]:'-'}</span>
            <b>만료일</b><span>${l.expires_at?l.expires_at.split('T')[0]:'-'}</span>
            <b>남은 기간</b><span>${l.is_expired?'만료됨':l.days_left+'일'}</span>
            <b>활성화일</b><span>${l.activated_at?l.activated_at.split('T')[0]:'미활성화'}</span>
            <b>기기 ID</b><span style="font-family:monospace;font-size:12px">${l.machine_id||'미등록'}</span>
        </div>
        <hr class="separator">
        <h3 style="margin-bottom:12px">기능 제한</h3>
        <div class="detail-grid">
            <b>크롤링 계정</b><span>최대 ${l.max_crawl_accounts}개</span>
            <b>DM 발송 계정</b><span>최대 ${l.max_dm_accounts}개</span>
            <b>일일 DM 한도</b><span>${l.max_daily_dm>=9999?'무제한':l.max_daily_dm+'건'}</span>
            <b>동시 해시태그</b><span>${l.max_hashtags>=9999?'무제한':l.max_hashtags+'개'}</span>
        </div>
        <div style="margin-top:8px">
            ${featureTag(l.can_schedule,'스케줄링')}
            ${featureTag(l.can_analyze,'유저 분석')}
            ${featureTag(l.can_export,'Excel 내보내기')}
        </div>`;
    document.getElementById('licenseDetailModal').classList.remove('hidden');
}

async function showAddLicense(){
    const customers=await fetch(API+'/api/customers').then(r=>r.json());
    const sel=document.getElementById('lCustomer');
    sel.innerHTML=customers.map(c=>`<option value="${c.id}">${c.company_name} (${c.plan})</option>`).join('');
    if(!customers.length){alert('먼저 고객사를 등록해주세요.');return}
    renderPlanCards('planCards2','lPlan');
    document.getElementById('addLicenseModal').classList.remove('hidden');
}

async function addLicense(){
    const body={customer_id:parseInt(document.getElementById('lCustomer').value),plan:document.getElementById('lPlan').value,duration_days:parseInt(document.getElementById('lDays').value)};
    const r=await fetch(API+'/api/licenses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();closeModal('addLicenseModal');
    if(d.ok){document.getElementById('newLicenseKey').textContent=d.license_key;document.getElementById('newLicenseExpiry').textContent=d.expires_at.split('T')[0];
    document.getElementById('licenseResultModal').classList.remove('hidden');loadLicenses()}
}

async function deactivateLicense(id){if(!confirm('이 라이선스를 비활성화하시겠습니까?'))return;await fetch(API+'/api/licenses/'+id+'/deactivate',{method:'PUT'});loadLicenses()}

function copyKey(){navigator.clipboard.writeText(document.getElementById('newLicenseKey').textContent);alert('라이선스 키가 복사되었습니다!')}
function closeModal(id){document.getElementById(id).classList.add('hidden')}
document.querySelectorAll('.modal-overlay').forEach(el=>{el.addEventListener('click',e=>{if(e.target===el)el.classList.add('hidden')})});
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def admin_page():
    return ADMIN_HTML


# ── 인증 API ──

@app.post("/api/auth/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    if db.query(AdminUser).filter_by(email=req.email).first():
        raise HTTPException(400, "이미 등록된 이메일입니다.")
    user = AdminUser(email=req.email, password_hash=hash_password(req.password), name=req.name)
    db.add(user)
    db.commit()
    return {"ok": True, "message": "회원가입 완료"}


@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter_by(email=req.email).first()
    if not user or user.password_hash != hash_password(req.password):
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다.")
    return {
        "ok": True,
        "user": {"id": user.id, "email": user.email, "name": user.name, "is_admin": user.is_admin},
    }


# ── 고객사 API ──

@app.post("/api/customers")
def create_customer(req: CustomerCreate, db: Session = Depends(get_db)):
    c = Customer(
        company_name=req.company_name, contact_name=req.contact_name,
        contact_email=req.contact_email, contact_phone=req.contact_phone,
        plan=req.plan, notes=req.notes,
    )
    db.add(c)
    db.flush()

    result = {"ok": True, "id": c.id}

    # 자동 라이선스 발급
    if req.auto_license:
        preset = PLAN_PRESETS.get(req.plan, PLAN_PRESETS["basic"])
        key = generate_license_key()
        expires = datetime.utcnow() + timedelta(days=req.duration_days)
        lic = License(
            license_key=key, customer_id=c.id, plan=req.plan,
            max_crawl_accounts=preset["max_crawl_accounts"],
            max_dm_accounts=preset["max_dm_accounts"],
            max_daily_dm=preset["max_daily_dm"],
            max_hashtags=preset["max_hashtags"],
            can_schedule=preset["can_schedule"],
            can_analyze=preset["can_analyze"],
            can_export=preset["can_export"],
            expires_at=expires,
        )
        db.add(lic)
        result["license_key"] = key
        result["expires_at"] = expires.isoformat()

    db.commit()
    return result


@app.get("/api/customers")
def list_customers(db: Session = Depends(get_db)):
    customers = db.query(Customer).order_by(Customer.created_at.desc()).all()
    return [
        {"id": c.id, "company_name": c.company_name, "contact_name": c.contact_name,
         "contact_email": c.contact_email, "contact_phone": c.contact_phone,
         "plan": c.plan,
         "created_at": c.created_at.isoformat() if c.created_at else None}
        for c in customers
    ]


@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    c = db.query(Customer).get(customer_id)
    if not c:
        raise HTTPException(404, "고객사를 찾을 수 없습니다.")
    licenses = db.query(License).filter_by(customer_id=customer_id).all()
    return {
        "id": c.id, "company_name": c.company_name, "contact_name": c.contact_name,
        "contact_email": c.contact_email, "contact_phone": c.contact_phone,
        "plan": c.plan, "notes": c.notes,
        "licenses": [license_to_dict(lic, c.company_name) for lic in licenses],
    }


# ── 라이선스 API ──

@app.post("/api/licenses")
def create_license(req: LicenseCreate, db: Session = Depends(get_db)):
    customer = db.query(Customer).get(req.customer_id)
    if not customer:
        raise HTTPException(404, "고객사를 찾을 수 없습니다.")
    preset = PLAN_PRESETS.get(req.plan, PLAN_PRESETS["basic"])
    key = generate_license_key()
    expires = datetime.utcnow() + timedelta(days=req.duration_days)
    lic = License(
        license_key=key, customer_id=req.customer_id, plan=req.plan,
        max_crawl_accounts=preset["max_crawl_accounts"],
        max_dm_accounts=preset["max_dm_accounts"],
        max_daily_dm=preset["max_daily_dm"],
        max_hashtags=preset["max_hashtags"],
        can_schedule=preset["can_schedule"],
        can_analyze=preset["can_analyze"],
        can_export=preset["can_export"],
        expires_at=expires,
    )
    db.add(lic)
    db.commit()
    return {"ok": True, "license_key": key, "expires_at": expires.isoformat()}


@app.get("/api/licenses")
def list_licenses(db: Session = Depends(get_db)):
    licenses = db.query(License).order_by(License.created_at.desc()).all()
    result = []
    for lic in licenses:
        customer = db.query(Customer).get(lic.customer_id)
        result.append(license_to_dict(lic, customer.company_name if customer else "?"))
    return result


@app.get("/api/licenses/{license_id}")
def get_license_detail(license_id: int, db: Session = Depends(get_db)):
    lic = db.query(License).get(license_id)
    if not lic:
        raise HTTPException(404, "라이선스를 찾을 수 없습니다.")
    customer = db.query(Customer).get(lic.customer_id)
    return license_to_dict(lic, customer.company_name if customer else "?")


@app.put("/api/licenses/{license_id}/deactivate")
def deactivate_license(license_id: int, db: Session = Depends(get_db)):
    lic = db.query(License).get(license_id)
    if not lic:
        raise HTTPException(404, "라이선스를 찾을 수 없습니다.")
    lic.is_active = False
    db.commit()
    return {"ok": True}


@app.put("/api/licenses/{license_id}/reset-machine")
def reset_machine(license_id: int, db: Session = Depends(get_db)):
    """라이선스의 기기 바인딩을 해제한다 (다른 PC에서 재활성화 가능)."""
    lic = db.query(License).get(license_id)
    if not lic:
        raise HTTPException(404, "라이선스를 찾을 수 없습니다.")
    lic.machine_id = None
    lic.activated_at = None
    db.commit()
    customer = db.query(Customer).get(lic.customer_id)
    return {"ok": True, "license": license_to_dict(lic, customer.company_name if customer else "?")}


# ── 프로그램측 라이선스 검증 API ──

@app.post("/api/license/activate")
def activate_license(req: LicenseActivateRequest, db: Session = Depends(get_db)):
    lic = db.query(License).filter_by(license_key=req.license_key).first()
    if not lic:
        return {"ok": False, "error": "유효하지 않은 라이선스 키입니다."}
    if not lic.is_active:
        return {"ok": False, "error": "비활성화된 라이선스입니다."}
    if lic.expires_at and lic.expires_at < datetime.utcnow():
        return {"ok": False, "error": "만료된 라이선스입니다."}
    if lic.machine_id and lic.machine_id != req.machine_id:
        return {"ok": False, "error": "다른 기기에 이미 활성화된 라이선스입니다."}
    lic.machine_id = req.machine_id
    lic.activated_at = datetime.utcnow()
    db.commit()
    customer = db.query(Customer).get(lic.customer_id)
    return {
        "ok": True,
        "company_name": customer.company_name if customer else "",
        "plan": lic.plan,
        "expires_at": lic.expires_at.isoformat(),
        "max_crawl_accounts": lic.max_crawl_accounts,
        "max_dm_accounts": lic.max_dm_accounts,
        "max_daily_dm": lic.max_daily_dm,
        "max_hashtags": lic.max_hashtags,
        "can_schedule": lic.can_schedule,
        "can_analyze": lic.can_analyze,
        "can_export": lic.can_export,
    }


@app.post("/api/license/verify")
def verify_license(req: LicenseVerifyRequest, db: Session = Depends(get_db)):
    lic = db.query(License).filter_by(license_key=req.license_key).first()
    if not lic:
        return {"ok": False, "error": "유효하지 않은 라이선스"}
    if not lic.is_active:
        return {"ok": False, "error": "비활성화된 라이선스"}
    if lic.expires_at and lic.expires_at < datetime.utcnow():
        return {"ok": False, "error": "만료된 라이선스"}
    if lic.machine_id and lic.machine_id != req.machine_id:
        return {"ok": False, "error": "다른 기기에서 활성화된 라이선스"}
    return {
        "ok": True,
        "plan": lic.plan,
        "max_crawl_accounts": lic.max_crawl_accounts,
        "max_dm_accounts": lic.max_dm_accounts,
        "max_daily_dm": lic.max_daily_dm,
        "max_hashtags": lic.max_hashtags,
        "can_schedule": lic.can_schedule,
        "can_analyze": lic.can_analyze,
        "can_export": lic.can_export,
    }


# ── 하트비트 ──

class HeartbeatRequest(BaseModel):
    license_key: str
    machine_id: str
    version: str = ""


@app.post("/api/heartbeat")
def heartbeat(req: HeartbeatRequest, db: Session = Depends(get_db)):
    lic = db.query(License).filter_by(license_key=req.license_key).first()
    if not lic:
        return {"ok": False}
    lic.activated_at = lic.activated_at  # keep existing
    customer = db.query(Customer).get(lic.customer_id)
    # 로그: 고객사명, 버전, 마지막 접속 시간
    print(f"[Heartbeat] {customer.company_name if customer else '?'} | v{req.version} | {datetime.utcnow().isoformat()}")
    return {"ok": True}


# ── 버전 체크 ──

LATEST_VERSION = "1.0.0"
DOWNLOAD_URL = ""  # 업데이트 다운로드 URL (추후 설정)


@app.get("/api/version")
def check_version(current: str = ""):
    from packaging.version import Version
    try:
        update_available = Version(current) < Version(LATEST_VERSION) if current else False
    except Exception:
        update_available = False
    return {
        "latest_version": LATEST_VERSION,
        "current_version": current,
        "update_available": update_available,
        "download_url": DOWNLOAD_URL,
        "message": f"새 버전 {LATEST_VERSION}이 있습니다. 업데이트해주세요." if update_available else "",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 9090))
    uvicorn.run(app, host="0.0.0.0", port=port)
