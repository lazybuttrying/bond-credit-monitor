"""Fetch financial ratios from DART (OpenDART API) for bond issuers.

Requires DART_API_KEY env var (40-char key from opendart.fss.or.kr).
Maps bond issuer names -> DART corp codes -> key financial metrics.

Metrics fetched (annual, consolidated):
  - debt_ratio: 부채비율 = 부채총계 / 자본총계 * 100
  - interest_coverage: 이자보상배율 = 영업이익 / 이자비용
  - current_ratio: 유동비율 = 유동자산 / 유동부채 * 100
  - roe: 자기자본이익률 = 당기순이익 / 자본총계 * 100

Output: dart_financials.json {issuer: {corp_code, corp_name, year, metrics...}}
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api"
DATA = os.path.dirname(os.path.abspath(__file__))

# bond issuer name -> DART corp name hint (for manual mapping when auto fails)
ISSUER_HINTS = {
    "국민은행": "KB국민은행",
    "신한은행": "신한은행",
    "하나은행": "하나은행",
    "우리은행": "우리은행",
    "중소기업은행": "기업은행",
    "한국전력공사채권": "한국전력공사",
    "토지주택채권": "한국토지주택공사",
    "한국주택금융공사": "한국주택금융공사",
    "한국주택금융공사MBS": "한국주택금융공사",
    "산업금융채권": "한국산업은행",
    "농업금융채권": "농협",
    "수산금융채권": "수협",
    "한국수출입금융": "한국수출입은행",
    "외국환평형기금채권": None,  # government fund, no corp
    "통화안정증권": None,  # BOK, no corp
    "통화안정증권DC": None,
    "국민주택": None,  # government
}


def api_get(path, params):
    params["crtfc_key"] = API_KEY
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get_corp_codes():
    """Download corp code mapping. Returns {corp_name: corp_code}."""
    import zipfile
    import io
    import xml.etree.ElementTree as ET

    url = f"{BASE}/corpCode.xml?crtfc_key={API_KEY}"
    with urllib.request.urlopen(url, timeout=60) as r:
        zf = zipfile.ZipFile(io.BytesIO(r.read()))
        xml_data = zf.read("CORPCODE.xml")
    root = ET.fromstring(xml_data)
    out = {}
    for corp in root.findall("list"):
        name = corp.findtext("corp_name", "").strip()
        code = corp.findtext("corp_code", "").strip()
        if name and code:
            out[name] = code
    return out


def fetch_metrics(corp_code, year="2024"):
    """Fetch key financial metrics for a corp (annual, consolidated)."""
    # reprt_code 11011 = annual report
    data = api_get("fnlttSinglAcnt.json", {
        "corp_code": corp_code,
        "bsns_year": year,
        "reprt_code": "11011",
    })
    if data.get("status") != "000":
        return {"error": data.get("message", "unknown")}
    # map account names to values (thousands of KRW, CFS)
    vals = {}
    for row in data.get("list", []):
        if row.get("fs_div") != "CFS":
            continue
        nm = row.get("account_nm", "").replace(" ", "")
        amt = row.get("thstrm_amount", "").replace(",", "")
        try:
            vals[nm] = int(amt) if amt and amt != "-" else None
        except ValueError:
            pass
    def get(*names):
        for n in names:
            if n in vals and vals[n] is not None:
                return vals[n]
        return None
    debt = get("부채총계")
    equity = get("자본총계")
    op_profit = get("영업이익")
    interest = get("이자비용", "금융비용")
    current_a = get("유동자산")
    current_l = get("유동부채")
    net_income = get("당기순이익", "당기순이익(손실)")
    out = {}
    if debt and equity:
        out["debt_ratio"] = round(debt / equity * 100, 1)
    if op_profit is not None and interest:
        out["interest_coverage"] = round(op_profit / interest, 2) if interest else None
    if current_a and current_l:
        out["current_ratio"] = round(current_a / current_l * 100, 1)
    if net_income is not None and equity:
        out["roe"] = round(net_income / equity * 100, 2)
    return out


def main():
    if not API_KEY:
        print("DART_API_KEY env var not set", file=sys.stderr)
        sys.exit(1)
    with open(os.path.join(DATA, "issuers.json")) as f:
        iss = json.load(f)
    issuers = sorted(set(r["issuer"] for r in iss["latest_table"]))
    print(f"issuers: {len(issuers)}, fetching corp codes...")
    codes = get_corp_codes()
    print(f"corp codes: {len(codes)}")
    result = {}
    for name in issuers:
        hint = ISSUER_HINTS.get(name, name)
        if hint is None:
            result[name] = {"skip": "non-corporate"}
            continue
        code = codes.get(hint) or codes.get(name)
        if not code:
            # try partial match
            for cn, cc in codes.items():
                if hint in cn or cn in hint:
                    code = cc
                    hint = cn
                    break
        if not code:
            result[name] = {"skip": "corp code not found"}
            continue
        time.sleep(0.3)  # rate limit courtesy
        m = fetch_metrics(code)
        result[name] = {"corp_code": code, "corp_name": hint, "year": "2024", **m}
        print(f"  {name} -> {hint}: {m}")
    with open(os.path.join(DATA, "dart_financials.json"), "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    ok = sum(1 for v in result.values() if "debt_ratio" in v)
    print(f"done: {ok}/{len(issuers)} with metrics")


if __name__ == "__main__":
    main()
