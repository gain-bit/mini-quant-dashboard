# Mini Quant Dashboard (KIS Open API 연동판)

Streamlit 기반 미니 퀀트 대시보드 — 한국투자증권(KIS) Open API REST 실시간 시세 전용.
FinanceDataReader, yfinance, pykrx, 목업(Mock) 데이터는 전혀 사용하지 않습니다.

## 최근 버그 수정 (2026-09-10)

1. **환율 조회 실패 수정** (`utils/naver_fx.py`) — 네이버 마켓인덱스 JSON API의 실제 응답이
   최상위가 아니라 `exchangeInfo` 키 안에 중첩되어 있었고, 등락 방향도 문자열이 아니라
   `{"code": "2", "text": "상승", "name": "RISING"}` 형태의 딕셔너리로 내려오는데 파서가
   이를 반영하지 못해 조회가 항상 실패하고 있었다. 실제 오류 응답을 그대로 사용해 수정
   후 재검증했다.
2. **페이지 전환 시 스크롤 자동 리셋** (`app.py`) — 사이드바에서 다른 페이지로 이동하면
   스크롤 위치가 유지되어 화면 중간부터 보이던 문제를 고쳤다. `st.session_state`로 이전
   페이지를 기억해두었다가, 페이지가 실제로 바뀐 경우에만(30초 자동 새로고침 등 일반
   재실행과는 구분) `streamlit.components.v1.html`로 스크롤을 최상단으로 이동시킨다.
3. **Detail 페이지에 섹션별 최종 업데이트 날짜 표기** (`pages_impl/detail.py`) — 각 항목
   제목 옆에 마지막으로 수정된 날짜가 함께 표시되어, 이후 기능이 추가·변경될 때마다
   무엇이 언제 바뀌었는지 한눈에 추적할 수 있다.
4. **올웨더 자산군 카드 정렬 버그 수정** (`pages_impl/market_overview.py`) — "전체" 탭에서
   `st.columns()`를 카테고리 루프 바깥에서 한 번만 생성하고 카테고리 제목은 컬럼 밖에서
   출력하다 보니, Streamlit이 제목들을 카드 그리드 전체 아래로 밀어버리는 렌더링 순서
   문제가 있었다. 8대 섹터 섹션과 동일하게 카테고리마다 컬럼을 새로 생성하도록 고쳤다.

## 폴더 구조

```
mini_quant_dashboard/
├── app.py                        # 메인 엔트리포인트 (사이드바 네비게이션, 공통 스타일, API 키 미설정 가드)
├── config.py                     # 초기자금/킬스위치/섹터 유니버스/KIS tr_id 등 전역 설정
├── db.py                         # SQLite 기반 가상 포트폴리오 저장소
├── requirements.txt
├── .gitignore                     # secrets.toml, 토큰 캐시(.token_cache.json), DB 파일 등을 커밋에서 제외
├── .streamlit/
│   └── secrets.toml.example      # KIS/텔레그램 인증정보 설정 예시 (복사해서 secrets.toml로 사용)
├── .token_cache.json               # (자동 생성됨, 프로젝트 루트) 발급된 KIS 토큰 캐시 — 커밋하지 말 것
├── pages_impl/
│   ├── market_overview.py        # 페이지1: Market Overview — 시장 국면 신호등 + 8대 섹터 + 올웨더 자산군
│   ├── portfolio_analysis.py     # 페이지2: Portfolio & Quant Analysis — 위험도 경보 + 스크리너 + 페이퍼 트레이딩
│   └── detail.py                  # 페이지3: Detail — 사이트 목적/데이터 출처/갱신 주기 등 설명 페이지
└── utils/
    ├── kis_api.py                 # KIS REST 클라이언트 (토큰 자동관리+파일캐시, 국내지수/종목 시세, 휴장일조회)
    ├── naver_fx.py                 # 네이버 금융 원/달러 환율 조회 (JSON→HTML 폴백)
    ├── market_hours.py             # KST 기준 정규장 운영시간 판별 (월~금 09:00~16:00, 요일·시간만)
    ├── holiday.py                  # 한국거래소 휴장일 캘린더 조회 (KIS API 재사용, 하루 단위 캐싱)
    ├── strategy_engine.py          # 매크로(코스피 200일선)+퀀트(RSI/PBR/PER) 결합 매수 시그널 판단
    ├── risk.py                     # 계좌 킬 스위치 + 시장 위험도 경보(이동평균/변동성 타겟팅) 판단
    ├── telegram_bot.py             # 텔레그램 봇 API 실시간 푸시 알림 (매수시그널/손절/킬스위치)
    └── data_fetcher.py             # 캐싱(ttl=30) + Last-Known-Good 폴백을 포함한 상위 데이터 계층
```

**Python 3.9 호환성**: 모든 모듈 상단에 `from __future__ import annotations`를 추가해,
`str | None` 같은 PEP 604 유니온 문법을 3.9에서도 안전하게 쓸 수 있도록 했다 (이 문법은
3.10부터 네이티브 지원되며, future import 없이 3.9에서 그대로 실행하면 `TypeError`가 난다).

## 사전 준비: KIS API Key 발급

1. [한국투자증권 Open API 포털](https://apiportal.koreainvestment.com)에서 회원가입 후 APP KEY / APP SECRET 발급
2. 실전투자든 모의투자든 상관없이 시세 조회(quotations)는 가능합니다.
3. `.streamlit/secrets.toml.example` 파일을 복사해 `.streamlit/secrets.toml`로 저장하고 값을 채웁니다.

```toml
[kis]
APP_KEY = "발급받은 APP KEY"
APP_SECRET = "발급받은 APP SECRET"
CANO = "계좌번호 앞 8자리"
ACNT_PRDT_CD = "계좌상품코드 (보통 01)"
IS_VIRTUAL = true   # 모의투자면 true, 실전투자면 false
```

`secrets.toml`이 없거나 값이 누락되면, 앱이 죽지 않고 화면에
"⚠️ .streamlit/secrets.toml 파일에 한국투자증권 API Key를 설정해주세요" 안내 카드가 표시됩니다.

## 실행 방법

```bash
cd mini_quant_dashboard
pip install -r requirements.txt
streamlit run app.py
```

**Streamlit Community Cloud에 배포하려면** GitHub 업로드 방법과 Secrets 설정 방법을 정리한
[`DEPLOY.md`](./DEPLOY.md)를 참고하세요. API 키가 GitHub에 노출되지 않도록 `.gitignore`
설정과 Streamlit Cloud의 Secrets 입력 예시가 함께 안내되어 있습니다.

대시보드는 **정규장 운영시간(KST 기준 월~금 09:00:00~16:00:00)** 에만 15초 주기로
자동 새로고침되어 최신 KIS 시세를 반영합니다 (`config.py`의 `AUTOREFRESH_INTERVAL_SEC`,
`MARKET_OPEN_TIME`, `MARKET_CLOSE_TIME`, `streamlit-autorefresh` 패키지 사용).
장 마감 후·주말에는 자동 새로고침이 완전히 중지되고, 직전에 조회된 정적 시세가 유지됩니다.
- 장중: 사이드바에 `🔴 장중 실시간 동기화 중 (15초 주기)`
- 장마감/주말: 사이드바에 `🟢 장마감 (정적 시세 유지 중)`

`streamlit-autorefresh` 패키지가 설치되어 있지 않은 환경에서는 HTML `meta refresh` 방식으로
자동 대체되어(장중일 때만) 앱이 죽지 않고 동일한 주기로 전체 페이지가 새로고침됩니다.

시간대 판별은 표준 라이브러리 `zoneinfo("Asia/Seoul")`로 처리하며 (`utils/market_hours.py`),
요일·시간 조건 외에 **한국거래소 휴장일 캘린더**도 함께 반영합니다 (`utils/holiday.py`).
휴장일 조회는 KIS Open API의 '국내휴장일조회'(tr_id `CTCA0903R`)를 사용하며, **기존에 설정한
KIS APP_KEY/APP_SECRET을 그대로 재사용하므로 별도의 API를 추가로 발급받을 필요가 없습니다.**
휴장일 조회가 실패하거나 KIS 키가 없는 경우엔 "휴장일 여부 불명"으로 간주해 요일/시간
조건만으로 판단하는 fail-open 방식이라, 캘린더 조회 장애 때문에 정상 거래일에 새로고침이
멈추는 일은 없습니다. 일부 환경(특히 Windows)은 시스템에 IANA 타임존 DB가 없을 수 있어
`requirements.txt`에 `tzdata`를 포함했습니다.

## 텔레그램 실시간 푸시 알림

`utils/telegram_bot.py`가 `.streamlit/secrets.toml`의 `[telegram]` 섹션(`BOT_TOKEN`,
`CHAT_ID`)을 읽어 실제 텔레그램 봇 API(`https://api.telegram.org/bot<TOKEN>/sendMessage`)로
메시지를 전송합니다. 설정이 없거나 네트워크 오류가 발생해도 예외를 던지지 않고
`(성공 여부, 메시지)`만 반환하므로 앱이 멈추지 않습니다.

요청 타임아웃은 12초로 설정되어 있습니다. 텔레그램 서버 응답이 느려
`requests.exceptions.ReadTimeout`이 발생하는 경우는 실패로 단정하지 않습니다 — 요청 자체는
이미 서버로 전달되었을 가능성이 높으므로, `ok=True`와 함께
`⚠️ 메시지가 발송되었으나 응답 확인이 지연되었습니다.` 안내만 반환합니다. 테스트 버튼에서는
이 경우 빨간 에러 박스가 아니라 노란 경고(`st.warning`) 박스로 구분해서 표시됩니다.

자동 발송되는 3가지 알림:

1. **매수 추천 시그널 포착** — 코스피 200일선 위(공격 모드) + RSI≤30/PBR<1.0/PER≤10을
   모두 만족하는 종목이 새로 포착되면 전송됩니다. 같은 종목에 대해 **하루 1회만** 발송되도록
   `db.notification_log` 테이블로 중복을 방지합니다.
2. **손절가 도달** — 보유 종목이 자동 손절 매도될 때마다 항상 전송됩니다(포지션이 매도되어
   사라지므로 자연스럽게 중복되지 않습니다).
3. **계좌 킬 스위치 발동** — 킬 스위치가 새로 발동되는 순간에만 전송됩니다(엣지 트리거).
   `db.app_state` 테이블에 발동 여부를 저장해두었다가, 킬 스위치가 해제되면 플래그를
   초기화해 다음에 다시 발동될 때 재알림이 가도록 했습니다.

스크리너와 매수 추천 카드에 있는 "텔레그램 알림 전송" 버튼은 실제 전송 연동을 즉석에서
확인해볼 수 있는 테스트 버튼입니다. 누르면 실제로 `📱 [Mini Quant] 대시보드 알림 연동
테스트 성공!` 메시지가 설정된 텔레그램 채팅으로 전송되고, 성공/실패 여부가 화면에
`st.success` / `st.error`로 표시됩니다.

### 텔레그램 봇 설정 방법

1. 텔레그램에서 `@BotFather`와 대화를 시작해 `/newbot` 명령으로 봇을 생성하고 발급받은
   토큰을 `BOT_TOKEN`에 입력합니다.
2. 만든 봇과 개인 대화(또는 그룹)를 시작한 뒤 아무 메시지나 보냅니다.
3. 브라우저로 `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`에 접속해 응답 JSON에서
   `chat.id` 값을 찾아 `CHAT_ID`에 입력합니다.
4. `.streamlit/secrets.toml`에 다음과 같이 추가합니다.

```toml
[telegram]
BOT_TOKEN = "발급받은 텔레그램 봇 토큰"
CHAT_ID = "알림을 받을 chat_id"
```

## 전략 엔진: 매수 추천 시그널 / 자동 손절 / 킬 스위치

1. **매수 추천 시그널** (`utils/strategy_engine.py`, `pages_impl/portfolio_analysis.py`)
   - 조건 A(매크로): 코스피 지수가 200일 이동평균선 위(공격 모드)
   - 조건 B(퀀트): RSI ≤ 30 AND PBR < 1.0 AND (0 < PER ≤ 10)
   - A와 B를 모두 만족하는 종목만 스크리너 상단에 "가상 매수 추천 시그널" 카드로 강조 표시된다.
     조건을 일부만 만족하는 종목은 그 아래 "조건 부분 충족 종목(관심 목록)"에 **카드형 레이아웃**으로
     함께 보여준다. 각 카드는 `st.container(border=True)`로 감싸고, 1행에 종목명(코드)·현재가,
     시그널은 색상이 구분된 배지(RSI 과매도=빨강, 저PBR=파랑, 저PER=보라)로 표시하며, 2행에
     PER·PBR·RSI를 한 줄로 컴팩트하게, 3행에 텔레그램 알림 전송 버튼을 배치한다. 기존의 좁은 열
     8개짜리 `st.columns` 표 레이아웃은 모바일에서 세로로 심하게 늘어지는 문제가 있어 이 카드형
     구조로 전면 교체했다.
   - 판단 로직 자체는 외부 API를 호출하지 않는 순수 함수라 단위 테스트로 경계값(RSI/PBR/PER의
     정확히 임계값인 경우, 조건 일부만 만족하는 경우 등)을 검증했다.

2. **포지션별 자동 손절** (`pages_impl/portfolio_analysis.py`)
   - 보유 종목의 실시간 평가 수익률이 매수 시 설정한 손절 기준(-3% 또는 -5%)에 도달하거나
     이를 초과해 하락하면, 화면이 새로고침될 때마다(장중에는 30초 주기) 자동으로 감지되어
     해당 포지션을 즉시 가상 매도 처리하고 매도 이력을 DB에 기록한다.
   - 보유 종목 목록에는 각 종목의 수익률이 손절 기준에 얼마나 근접했는지 진행률 막대로
     표시되며, 근접도에 따라 안전/주의/위험 3단계 라벨이 함께 표시된다.

3. **계좌 전체 킬 스위치** (`utils/risk.py`, `app.py`)
   - (보유 현금 + 보유 종목 평가금액)의 총 손실률이 초기 자금 대비 -2.0% 이하로 내려가면
     킬 스위치가 자동 발동되어, 어느 페이지에 있든 대시보드 최상단에
     "🚨 계좌 리스크 킬 스위치 작동 (-2% 손실 도달): 신규 매수 강제 잠금" 배너가 표시된다.
   - 킬 스위치 발동 중에는 페이퍼 트레이딩 화면의 매수 실행 버튼이 비활성화되어 신규 매수가
     완전히 차단된다.

## 올웨더 포트폴리오 자산군 + 시장 위험도 경보 (동적 자산배분)

1. **올웨더 포트폴리오 자산군** (`config.py`의 `ASSET_CLASS_ETFS`, `pages_impl/market_overview.py`)
   - 레이 달리오의 올웨더(All-Weather) 포트폴리오 개념을 참고해 주식/채권/원자재/현금·방어
     4개 자산군의 국내 상장 ETF를 추가했다 (KODEX 200, TIGER 미국S&P500, KODEX 국고채10년,
     TIGER 미국채10년선물, KODEX 골드선물(H), TIGER 원유선물Enhanced(H), KODEX KOFR금리액티브,
     KODEX 200선물인버스2X).
   - Market Overview 페이지 하단에 `st.tabs()`로 전체/주식/채권/원자재/현금·방어 필터를 제공하며,
     기존 8대 섹터 카드와 동일한 카드형 레이아웃 렌더러(`_render_stock_card_html`)를 공유해
     모바일 UI가 깨지지 않는다.
   - ⚠️ ETF 코드, 특히 KOFR금리액티브 계열은 유사 상품이 많아 실제 사용 전 한국거래소
     정보데이터시스템 등에서 최신 코드로 재확인을 권장한다.

2. **시장 위험도 경보 / 변동성 타겟팅** (`utils/risk.py`, `pages_impl/portfolio_analysis.py`)
   - 파생상품(풋옵션) 없이 인버스 ETF·현금 비중 조절만으로 방어하는 동적 리스크 관리 개념을 구현했다.
   - 코스피 지수와, 실제 해외지수 대신 국내 상장 ETF 'TIGER 미국S&P500'(원화 기준)을 S&P500의
     프록시로 사용해 각각 20일/60일 이동평균 추세와 20일 연환산 변동성을 분석한다.
   - 판정 기준: 20일선 아래이면서 20일선<60일선(데드크로스)이거나 변동성 ≥30%면 "위험",
     20일선 아래이거나 변동성 ≥20%면 "주의", 그 외는 "정상". 코스피와 S&P500 프록시 중 더
     위험한 쪽을 전체 경보 단계로 채택한다.
   - 단계별 권장 문구: 정상 → "현금/인버스 비중 0%", 주의 → "현금 또는 인버스 ETF 비중
     20~30% 확보 추천", 위험 → "KODEX 200선물인버스2X 비중 확대 권장".
   - 상승/하락/고변동성/데이터부족/데이터없음 5가지 시나리오를 순수 함수 단위 테스트로 직접
     실행해 검증했다. 이동평균 기간과 변동성 임계값(`config.py`)은 조정 가능한 휴리스틱이다.

## 안정성 방어 체계 구현 내역

1. **토큰 자동 관리** (`utils/kis_api.py`)
   - Access Token은 프로세스 메모리(전역 캐시)에 저장하며, 만료 5분 전 자동 갱신
   - API 호출 중 401 응답을 받으면 토큰을 강제 재발급 후 1회 자동 재시도
   - 추가로, 발급된 토큰을 프로젝트 루트의 `.token_cache.json` 파일에도 백업한다. 개발 중
     코드 수정으로 Streamlit 프로세스가 재시작되어 메모리 캐시가 초기화되더라도, 파일에
     남아있는 토큰이 아직 유효하면(만료 전이고 APP_KEY/모의·실전 모드가 동일하면) 그대로
     재사용한다. 이는 KIS의 "토큰 재발급 1분당 1회" 제한(에러코드 `EGW00133`,
     `접근토큰 발급 잠시 후 다시 시도하세요`)에 걸리는 것을 방지하고, 앱을 켤 때마다
     매번 재발급하면서 발생하던 알림(카카오톡 등) 폭주를 줄이기 위함이다.
     이 캐시 파일에는 발급된 토큰(민감 정보)이 담기므로 `.gitignore`에 포함되어 있으며,
     `secrets.toml`의 APP_KEY를 바꾸거나 모의/실전 모드를 전환하면 자동으로 무시되고
     새로 발급받는다.

2. **Rate Limit / IP 차단 방지**
   - 모든 시세 조회 함수(`utils/data_fetcher.py`)에 `@st.cache_data(ttl=30)` 적용 → 30초간 캐시된 값 재사용
     (데이터 수집과 UI 렌더링의 병목을 분리하기 위해 기존 15초에서 상향)
   - 히스토리(200일 이평/RSI/60일 이평용) 조회는 `ttl=120`으로 더 길게 캐싱
   - 실제 KIS 호출이 일어나는 지점마다 `time.sleep(0.2)`를 적용해 연속 호출 시 과도한 트래픽 방지
     (기존 0.05초에서 상향 조정 — 초당 거래건수 초과 오류 EGW00201 발생 빈도를 낮추기 위함)
   - 여러 종목을 순회 조회하는 화면(8대 섹터, 스크리너, 올웨더 자산군)은 캐시 미스가 난 종목만
     실제로 호출하므로, 최초 로딩 이후에는 API 호출이 거의 발생하지 않음
   - `utils/kis_api.py`의 `_request()`는 응답에서 `msg_cd == "EGW00201"`("초당 거래건수를 초과하였습니다")을
     감지하면 1.0초 대기 후 자동으로 재시도하며, 최대 2회까지 반복한다. 이 오류는 KIS가 HTTP 200이 아닌
     상태코드(주로 500)로 내려보내는 경우가 있어, HTTP 상태코드를 판정하기 전에 먼저 응답 바디에서
     이 오류코드 여부를 확인하도록 구현했다. 재시도 로직 자체는 `requests.get`을 모킹한 테스트로
     (2회 실패 후 성공 / 계속 실패 시 최종 오류 / 일반 오류는 재시도 없이 즉시 실패) 3가지 시나리오를
     직접 실행해 검증했다.

3. **네트워크 지연/실패 방어 — Last-Known-Good**
   - 목업 데이터는 완전히 제거했습니다.
   - API 호출이 실패하면 `st.session_state`에 저장해둔 '가장 최근에 성공한 진짜 시세'를 그대로 보여주고,
     `⚠️ KIS 일시 응답 지연 (최근 성공 시세 유지 중)` 라벨을 함께 표시합니다.
   - 과거 성공 데이터도 전혀 없는 경우(최초 실행부터 실패)에만 오류 카드를 표시합니다.

4. **API 키 미설정 안내**
   - `app.py`에서 `kis_api.is_configured()`를 확인해, 설정이 안 되어 있으면 즉시 안내 카드를 띄우고
     `st.stop()`으로 이후 로직 실행을 막아 앱이 죽지 않습니다.

5. **출처/동기화 시각 표기** (`market_overview.py`)
   - 지수/환율/종목 카드 하단에 `🏷️ 출처: 한국투자증권 REST API | 동기화: HH:MM:SS` 형태로 표기
   - 지연 데이터인 경우 그 위에 경고 라벨이 함께 노출됩니다.

## ⚠️ 반드시 확인해야 할 사항 (중요)

이 리팩토링은 네트워크가 차단된 개발 환경에서 작성되어, KIS 서버에 대한 실제 호출 테스트를
진행하지 못했습니다. 아래 항목은 KIS Open API 공식 문서(https://apiportal.koreainvestment.com)의
최신본과 반드시 대조 확인한 후 사용하시길 권장합니다.

- **확실도가 높은 항목** (표준적으로 널리 쓰이는 엔드포인트)
  - OAuth 토큰 발급: `POST /oauth2/tokenP`
  - 주식현재가 시세: tr_id `FHKST01010100`, `/uapi/domestic-stock/v1/quotations/inquire-price`
  - 국내업종 현재지수: tr_id `FHPUP02100000`, `/uapi/domestic-stock/v1/quotations/inquire-index-price`

- **⚠️ 재검증이 필요한 항목** (버전/정책에 따라 tr_id·파라미터·응답 정렬 순서가 다를 수 있음)
  - 국내업종 일자별지수(200일 이동평균용): `config.py`의 `KIS_TR_ID["index_daily_price"]`
  - 주식현재가 일자별(RSI 계산용): `config.py`의 `KIS_TR_ID["stock_daily_price"]`
  - 국내휴장일조회(휴장일 캘린더용): `utils/kis_api.py`의 `get_domestic_holiday_status()` 내 tr_id `CTCA0903R`
  - 위 함수 모두 응답 필드명 후보를 여러 개 시도하는 방어적 파싱(`_extract_first_float` 등)을
    적용해, 필드명이 문서와 다르더라도 최대한 값을 뽑아내도록 재점검했습니다. 휴장일 조회가
    실패해도 fail-open으로 처리되어 앱이나 자동 새로고침이 멈추지 않습니다.

- **원/달러 환율은 KIS가 아닌 네이버 금융에서 조회합니다** (`utils/naver_fx.py`)
  - 1차: 네이버 증권 마켓인덱스 JSON API (`api.stock.naver.com/marketindex/exchange/FX_USDKRW`)
  - 2차: JSON 실패 시 네이버 금융 환율 페이지(`finance.naver.com/marketindex/`) HTML 파싱으로 폴백
  - 이 역시 비공식 공개 데이터라 네이버 측 구조 변경 가능성이 있으며, 두 방법 모두 실패하면
    `data_fetcher.py`의 Last-Known-Good 로직에 따라 직전 성공 환율 + 경고 라벨이 표시됩니다.

  위 항목들이 실제 KIS 스펙과 다르면 해당 기능(200일 이평 국면 판단, RSI, 환율)만 개별적으로
  "조회 실패" 상태로 표시되고 앱 전체는 정상 동작합니다(오류 전파 차단 구조로 설계됨).
  틀린 값이 확인되면 `config.py`의 `KIS_TR_ID` 딕셔너리 값만 고치면 됩니다 (다른 코드 수정 불필요).

- **모의투자(가상계좌) 계정의 호출 제한이 실전투자보다 더 엄격할 수 있습니다.**
  트래픽 제한에 자주 걸린다면 `config.py`의 `KIS_REQUEST_DELAY_SEC`, `KIS_QUOTE_CACHE_TTL_SEC` 값을
  늘려서 완화하세요.

## 문제 해결: "토큰 발급 실패 (HTTP 403) EGW00133"

`접근토큰 발급 잠시 후 다시 시도하세요(1분당 1회)` 메시지는 코드 오류가 아니라 KIS 서버가
APP_KEY 1개당 토큰 발급을 1분에 1회로 제한하기 때문에 발생합니다. 주로 아래 경우에
발생합니다.

- 같은 APP_KEY로 동시에 여러 Streamlit 프로세스(예: 이전 실행이 남아있는 상태에서 재실행)가
  각각 토큰을 요청한 경우
- 코드 수정 직후 Streamlit이 짧은 시간에 여러 번 자동 재시작되어, 재시작마다 메모리 캐시가
  초기화되고 매번 새 토큰을 요청한 경우

이번 업데이트로 발급된 토큰을 프로젝트 루트의 `.token_cache.json`에도 저장하도록 개선했으므로,
프로세스가 재시작되어도 아직 유효한 토큰이 있으면 재발급 없이 재사용됩니다. 그래도 이
오류가 발생한다면 실행 중인 다른 Streamlit 프로세스가 있는지 확인해 종료하고, 1분 정도
기다린 후 다시 실행하세요.

## 커스터마이징 포인트

- `config.py`의 `SECTOR_STOCKS`, `ASSET_CLASS_ETFS`, `INITIAL_CAPITAL`, `KILL_SWITCH_THRESHOLD`,
  `DEFAULT_STOP_LOSS_LEVELS`, `KIS_REQUEST_DELAY_SEC`, `KIS_QUOTE_CACHE_TTL_SEC`,
  `AUTOREFRESH_INTERVAL_SEC`, `MA_SHORT_DAYS`/`MA_LONG_DAYS`, `VOL_CAUTION_THRESHOLD`/
  `VOL_DANGER_THRESHOLD` 값만 바꾸면 유니버스/파라미터/캐시/새로고침 주기/위험도 경보
  임계값 조정이 가능합니다.
- 텔레그램 알림은 `utils/telegram_bot.py`를 통해 실제 텔레그램 봇 API로 발송됩니다
  (자세한 설정 방법은 위 "텔레그램 실시간 푸시 알림" 섹션 참고).

## 참고 / 제한 사항

- 개발 샌드박스가 네트워크 차단 환경이라 `pip install` 및 KIS 서버 실호출 테스트는
  로컬/서버 환경에서 인터넷이 연결된 상태로 직접 실행해 확인해야 합니다.
  코드 자체는 `py_compile`로 전체 모듈 문법 검증을 완료했습니다.
