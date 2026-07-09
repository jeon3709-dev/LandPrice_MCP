import os
import sys
import re
import logging
import urllib.parse
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
import httpx
import xmltodict
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("molit-rtms-mcp")

# Masking serviceKey in logging and responses
def sanitize_error(msg: str) -> str:
    """Mask the MOLIT_SERVICE_KEY in error messages or logs to prevent credential leakage."""
    if not msg:
        return ""
    msg = re.sub(r'(serviceKey=)[^&\'"\s]+', r'\g<1>***', msg)
    msg = re.sub(r'(key=)[^&\'"\s]+', r'\g<1>***', msg)
    key = os.environ.get("MOLIT_SERVICE_KEY")
    if key and len(key) > 8:
        msg = msg.replace(key, "***")
        decoded_key = urllib.parse.unquote(key)
        if decoded_key and len(decoded_key) > 8:
            msg = msg.replace(decoded_key, "***")
    return msg

# Load environment variables
load_dotenv()

# Initialize FastMCP Server
port_env = os.environ.get("PORT")
is_sse = bool(port_env) or ("sse" in sys.argv)
mcp_port = int(port_env) if port_env else 8080
mcp_host = "0.0.0.0" if is_sse else "127.0.0.1"

mcp = FastMCP(
    "MOLIT Real Estate Transactions Server",
    host=mcp_host,
    port=mcp_port,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

BASE_URL = "https://apis.data.go.kr/1613000"
DB_FILE = os.path.join(os.path.dirname(__file__), "code_bdong.json")
_bdong_db = None

def get_service_key() -> str:
    """Retrieve and decode the API service key to ensure single-encoding by httpx."""
    key = os.environ.get("MOLIT_SERVICE_KEY")
    if not key or key == "your_service_key_here":
        raise ValueError(
            "MOLIT_SERVICE_KEY is not set in the environment variables. "
            "Please configure MOLIT_SERVICE_KEY in your environment or .env file."
        )
    return urllib.parse.unquote(key)

def get_api_headers() -> Dict[str, str]:
    """Return common headers to mimic a browser and prevent Cloud WAF blocking."""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/xml, text/xml, */*"
    }

# --- Legal Dong Code Resolution ---

def load_bdong_db() -> Dict[str, Any]:
    """Lazy load the static legal dong code database."""
    global _bdong_db
    if _bdong_db is not None:
        return _bdong_db
    
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError(
            f"Legal dong code database not found at {DB_FILE}. "
            "Please ensure you run download_db.py first or place the file in the server directory."
        )
    
    logger.info(f"Loading legal dong code database from {DB_FILE}...")
    with open(DB_FILE, "r", encoding="utf-8") as f:
        _bdong_db = json.load(f)
    logger.info("Legal dong code database loaded successfully.")
    return _bdong_db

def clean_str(val: Any) -> str:
    """Clean empty, nan, null strings to empty string."""
    if val is None:
        return ""
    val_str = str(val).strip()
    if val_str.lower() in ["nan", "none", "null"]:
        return ""
    return val_str

def resolve_lawd_cd(sido: Optional[str], sigungu: str, dong: str) -> Dict[str, Any]:
    """
    Resolve sido + sigungu + dong into a 5-digit LAWD_CD (sigungu code).
    Handles potential ambiguities and returns details.
    """
    db = load_bdong_db()
    df_data = db.get("data", {})
    
    sido_col = df_data.get("시도명", {})
    sigungu_col = df_data.get("시군구명", {})
    dong_col = df_data.get("읍면동명", {})
    code_col = df_data.get("법정동코드", {})
    malso_col = df_data.get("말소일자", {})
    
    # Strip spaces
    sigungu = sigungu.strip()
    dong = dong.strip()
    if sido:
        sido = sido.strip()
        
    candidates = []
    for idx, code in code_col.items():
        # Exclude deleted
        malso = clean_str(malso_col.get(idx))
        if malso:
            continue
            
        sd = clean_str(sido_col.get(idx))
        sgg = clean_str(sigungu_col.get(idx))
        d = clean_str(dong_col.get(idx))
        
        # Sigungu match
        sgg_match = sigungu in sgg if sgg else False
        
        # Dong match (target starts with db_dong or vice versa to cover sub-dongs)
        # E.g. "광희동" matches "광희동1가"
        d_match = (d.startswith(dong) or dong.startswith(d)) if d else False
        
        # Sido match (optional)
        s_match = True
        if sido:
            s_match = sido in sd if sd else False
            
        if sgg_match and d_match and s_match:
            candidates.append({
                "sido": sd,
                "sigungu": sgg,
                "dong": d,
                "code": code
            })
            
    if not candidates:
        return {
            "status": "NOT_FOUND",
            "message": f"No legal dong code found matching: [Sido: {sido or 'Any'}, Sigungu: {sigungu}, Dong: {dong}]."
        }
        
    # Group by the first 5 digits (sigungu code)
    lawd_cds: Dict[str, List[Dict[str, str]]] = {}
    for c in candidates:
        lawd_cd = c["code"][:5]
        if lawd_cd not in lawd_cds:
            lawd_cds[lawd_cd] = []
        lawd_cds[lawd_cd].append(c)
        
    if len(lawd_cds) > 1:
        # Ambiguous! Suggest clarification
        msg = f"Multiple region candidates found for [Sigungu: {sigungu}, Dong: {dong}]. Please narrow down your search:\n"
        for cd, c_list in lawd_cds.items():
            paths = ", ".join([f"{c['sido']} {c['sigungu']} {c['dong']}" for c in c_list])
            msg += f"- LAWD_CD: {cd} ({paths})\n"
        return {
            "status": "AMBIGUOUS",
            "message": msg,
            "candidates": candidates
        }
        
    # Succeeded
    matched_lawd_cd = list(lawd_cds.keys())[0]
    matched_dongs = [c["dong"] for c in lawd_cds[matched_lawd_cd]]
    
    return {
        "status": "OK",
        "lawd_cd": matched_lawd_cd,
        "matched_dongs": matched_dongs,
        "candidates": candidates
    }

# --- Core Fetching Logic ---

def get_months_list(months_back: int) -> List[str]:
    """Generate YYYYMM contract months backwards from current date."""
    now = datetime.now()
    months = []
    curr_year = now.year
    curr_month = now.month
    
    for _ in range(months_back):
        months.append(f"{curr_year}{str(curr_month).zfill(2)}")
        curr_month -= 1
        if curr_month == 0:
            curr_month = 12
            curr_year -= 1
    return months

async def fetch_api_data(
    endpoint_name: str,
    lawd_cd: str,
    months: List[str]
) -> Tuple[str, List[Dict[str, Any]]]:
    """Fetch raw XML data from data.go.kr for given months list and parse to dictionaries."""
    try:
        service_key = get_service_key()
    except ValueError as e:
        return "ERROR", [{"error": str(e)}]
        
    url = f"{BASE_URL}/{endpoint_name}/get{endpoint_name}"
    headers = get_api_headers()
    all_items = []
    
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        for ymd in months:
            page = 1
            while True:
                params = {
                    "serviceKey": service_key,
                    "LAWD_CD": lawd_cd,
                    "DEAL_YMD": ymd,
                    "numOfRows": "100",
                    "pageNo": str(page)
                }
                
                try:
                    logger.info(f"Requesting {endpoint_name} for {ymd} (page {page})...")
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    
                    xml_text = response.text
                    # Check for auth errors in text response
                    if "<errMsg>" in xml_text or "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in xml_text:
                        err_match = re.search(r"<errMsg>(.*?)</errMsg>", xml_text)
                        err_msg = err_match.group(1) if err_match else "Authentication Error"
                        return "AUTH_ERROR", [{"error": f"OpenAPI Authentication Failure: {err_msg}"}]
                        
                    data = xmltodict.parse(xml_text)
                    res_node = data.get("response", {})
                    header = res_node.get("header", {})
                    result_code = header.get("resultCode")
                    result_msg = header.get("resultMsg", "No message")
                    
                    if result_code != "000" and result_code != "00":
                        logger.error(f"API returned error [{result_code}]: {result_msg} for month {ymd}")
                        break
                        
                    body = res_node.get("body", {})
                    items_node = body.get("items")
                    month_items = []
                    if items_node and "item" in items_node:
                        item_list = items_node["item"]
                        if isinstance(item_list, dict):
                            month_items = [item_list]
                        elif isinstance(item_list, list):
                            month_items = item_list
                            
                    all_items.extend(month_items)
                    
                    # Pagination logic
                    total_count_str = body.get("totalCount")
                    num_of_rows_str = body.get("numOfRows")
                    
                    if total_count_str and num_of_rows_str:
                        total_count = int(total_count_str)
                        num_of_rows = int(num_of_rows_str)
                        if total_count > page * num_of_rows:
                            page += 1
                        else:
                            break
                    else:
                        break
                        
                except httpx.HTTPError as e:
                    logger.error(f"HTTP Network error on {ymd} page {page}: {sanitize_error(str(e))}")
                    break
                except Exception as e:
                    logger.error(f"Unexpected parsing error on {ymd} page {page}: {str(e)}")
                    break
                    
    return "OK", all_items

# --- Utility Calculations ---

def clean_amount(val: Any) -> int:
    """Parse transaction amount string (with commas) into integer (만원)."""
    if not val:
        return 0
    val_str = str(val).replace(",", "").strip()
    try:
        return int(val_str)
    except ValueError:
        return 0

def format_price(amount_man: int) -> str:
    """Format transaction amount into '억원' and '만원' representation."""
    if amount_man >= 10000:
        uk = amount_man // 10000
        man = amount_man % 10000
        if man > 0:
            return f"{uk}억 {man:,}만원"
        else:
            return f"{uk}억원"
    return f"{amount_man:,}만원"

def clean_area(val: Any) -> float:
    """Parse size/area float value."""
    if not val:
        return 0.0
    try:
        return float(str(val).strip())
    except ValueError:
        return 0.0

def calc_price_per_pyung(amount_man: int, area_m2: float) -> float:
    """Calculate price per pyung in unit '만원/평'."""
    if not area_m2 or area_m2 <= 0:
        return 0.0
    pyung = area_m2 * 0.3025
    return round(amount_man / pyung, 1)

def check_share_deal(item: Dict[str, Any]) -> bool:
    """Check if the item is a share deal (지분거래)."""
    # Key name in Land and Commercial is shareDealingType
    st = clean_str(item.get("shareDealingType"))
    if st and st != "None":
        return True
    return False

def check_cancelled_deal(item: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if the transaction is cancelled."""
    c_day = clean_str(item.get("cdealDay"))
    c_type = clean_str(item.get("cdealType"))
    
    # If cdealDay is not empty or cdealType is 'O' / 'o'
    is_cancelled = False
    if c_day or c_type in ["O", "o", "1", "Y", "y", "true"]:
        is_cancelled = True
        
    return is_cancelled, c_day

# --- Median calculation ---
def calculate_median(values: List[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        return sorted_vals[n // 2]
    else:
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0

# --- General Enrichment & Output formatter ---

def create_summary_block(
    records: List[Dict[str, Any]], 
    filter_details: str,
    asset_type: str
) -> Tuple[Dict[str, Any], str]:
    """Create stats summary dict and formatted markdown block."""
    total_count = len(records)
    
    # Filter valid items (excluding share and cancelled deals)
    valid_records = [r for r in records if not r["is_share"] and not r["is_cancelled"]]
    valid_count = len(valid_records)
    
    # Extract periods
    dates = [r["deal_date"] for r in records if r["deal_date"]]
    period = f"{min(dates)[:7]} ~ {max(dates)[:7]}" if dates else "N/A"
    
    summary = {
        "total_count": total_count,
        "valid_count": valid_count,
        "period": period,
        "filter_details": filter_details
    }
    
    md = f"### 📊 거래 분석 요약 ({asset_type})\n"
    md += f"- **조회 기간**: {period}\n"
    md += f"- **총 거래건수**: {total_count}건 (유효거래: {valid_count}건 / 지분·해제 거래 제외)\n"
    md += f"- **적용 필터**: {filter_details}\n"
    
    if asset_type == "상업업무용":
        # Dual price summaries
        land_prices = [r["price_per_land_pyung"] for r in valid_records if r["price_per_land_pyung"] > 0]
        bld_prices = [r["price_per_building_pyung"] for r in valid_records if r["price_per_building_pyung"] > 0]
        
        summary["land_price_stats"] = {
            "min": min(land_prices) if land_prices else 0.0,
            "max": max(land_prices) if land_prices else 0.0,
            "median": calculate_median(land_prices) if land_prices else 0.0
        }
        summary["building_price_stats"] = {
            "min": min(bld_prices) if bld_prices else 0.0,
            "max": max(bld_prices) if bld_prices else 0.0,
            "median": calculate_median(bld_prices) if bld_prices else 0.0
        }
        
        md += "#### 🔹 평단가 통계 (만원/평)\n"
        md += "| 구분 | 최소값 | 최대값 | 중위값 |\n"
        md += "| :--- | :---: | :---: | :---: |\n"
        if land_prices:
            md += f"| **대지 평단가** | {min(land_prices):,} 만원 | {max(land_prices):,} 만원 | {calculate_median(land_prices):,} 만원 |\n"
        else:
            md += "| **대지 평단가** | N/A | N/A | N/A |\n"
        if bld_prices:
            md += f"| **연면적 평단가** | {min(bld_prices):,} 만원 | {max(bld_prices):,} 만원 | {calculate_median(bld_prices):,} 만원 |\n"
        else:
            md += "| **연면적 평단가** | N/A | N/A | N/A |\n"
    else:
        # Standard price summaries
        prices = [r["price_per_pyung"] for r in valid_records if r["price_per_pyung"] > 0]
        summary["price_stats"] = {
            "min": min(prices) if prices else 0.0,
            "max": max(prices) if prices else 0.0,
            "median": calculate_median(prices) if prices else 0.0
        }
        md += "#### 🔹 평단가 통계 (만원/평)\n"
        if prices:
            md += f"- **최소 평단가**: {min(prices):,} 만원/평\n"
            md += f"- **최대 평단가**: {max(prices):,} 만원/평\n"
            md += f"- **중위 평단가**: {calculate_median(prices):,} 만원/평\n"
        else:
            md += "- **평단가**: N/A\n"
            
    return summary, md

def handle_empty_fallback(sido: Optional[str], sigungu: str, dong: str, months_back: int, filter_str: str) -> Dict[str, Any]:
    """Return a helpful suggestion message when zero transactions matched."""
    msg = (
        f"⚠️ **조회 결과 거래 사례가 0건입니다.**\n\n"
        f"**검색 조건**:\n"
        f"- 지역: {sido or ''} {sigungu} {dong}\n"
        f"- 기간: 최근 {months_back}개월\n"
        f"- 상세 필터: {filter_str}\n\n"
        f"**제안사항**:\n"
        f"1. **조회 기간 확대**: 툴 호출 시 `months_back` 값을 더 크게 설정(예: 60개월 또는 120개월)하여 조회 기간을 넓혀보세요.\n"
        f"2. **인접 법정동 조회**: 인접한 다른 법정동(동명)을 입력하여 거래 사례를 비교해 보세요."
    )
    return {
        "status": "NO_DATA",
        "message": msg,
        "summary": {
            "total_count": 0,
            "valid_count": 0,
            "period": "N/A",
            "filter_details": filter_str
        },
        "report": msg,
        "transactions": []
    }

# --- MCP Tool Registrations ---

@mcp.tool()
async def search_land_transactions(
    sigungu: str,
    dong: str,
    sido: Optional[str] = None,
    months_back: int = 36,
    exclude_share_deals: bool = True,
    exclude_cancelled: bool = True,
    zone_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    토지 거래 실거래가 정보를 조회합니다.
    자연어 프롬프트("중구 광희동 최근 36개월 토지거래")에 대응하여 클라이언트가 호출합니다.
    
    sigungu: 시군구명 (예: "중구")
    dong: 법정동명 (예: "광희동")
    sido: 시도명 (선택, 예: "서울특별시")
    months_back: 최근 N개월 조회 범위 (선택, 기본 36)
    exclude_share_deals: 지분거래 제외 여부 (선택, 기본 True)
    exclude_cancelled: 계약해제건 제외 여부 (선택, 기본 True)
    zone_filter: 용도지역 필터 (선택, 예: "일반상업지역". 지정된 경우 해당 용도지역의 거래건만 필터링)
    """
    logger.info(f"search_land_transactions called for Sigungu: {sigungu}, Dong: {dong}, Sido: {sido}")
    
    # 1. Resolve LAWD_CD
    resolved = resolve_lawd_cd(sido, sigungu, dong)
    if resolved["status"] != "OK":
        return resolved
        
    lawd_cd = resolved["lawd_cd"]
    matched_dongs = resolved["matched_dongs"]
    
    # 2. Generate months list
    months = get_months_list(months_back)
    
    # 3. Fetch data
    status, items = await fetch_api_data("RTMSDataSvcLandTrade", lawd_cd, months)
    if status != "OK":
        return {"status": "ERROR", "message": items[0].get("error", "Failed to retrieve transactions.")}
        
    # 4. Enrich & Filter
    records = []
    for item in items:
        # Re-filter by dong
        umd = clean_str(item.get("umdNm"))
        if umd not in matched_dongs:
            continue
            
        # Filter by zone_filter (용도지역)
        land_use = clean_str(item.get("landUse"))
        if zone_filter and zone_filter not in land_use:
            continue
            
        # Flags
        is_share = check_share_deal(item)
        if exclude_share_deals and is_share:
            continue
            
        is_cancelled, cancel_date = check_cancelled_deal(item)
        if exclude_cancelled and is_cancelled:
            continue
            
        # Parse price and area
        amount_man = clean_amount(item.get("dealAmount"))
        area_m2 = clean_area(item.get("dealArea"))
        pyung = round(area_m2 * 0.3025, 2)
        price_pyung = calc_price_per_pyung(amount_man, area_m2)
        
        # Contract date
        yr = clean_str(item.get("dealYear"))
        mo = clean_str(item.get("dealMonth")).zfill(2)
        dy = clean_str(item.get("dealDay")).zfill(2)
        deal_date = f"{yr}-{mo}-{dy}" if yr and mo and dy else "N/A"
        
        jimok = clean_str(item.get("jimok"))
        
        records.append({
            "address": f"{umd} {clean_str(item.get('jibun'))}",
            "jimok": jimok,
            "land_use": land_use,
            "asset_character": f"지목: {jimok} / 용도지역: {land_use}",
            "area_m2": area_m2,
            "area_pyung": pyung,
            "amount_man": amount_man,
            "amount_formatted": format_price(amount_man),
            "price_per_pyung": price_pyung,
            "deal_date": deal_date,
            "trade_type": clean_str(item.get("dealingGbn")),
            "agent_location": clean_str(item.get("estateAgentSggNm")),
            "is_share": is_share,
            "is_cancelled": is_cancelled,
            "cancel_date": cancel_date
        })
        
    # Handle 0 results
    filter_desc = f"용도지역 필터: {zone_filter or '없음'}"
    if not records:
        return handle_empty_fallback(sido, sigungu, dong, months_back, filter_desc)
        
    # Sort by date descending
    records.sort(key=lambda x: x["deal_date"], reverse=True)
    
    # 5. Summarize
    summary, summary_md = create_summary_block(records, filter_desc, "토지")
    
    # 6. Format Markdown Report
    report = f"## 🗺️ 토지 실거래가 조회 결과 ({sigungu} {dong})\n\n"
    report += summary_md + "\n"
    report += "### 📋 거래 상세 사례 목록\n"
    report += "| 번호 | 소재지 | 지목 | 용도지역 | 면적(㎡/평) | 거래금액 | 평단가(만원/평) | 계약일 | 거래유형 | 비고 |\n"
    report += "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    
    for idx, r in enumerate(records):
        flags = []
        if r["is_share"]:
            flags.append("지분")
        if r["is_cancelled"]:
            flags.append(f"해제({r['cancel_date']})")
        flag_str = ", ".join(flags) if flags else "-"
        
        report += (
            f"| {idx + 1} | {r['address']} | {r['jimok']} | {r['land_use']} | "
            f"{r['area_m2']}㎡ / {r['area_pyung']}평 | {r['amount_formatted']} | "
            f"{r['price_per_pyung']:,} 만원 | {r['deal_date']} | {r['trade_type'] or '-'} | {flag_str} |\n"
        )
        
    return {
        "status": "OK",
        "summary": summary,
        "report": report,
        "transactions": records
    }

@mcp.tool()
async def search_commercial_transactions(
    sigungu: str,
    dong: str,
    sido: Optional[str] = None,
    months_back: int = 36,
    exclude_share_deals: bool = True,
    exclude_cancelled: bool = True,
    building_use_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    상업업무용 빌딩/상가 거래 실거래가 정보를 조회합니다.
    대지면적 기준 평단가와 건물 연면적 기준 평단가(이중 평단가)를 제공합니다.
    
    sigungu: 시군구명 (예: "중구")
    dong: 법정동명 (예: "광희동")
    sido: 시도명 (선택, 예: "서울특별시")
    months_back: 최근 N개월 조회 범위 (선택, 기본 36)
    exclude_share_deals: 지분거래 제외 여부 (선택, 기본 True)
    exclude_cancelled: 계약해제건 제외 여부 (선택, 기본 True)
    building_use_filter: 건물주용도 필터 (선택, 예: "제2종근린생활". 지정된 경우 해당 용도 포함 거래만 필터링)
    """
    logger.info(f"search_commercial_transactions called for Sigungu: {sigungu}, Dong: {dong}, Sido: {sido}")
    
    # 1. Resolve LAWD_CD
    resolved = resolve_lawd_cd(sido, sigungu, dong)
    if resolved["status"] != "OK":
        return resolved
        
    lawd_cd = resolved["lawd_cd"]
    matched_dongs = resolved["matched_dongs"]
    
    # 2. Generate months list
    months = get_months_list(months_back)
    
    # 3. Fetch data
    status, items = await fetch_api_data("RTMSDataSvcNrgTrade", lawd_cd, months)
    if status != "OK":
        return {"status": "ERROR", "message": items[0].get("error", "Failed to retrieve transactions.")}
        
    # 4. Enrich & Filter
    records = []
    for item in items:
        # Re-filter by dong
        umd = clean_str(item.get("umdNm"))
        if umd not in matched_dongs:
            continue
            
        # Filter by building_use_filter (건물주용도)
        bld_use = clean_str(item.get("buildingUse"))
        if building_use_filter and building_use_filter not in bld_use:
            continue
            
        # Flags
        is_share = check_share_deal(item)
        if exclude_share_deals and is_share:
            continue
            
        is_cancelled, cancel_date = check_cancelled_deal(item)
        if exclude_cancelled and is_cancelled:
            continue
            
        # Parse sizes and prices
        amount_man = clean_amount(item.get("dealAmount"))
        
        # plottageAr: 대지면적
        plottage_m2 = clean_area(item.get("plottageAr"))
        plottage_pyung = round(plottage_m2 * 0.3025, 2)
        price_land_pyung = calc_price_per_pyung(amount_man, plottage_m2) if plottage_m2 > 0 else 0.0
        
        # buildingAr: 건물 거래 연면적/전용면적
        building_m2 = clean_area(item.get("buildingAr"))
        building_pyung = round(building_m2 * 0.3025, 2)
        price_bld_pyung = calc_price_per_pyung(amount_man, building_m2) if building_m2 > 0 else 0.0
        
        # Contract date
        yr = clean_str(item.get("dealYear"))
        mo = clean_str(item.get("dealMonth")).zfill(2)
        dy = clean_str(item.get("dealDay")).zfill(2)
        deal_date = f"{yr}-{mo}-{dy}" if yr and mo and dy else "N/A"
        
        bld_type = clean_str(item.get("buildingType"))
        
        records.append({
            "address": f"{umd} {clean_str(item.get('jibun'))}",
            "building_use": bld_use,
            "building_type": bld_type,
            "asset_character": f"주용도: {bld_use} / 유형: {bld_type}",
            "plottage_m2": plottage_m2,
            "plottage_pyung": plottage_pyung,
            "building_m2": building_m2,
            "building_pyung": building_pyung,
            "amount_man": amount_man,
            "amount_formatted": format_price(amount_man),
            "price_per_land_pyung": price_land_pyung,
            "price_per_building_pyung": price_bld_pyung,
            "deal_date": deal_date,
            "trade_type": clean_str(item.get("dealingGbn")),
            "agent_location": clean_str(item.get("estateAgentSggNm")),
            "floor": clean_str(item.get("floor")),
            "build_year": clean_str(item.get("buildYear")),
            "is_share": is_share,
            "is_cancelled": is_cancelled,
            "cancel_date": cancel_date
        })
        
    # Handle 0 results
    filter_desc = f"건물주용도 필터: {building_use_filter or '없음'}"
    if not records:
        return handle_empty_fallback(sido, sigungu, dong, months_back, filter_desc)
        
    # Sort by date descending
    records.sort(key=lambda x: x["deal_date"], reverse=True)
    
    # 5. Summarize
    summary, summary_md = create_summary_block(records, filter_desc, "상업업무용")
    
    # 6. Format Markdown Report
    report = f"## 🏢 상업업무용 실거래가 조회 결과 ({sigungu} {dong})\n\n"
    report += summary_md + "\n"
    report += "### 📋 거래 상세 사례 목록\n"
    report += "| 번호 | 소재지 | 주용도 | 유형 | 대지면적(㎡/평) | 건물면적(㎡/평) | 거래금액 | 대지 평단가 | 건물 평단가 | 계약일 | 비고 |\n"
    report += "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    
    for idx, r in enumerate(records):
        flags = []
        if r["is_share"]:
            flags.append("지분")
        if r["is_cancelled"]:
            flags.append(f"해제({r['cancel_date']})")
        if r["floor"]:
            flags.append(f"{r['floor']}층")
        flag_str = ", ".join(flags) if flags else "-"
        
        plottage_str = f"{r['plottage_m2']}㎡ / {r['plottage_pyung']}평" if r["plottage_m2"] > 0 else "N/A"
        price_land_str = f"{r['price_per_land_pyung']:,} 만원" if r["price_per_land_pyung"] > 0 else "N/A"
        
        building_str = f"{r['building_m2']}㎡ / {r['building_pyung']}평"
        price_bld_str = f"{r['price_per_building_pyung']:,} 만원"
        
        report += (
            f"| {idx + 1} | {r['address']} | {r['building_use']} | {r['building_type']} | "
            f"{plottage_str} | {building_str} | {r['amount_formatted']} | "
            f"{price_land_str} | {price_bld_str} | {r['deal_date']} | {flag_str} |\n"
        )
        
    return {
        "status": "OK",
        "summary": summary,
        "report": report,
        "transactions": records
    }

@mcp.tool()
async def search_apartment_transactions(
    sigungu: str,
    dong: str,
    sido: Optional[str] = None,
    months_back: int = 36,
    exclude_share_deals: bool = True,
    exclude_cancelled: bool = True,
    min_area: Optional[float] = None,
    max_area: Optional[float] = None,
    buyer_type_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    아파트 거래 실거래가 상세자료를 조회합니다.
    매도자/매수자 유형, 등기일자, 거래 유형 등 상세 확장 스크리닝 필드를 함께 분석하여 반환합니다.
    
    sigungu: 시군구명 (예: "중구")
    dong: 법정동명 (예: "광희동")
    sido: 시도명 (선택, 예: "서울특별시")
    months_back: 최근 N개월 조회 범위 (선택, 기본 36)
    exclude_share_deals: 지분거래 제외 여부 (선택, 기본 True)
    exclude_cancelled: 계약해제건 제외 여부 (선택, 기본 True)
    min_area: 최소 전용면적㎡ 범위 필터 (선택)
    max_area: 최대 전용면적㎡ 범위 필터 (선택)
    buyer_type_filter: 매수자 거래주체 필터 (선택, 예: "개인", "법인", "공공기관", "기타법인")
    """
    logger.info(f"search_apartment_transactions called for Sigungu: {sigungu}, Dong: {dong}, Sido: {sido}")
    
    # 1. Resolve LAWD_CD
    resolved = resolve_lawd_cd(sido, sigungu, dong)
    if resolved["status"] != "OK":
        return resolved
        
    lawd_cd = resolved["lawd_cd"]
    matched_dongs = resolved["matched_dongs"]
    
    # 2. Generate months list
    months = get_months_list(months_back)
    
    # 3. Fetch data
    status, items = await fetch_api_data("RTMSDataSvcAptTradeDev", lawd_cd, months)
    if status != "OK":
        return {"status": "ERROR", "message": items[0].get("error", "Failed to retrieve transactions.")}
        
    # 4. Enrich & Filter
    records = []
    for item in items:
        # Re-filter by dong
        umd = clean_str(item.get("umdNm"))
        if umd not in matched_dongs:
            continue
            
        # ExcluUseAr: 전용면적
        exclu_ar = clean_area(item.get("excluUseAr"))
        if min_area and exclu_ar < min_area:
            continue
        if max_area and exclu_ar > max_area:
            continue
            
        # Buyer type filter
        buyer_gbn = clean_str(item.get("buyerGbn"))
        if buyer_type_filter and buyer_type_filter not in buyer_gbn:
            continue
            
        # Flags
        is_share = check_share_deal(item)
        if exclude_share_deals and is_share:
            continue
            
        is_cancelled, cancel_date = check_cancelled_deal(item)
        if exclude_cancelled and is_cancelled:
            continue
            
        # Parse price and size
        amount_man = clean_amount(item.get("dealAmount"))
        pyung = round(exclu_ar * 0.3025, 2)
        price_pyung = calc_price_per_pyung(amount_man, exclu_ar)
        
        # Contract date
        yr = clean_str(item.get("dealYear"))
        mo = clean_str(item.get("dealMonth")).zfill(2)
        dy = clean_str(item.get("dealDay")).zfill(2)
        deal_date = f"{yr}-{mo}-{dy}" if yr and mo and dy else "N/A"
        
        apt_nm = clean_str(item.get("aptNm"))
        apt_dong = clean_str(item.get("aptDong"))
        floor = clean_str(item.get("floor"))
        
        records.append({
            "address": f"{umd} {clean_str(item.get('jibun'))}",
            "apt_name": apt_nm,
            "apt_dong": apt_dong,
            "floor": floor,
            "asset_character": f"단지: {apt_nm} / 동: {apt_dong or '미표기'} / {floor}층",
            "area_m2": exclu_ar,
            "area_pyung": pyung,
            "amount_man": amount_man,
            "amount_formatted": format_price(amount_man),
            "price_per_pyung": price_pyung,
            "deal_date": deal_date,
            "trade_type": clean_str(item.get("dealingGbn")),
            "agent_location": clean_str(item.get("estateAgentSggNm")),
            "buyer_gbn": buyer_gbn,
            "seller_gbn": clean_str(item.get("slerGbn")),
            "register_date": clean_str(item.get("rgstDate")),
            "land_leasehold": clean_str(item.get("landLeaseholdGbn")),
            "build_year": clean_str(item.get("buildYear")),
            "is_share": is_share,
            "is_cancelled": is_cancelled,
            "cancel_date": cancel_date
        })
        
    # Handle 0 results
    filters = []
    if min_area: filters.append(f"최소 면적: {min_area}㎡")
    if max_area: filters.append(f"최대 면적: {max_area}㎡")
    if buyer_type_filter: filters.append(f"매수자 주체: {buyer_type_filter}")
    filter_desc = ", ".join(filters) if filters else "없음"
    
    if not records:
        return handle_empty_fallback(sido, sigungu, dong, months_back, filter_desc)
        
    # Sort by date descending
    records.sort(key=lambda x: x["deal_date"], reverse=True)
    
    # 5. Summarize
    summary, summary_md = create_summary_block(records, filter_desc, "아파트(상세)")
    
    # 6. Format Markdown Report
    report = f"## 🏢 아파트 실거래가 상세 조회 결과 ({sigungu} {dong})\n\n"
    report += summary_md + "\n"
    report += "### 📋 거래 상세 사례 목록\n"
    report += "| 번호 | 단지명 | 동 | 전용면적(㎡/평) | 층 | 거래금액 | 평단가(만원/평) | 계약일 | 거래유형 | 매도/매수 | 등기일자 | 비고 |\n"
    report += "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    
    for idx, r in enumerate(records):
        flags = []
        if r["is_share"]:
            flags.append("지분")
        if r["is_cancelled"]:
            flags.append(f"해제({r['cancel_date']})")
        if r["land_leasehold"] == "Y":
            flags.append("토지임대부")
        flag_str = ", ".join(flags) if flags else "-"
        
        md_dong = r["apt_dong"] if r["apt_dong"] else "-"
        md_floor = f"{r['floor']}층" if r["floor"] else "-"
        md_rgst = r["register_date"] if r["register_date"] else "-"
        md_dealers = f"{r['seller_gbn'] or '-'} ➔ {r['buyer_gbn'] or '-'}"
        
        report += (
            f"| {idx + 1} | {r['apt_name']} | {md_dong} | {r['area_m2']}㎡ / {r['area_pyung']}평 | "
            f"{md_floor} | {r['amount_formatted']} | {r['price_per_pyung']:,} 만원 | "
            f"{r['deal_date']} | {r['trade_type'] or '-'} | {md_dealers} | {md_rgst} | {flag_str} |\n"
        )
        
    return {
        "status": "OK",
        "summary": summary,
        "report": report,
        "transactions": records
    }

@mcp.tool()
async def health_check() -> Dict[str, Any]:
    """
    인증키/네트워크/응답 연결성 진단 도구.
    서울 중구 소공동의 최근 1개월 아파트 거래사례 조회를 실행하여 HTTP 및 인증 정상 여부를 진단합니다.
    """
    import time
    start_time = time.time()
    
    try:
        service_key = get_service_key()
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Configuration error: {sanitize_error(str(e))}"
        }
        
    # Check legal dong code resolution
    resolved = resolve_lawd_cd("서울특별시", "중구", "소공동")
    if resolved["status"] != "OK":
        return {
            "status": "ERROR",
            "message": f"Legal Dong database check failed: {resolved.get('message')}"
        }
        
    lawd_cd = resolved["lawd_cd"]
    now = datetime.now()
    ymd = f"{now.year}{str(now.month).zfill(2)}"
    
    url = f"{BASE_URL}/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
    params = {
        "serviceKey": service_key,
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": ymd,
        "numOfRows": "1",
        "pageNo": "1"
    }
    
    headers = get_api_headers()
    
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        try:
            logger.info("Running health check API call...")
            response = await client.get(url, params=params)
            elapsed = round(time.time() - start_time, 3)
            status_code = response.status_code
            
            xml_text = response.text
            # Authenticate check
            if "<errMsg>" in xml_text or "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in xml_text:
                return {
                    "status": "AUTH_ERROR",
                    "elapsed_seconds": elapsed,
                    "http_status_code": status_code,
                    "message": "OpenAPI authentication failed. Please check your MOLIT_SERVICE_KEY."
                }
                
            return {
                "status": "OK",
                "http_status_code": status_code,
                "elapsed_seconds": elapsed,
                "message": "Connection diagnostic completed. MOLIT API is accessible and authenticated."
            }
        except Exception as e:
            elapsed = round(time.time() - start_time, 3)
            return {
                "status": "NETWORK_ERROR",
                "elapsed_seconds": elapsed,
                "message": f"MOLIT API connection failed: {sanitize_error(str(e))}"
            }

# --- ASGI Server Bootstrapper ---

if __name__ == "__main__":
    use_stdio = len(sys.argv) > 1 and sys.argv[1] == "stdio"
    if not use_stdio:
        logger.info(f"Starting MOLIT Real Estate Transactions MCP Server in HTTP transport mode...")

        # Base app = Streamable HTTP transport (endpoint: /mcp)
        app = mcp.streamable_http_app()

        # Legacy SSE transport (/sse + /messages/)
        from starlette.routing import Route
        from starlette.responses import PlainTextResponse
        app.router.routes.extend(mcp.sse_app().router.routes)

        # Health-check route
        async def _health(request):
            return PlainTextResponse("ok")
        app.router.routes.append(Route("/", _health, methods=["GET"]))

        # Disable buffering middleware
        class DisableBufferingMiddleware:
            def __init__(self, app):
                self.app = app
            async def __call__(self, scope, receive, send):
                if scope["type"] != "http":
                    await self.app(scope, receive, send)
                    return
                async def send_wrapper(message):
                    if message["type"] == "http.response.start":
                        headers = message.setdefault("headers", [])
                        headers.append((b"x-accel-buffering", b"no"))
                        headers.append((b"cache-control", b"no-cache, no-transform"))
                    await send(message)
                await self.app(scope, receive, send_wrapper)
        app.add_middleware(DisableBufferingMiddleware)
        
        # Permissive CORS middleware
        from starlette.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        import uvicorn
        logger.info(f"Running uvicorn on 0.0.0.0:{mcp_port} with CORS and buffering disabled...")
        uvicorn.run(app, host="0.0.0.0", port=mcp_port)
    else:
        mcp.run()
