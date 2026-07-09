# 국토교통부 실거래가 조회 MCP 서버 (MOLIT Real Estate Transactions MCP Server)

자연어 프롬프트(예: *"중구 광희동의 최근 12개월 토지거래 사례를 알려줘"*)를 받아 국토교통부 실거래가 공개 API를 조회하고, **자산 성격 / 규모(㎡ 및 평) / 거래금액 / 평단가(만원/평)** 등을 정형화된 표와 요약 통계로 반환하는 원격 MCP 서버입니다.

---

## 🛠️ 기술 스택 및 연동 API

* **언어**: Python 3.11+ (Python 3.14 호환 완료)
* **MCP 프레임워크**: FastMCP (Streamable-HTTP transport, `/mcp` 엔드포인트) 및 SSE 동시 지원
* **데이터 소스**: 공공데이터포털 (data.go.kr) 국토교통부 실거래가 오픈 API 3종
  1. **토지 매매 실거래가**: `RTMSDataSvcLandTrade`
  2. **상업업무용 부동산 매매 실거래가**: `RTMSDataSvcNrgTrade`
  3. **아파트 매매 실거래가 상세자료**: `RTMSDataSvcAptTradeDev`

---

## ✨ 핵심 처리 특징

1. **경량/정적 법정동 코드 매핑**:
   * 행정표준코드 데이터 (`code_bdong.json`)를 프로젝트 내에 정적으로 내장하여, 시도+시군구+법정동명을 5자리 지역코드(`LAWD_CD`)로 변환합니다.
   * 외부 pandas나 라이브러리 의존성 없이 순수 파이썬 표준 라이브러리만으로 고성능 검색 및 중의적 주소(동명 중복) 확인을 지원합니다.
2. **지분 및 해제 거래 스크리닝**:
   * 평단가 왜곡을 방지하기 위해 지분 거래(`shareDealingType`) 및 계약 해제건(`cdealDay`, `cdealType`)을 통계에서 완벽히 분리하고, 필터링 여부에 따라 플래그 표시합니다.
3. **상업업무용 이중 평단가**:
   * 상업용 부동산의 특성을 고려하여 **대지면적 기준 평단가**와 **연면적(건물면적) 기준 평단가**를 이중으로 산출하여 병기합니다.
4. **거래 희소성 대응 폴백(Fallback)**:
   * 조회 기간 동안 거래 실적이 0건인 경우, 자동으로 검색 기간을 연장(`months_back` 증가)하거나 인접 법정동 조회를 검토하라는 제안 메시지를 반환합니다.
5. **보안성**:
   * 에러 로그나 디버깅 메시지 출력 시 `MOLIT_SERVICE_KEY`가 외부로 노출되지 않도록 마스킹 처리 유틸리티가 통합되어 있습니다.

---

## 🚀 로컬 실행 방법

### 1. 가상환경 설정 및 의존성 설치
```bash
# 가상환경 생성
python -m venv .venv

# 가상환경 활성화 (Windows)
.venv\Scripts\activate

# 서버 구동용 의존성 설치
pip install -r requirements.txt

# (선택) 테스트 스크립트까지 실행하려면 개발용 의존성 추가 설치
pip install -r requirements-dev.txt
```

> `requirements.txt`는 서버 구동에 필요한 최소 런타임 의존성만 담고 있습니다. `test_api.py` 등 검증 스크립트는 `requests`를 사용하므로 `requirements-dev.txt`로 별도 설치합니다.

### 2. 환경 변수 설정
프로젝트 루트 폴더에 `.env` 파일을 생성하고 공공데이터포털에서 발급받은 일반 인증키(Decoding 키 권장)를 설정합니다.

```env
# 국토교통부 실거래가 공개 API 인증키 (공공데이터포털 일반 인증키)
MOLIT_SERVICE_KEY=your_decoding_service_key_here

# 서버 구동 포트
PORT=8080
```

### 3. 로컬 테스트 및 API 검증
연결성 및 툴 작동 여부를 사전에 자가진단할 수 있는 통합 검증 스크립트를 제공합니다.
```bash
# 로컬 통합 테스트 실행 (requirements-dev.txt 설치 필요)
.venv\Scripts\python.exe test_api.py
```

### 4. 로컬 서버 기동
* **HTTP/SSE 원격 모드 (클라우드 배포 시 사용)**:
  ```bash
  .venv\Scripts\python.exe server.py
  ```
  이 모드에서는 `0.0.0.0:8080` 포트로 HTTP/SSE 서버가 실행되며, `/mcp` 엔드포인트로 커넥터를 구성할 수 있습니다.
* **Stdio 로컬 파이프 모드 (Claude Desktop 로컬 연동 시 사용)**:
  ```bash
  .venv\Scripts\python.exe server.py stdio
  ```

---

## ☁️ 클라우드타입(Cloudtype) 배포 방법

이 프로젝트는 클라우드타입의 **Python Web App** 배포를 지원하도록 패키징되어 있습니다.

1. **GitHub 저장소 연동**: 본 코드를 GitHub 리포지토리(`main` 브랜치)에 푸시합니다.
2. **클라우드타입 새 프로젝트 생성**:
   * **종류**: Python
   * **빌드 명령**: `pip install -r requirements.txt`
   * **실행 명령**: 비워두면 `Procfile`의 `web: python server.py`가 자동 적용됩니다.
   * **포트**: `8080` (클라우드타입이 주입하는 `PORT` 환경변수를 서버가 자동으로 읽습니다.)
3. **환경변수(Secrets) 등록**:
   * `MOLIT_SERVICE_KEY`: 발급받은 실거래가 공용 인증키(Decoding 키) 입력
4. **배포**: 배포 완료 후 제공되는 도메인 주소(예: `https://port-0-molit-rtms-mcp-xxxxx.cloudtype.app`)를 확인합니다.
5. **헬스체크**: 웹 브라우저로 서비스 루트 경로(`https://[your-domain]/`)에 접속하여 `ok`가 반환되는지 확인합니다. MCP 엔드포인트는 `https://[your-domain]/mcp` 입니다.

---

## 🔌 MCP 클라이언트 등록 (Claude Desktop 설정)

`claude_desktop_config.json`에 다음 중 하나의 방식을 추가하여 프롬프트 상에서 즉시 조회 툴을 사용할 수 있습니다.

### 1. 원격 배포 방식 (클라우드타입 배포 후 권장)
원격 Streamable HTTP 서버에 연결할 때는 `mcp-remote` 브리지를 사용합니다. (Node.js 설치 필요)
```json
{
  "mcpServers": {
    "molit-rtms-mcp": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://port-0-molit-rtms-mcp-xxxxx.cloudtype.app/mcp"
      ]
    }
  }
}
```

### 2. 로컬 Stdio 방식
```json
{
  "mcpServers": {
    "molit-rtms-mcp": {
      "command": "C:\\Users\\10564\\Documents\\LandPrice_MCP\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\10564\\Documents\\LandPrice_MCP\\server.py",
        "stdio"
      ],
      "env": {
        "MOLIT_SERVICE_KEY": "your_decoding_service_key_here"
      }
    }
  }
}
```

> 설정을 저장한 뒤 Claude Desktop을 완전히 종료 후 재시작해야 커넥터가 인식됩니다.

---

## 🛠️ 제공하는 툴 명세

1. **`health_check`**: API 호출 가용성 및 인증 상태 진단
2. **`search_land_transactions`**: 토지 실거래가 조회 및 지목/용도지역 필터 지원
3. **`search_commercial_transactions`**: 상업업무용 빌딩/상가 거래 실거래가 조회 및 대지/연면적 이중 평단가 제공
4. **`search_apartment_transactions`**: 아파트 실거래가 상세 조회 및 등기일자, 매도/매수 거래주체 확장 필드 스크리닝 제공
