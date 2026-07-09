import os
import requests
import xmltodict
from dotenv import load_dotenv
import urllib.parse

load_dotenv()
key = urllib.parse.unquote(os.environ.get("MOLIT_SERVICE_KEY"))

url = "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
params = {
    "serviceKey": key,
    "LAWD_CD": "11140",
    "DEAL_YMD": "202605",
    "numOfRows": "100",  # Get more items to see different fields
    "pageNo": "1"
}

try:
    response = requests.get(url, params=params, timeout=15)
    data_dict = xmltodict.parse(response.text)
    body = data_dict.get("response", {}).get("body", {})
    items_node = body.get("items", {})
    if items_node and "item" in items_node:
        items = items_node["item"]
        if isinstance(items, dict):
            items = [items]
            
        print(f"Retrieved {len(items)} items.")
        
        # Check all unique keys
        all_keys = set()
        for item in items:
            all_keys.update(item.keys())
            
        print("\nAll unique keys found across all items:")
        for k in sorted(all_keys):
            print(f"- {k}")
            
        print("\nSample items details (Safe print):")
        # Print first 3 items safely
        for idx, item in enumerate(items[:5]):
            print(f"\nItem {idx + 1}:")
            for k, v in item.items():
                if v is not None:
                    # Safe print Korean characters
                    print(f"  {k}: {repr(v)}")
                else:
                    print(f"  {k}: None")
    else:
        print("No items found.")
except Exception as e:
    print("Error:", e)
