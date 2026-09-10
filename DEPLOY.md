# Streamlit Community Cloud 배포 가이드

이 문서는 GitHub 업로드부터 Streamlit Community Cloud 배포까지, API 키가 절대
유출되지 않는 방식으로 진행하는 방법을 안내합니다.

---

## 핵심 원칙: 코드와 비밀정보는 분리해서 관리합니다

- **GitHub에 올라가는 것**: 소스 코드, `requirements.txt`, `.streamlit/secrets.toml.example`
  (전부 예시 값이거나 빈 값이라 안전합니다)
- **GitHub에 절대 올라가면 안 되는 것**: 실제 KIS APP_KEY/APP_SECRET, 텔레그램 BOT_TOKEN,
  계좌번호, 발급된 토큰 캐시 파일, 개인 매매 기록이 담긴 DB 파일
- 이 프로젝트의 `.gitignore`가 위 민감 파일들을 이미 자동으로 커밋 대상에서 제외합니다.
  실제 값은 **Streamlit Cloud의 Secrets 설정 화면에만** 입력합니다 (GitHub에는 절대
  올라가지 않는 별도의 저장 공간입니다).

---

## 1. `.gitignore` 확인 (이미 설정되어 있음)

프로젝트 루트의 `.gitignore`에 다음이 포함되어 있는지 확인하세요 (이미 포함되어 있습니다).

```
.streamlit/secrets.toml
.streamlit/kis_token_cache.json
.token_cache.json
*.db
*.sqlite
*.sqlite3
.venv/
venv/
```

이 덕분에 `git add .`를 하더라도 실제 비밀 값이 담긴 `secrets.toml`, 발급된 토큰 캐시,
개인 매매 DB 파일은 자동으로 제외됩니다. `.streamlit/secrets.toml.example`(예시 파일)은
실제 값이 없으므로 커밋되어도 안전하며, 오히려 저장소에 함께 두는 것을 권장합니다.

---

## 2. Streamlit Cloud [Secrets] 에 붙여넣을 TOML 예시

배포 후 Streamlit Cloud 대시보드에서 앱을 선택하고
**⋮ (메뉴) → Settings → Secrets** 로 들어가면 나오는 빈 텍스트 박스에
아래 내용을 실제 값으로 채워서 그대로 붙여넣으세요.

```toml
[kis]
APP_KEY = "여기에 실제 발급받은 KIS APP KEY를 입력"
APP_SECRET = "여기에 실제 발급받은 KIS APP SECRET을 입력"
CANO = "계좌번호 앞 8자리"
ACNT_PRDT_CD = "01"
IS_VIRTUAL = true

[telegram]
BOT_TOKEN = "여기에 실제 텔레그램 봇 토큰을 입력"
CHAT_ID = "여기에 알림을 받을 chat_id를 입력"
```

- `[telegram]` 섹션은 선택 사항입니다. 텔레그램 알림 기능을 쓰지 않는다면 통째로
  생략해도 앱은 정상 동작하며, 알림 관련 버튼/자동 알림만 비활성화됩니다.
- `IS_VIRTUAL`은 모의투자 계좌면 `true`, 실전투자 계좌면 `false`로 입력하세요.
- 저장(Save)하면 앱이 자동으로 재시작되며 이 값들을 `st.secrets`로 즉시 읽어들입니다.

---

## 3. 3분 배포 가이드 (GitHub 업로드 → Streamlit Cloud 연동)

### 1단계 — GitHub에 저장소 만들고 코드 올리기 (약 1분)

1. [github.com](https://github.com)에 로그인 후 우측 상단 `+` → **New repository** 클릭
2. 저장소 이름을 정하고(예: `mini-quant-dashboard`), **Public** 또는 **Private** 아무거나
   선택 후 **Create repository**
3. 압축 해제한 프로젝트 폴더에서 터미널을 열고 아래 명령을 순서대로 실행합니다
   (`<your-repo-url>`은 방금 만든 저장소 페이지에 표시된 주소로 바꿔주세요).

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

4. GitHub 저장소 페이지를 새로고침해서 파일이 올라갔는지 확인하세요. 이때
   `secrets.toml`이나 `.db` 파일이 보이지 않아야 정상입니다 (`.gitignore`가 제외했기 때문).

### 2단계 — Streamlit Community Cloud에서 앱 배포 (약 1분)

1. [share.streamlit.io](https://share.streamlit.io)에 접속해 GitHub 계정으로 로그인
2. **New app** 버튼 클릭
3. 방금 만든 저장소, 브랜치(`main`), 메인 파일 경로(`app.py`)를 선택
4. **Deploy!** 클릭 — 몇십 초간 빌드가 진행됩니다 (이 시점에는 API 키가 없어서
   대시보드에 "API Key를 설정해주세요" 안내 카드가 뜨는 것이 정상입니다)

### 3단계 — Secrets 입력하고 최종 확인 (약 1분)

1. 배포된 앱 화면 우측 하단(또는 상단) **⋮ 메뉴 → Settings → Secrets** 클릭
2. 위 "2. Streamlit Cloud [Secrets] 예시" 내용을 실제 값으로 채워 붙여넣고 **Save**
3. 앱이 자동으로 재시작되며 잠시 후 정상적으로 실시간 시세가 표시되면 완료입니다

---

## 참고 사항

- **페이퍼 트레이딩 DB는 배포 환경에서 휘발성입니다.** Streamlit Community Cloud는
  앱이 재시작되거나 재배포될 때 파일 시스템이 초기화될 수 있어, SQLite로 저장한
  가상 매매 기록(`quant_dashboard.db`)이 사라질 수 있습니다. 개인 로컬 환경에서는
  문제없이 계속 유지되지만, 클라우드에 장기간 기록을 남기고 싶다면 별도의
  외부 데이터베이스 연동이 필요합니다.
- Secrets를 수정한 뒤에는 항상 자동으로 앱이 재시작되지만, 반영이 안 된 것처럼 보이면
  Streamlit Cloud 앱 화면의 **Reboot app** 메뉴로 수동 재시작해보세요.
- 저장소를 Public으로 만들었다면 코드는 누구나 볼 수 있지만, Secrets는 별도로 암호화되어
  저장되고 저장소 파일과 무관하게 관리되므로 코드가 공개되어도 API 키는 노출되지 않습니다.
  그래도 확신이 없다면 저장소를 Private으로 만드는 것이 가장 안전합니다.
