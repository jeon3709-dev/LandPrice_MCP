import os
import requests
import xmltodict
from dotenv import load_dotenv
import urllib.parse

load_dotenv()

key = os.environ.get("MOLIT_SERVICE_KEY")
print("Raw Service Key length:", len(key) if key else 0)

# The service key from data.go.kr can be double encoded. 
# We decode it first to make sure it's raw, then pass it to requests.
# requests will encode it. If it fails, we will try with raw or other methods.
decoded_key = urllib.parse.unquote(key) if key else ""

def test_commercial():
    url = "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
    # Let's test for Seoul Jung-gu (11140) for 202605 (a recent month)
    params = {
        "serviceKey": decoded_key,
        "LAWD_CD": "11140",
        "DEAL_YMD": "202605",
        "numOfRows": "10",
        "pageNo": "1"
    }
    
    print("\n--- Testing Commercial API (RTMSDataSvcNrgTrade) ---")
    print(f"Requesting {url} with params (serviceKey masked):")
    masked_params = params.copy()
    masked_params["serviceKey"] = "***"
    print(masked_params)
    
    try:
        response = requests.get(url, params=params, timeout=15)
        print("Status Code:", response.status_code)
        print("Response text preview (500 chars):")
        print(response.text[:500])
        
        if response.status_code == 200:
            if "<errMsg>" in response.text or "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in response.text:
                print("API Key Authentication Failed!")
                return
                
            try:
                data_dict = xmltodict.parse(response.text)
                body = data_dict.get("response", {}).get("body", {})
                items_node = body.get("items", {})
                if items_node and "item" in items_node:
                    items = items_node["item"]
                    if isinstance(items, dict):
                        items = [items]
                    print(f"Successfully retrieved {len(items)} items!")
                    print("Sample item tags and values:")
                    first_item = items[0]
                    for k, v in first_item.items():
                        print(f"  {k}: {v}")
                else:
                    print("No items found. Response structure:")
                    print(data_dict)
            except Exception as e:
                print("Failed to parse XML:", e)
    except Exception as e:
        print("Request failed:", e)

if __name__ == "__main__":
    test_commercial()
