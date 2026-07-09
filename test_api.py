import asyncio
import json
import sys
from server import (
    health_check,
    search_land_transactions,
    search_commercial_transactions,
    search_apartment_transactions
)

def safe_print(text):
    if not isinstance(text, str):
        text = str(text)
    encoding = sys.stdout.encoding or 'utf-8'
    print(text.encode(encoding, errors='replace').decode(encoding))

async def run_tests():
    safe_print("=== [1] Running health_check ===")
    res_hc = await health_check()
    safe_print("Health Check Result:")
    safe_print(json.dumps(res_hc, indent=2, ensure_ascii=False))
    
    if res_hc.get("status") != "OK" and res_hc.get("status") != "AUTH_ERROR":
        safe_print("Health check encountered network or config error. Stopping tests.")
        return
        
    safe_print("\n=== [2] Testing search_land_transactions (광희동, 12 months) ===")
    res_land = await search_land_transactions(
        sido="서울특별시",
        sigungu="중구",
        dong="광희동",
        months_back=12
    )
    safe_print(f"Land Transactions Status: {res_land.get('status')}")
    if res_land.get("status") == "OK":
        safe_print(f"Transactions count: {len(res_land.get('transactions', []))}")
        safe_print(f"Summary stats: {res_land.get('summary')}")
        safe_print("\nReport Preview (First 400 chars):")
        safe_print(res_land.get("report")[:400])
    else:
        safe_print(f"Message: {res_land.get('message')}")
        
    safe_print("\n=== [3] Testing search_commercial_transactions (광희동, 12 months) ===")
    res_comm = await search_commercial_transactions(
        sido="서울특별시",
        sigungu="중구",
        dong="광희동",
        months_back=12
    )
    safe_print(f"Commercial Transactions Status: {res_comm.get('status')}")
    if res_comm.get("status") == "OK":
        safe_print(f"Transactions count: {len(res_comm.get('transactions', []))}")
        safe_print(f"Summary stats: {res_comm.get('summary')}")
        safe_print("\nReport Preview (First 400 chars):")
        safe_print(res_comm.get("report")[:400])
    else:
        safe_print(f"Message: {res_comm.get('message')}")
        
    safe_print("\n=== [4] Testing search_apartment_transactions (신당동, 6 months) ===")
    res_apt = await search_apartment_transactions(
        sido="서울특별시",
        sigungu="중구",
        dong="신당동",
        months_back=6
    )
    safe_print(f"Apartment Transactions Status: {res_apt.get('status')}")
    if res_apt.get("status") == "OK":
        safe_print(f"Transactions count: {len(res_apt.get('transactions', []))}")
        safe_print(f"Summary stats: {res_apt.get('summary')}")
        safe_print("\nReport Preview (First 400 chars):")
        safe_print(res_apt.get("report")[:400])
        
        # Verify detailed fields exist (e.g. buyer_gbn, register_date)
        if res_apt.get('transactions'):
            first = res_apt.get('transactions')[0]
            safe_print("\nApartment detailed sample fields:")
            safe_print(f"  Apt Name: {first.get('apt_name')}")
            safe_print(f"  Seller -> Buyer: {first.get('seller_gbn')} -> {first.get('buyer_gbn')}")
            safe_print(f"  Register Date: {first.get('register_date')}")
            safe_print(f"  Land Leasehold: {first.get('land_leasehold')}")
    else:
        safe_print(f"Message: {res_apt.get('message')}")
        
    safe_print("\n=== [5] Testing Zero-Result Fallback (광희동, 1 month, impossible filter) ===")
    res_fallback = await search_apartment_transactions(
        sido="서울특별시",
        sigungu="중구",
        dong="광희동",
        months_back=1,
        min_area=99999.0  # Impossible area to guarantee 0 matches
    )
    safe_print(f"Fallback Status (expected NO_DATA): {res_fallback.get('status')}")
    safe_print("Fallback Report / Message:")
    safe_print(res_fallback.get("report"))

if __name__ == "__main__":
    asyncio.run(run_tests())
