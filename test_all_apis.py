import os
import requests
import xmltodict
from dotenv import load_dotenv
import urllib.parse

load_dotenv()
key = urllib.parse.unquote(os.environ.get("MOLIT_SERVICE_KEY"))

# Endpoints
endpoints = {
    "land": "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",
    "commercial": "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
    "apartment": "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
}

def test_api(name, url):
    # Test with Seoul Jung-gu (11140) for 202605
    params = {
        "serviceKey": key,
        "LAWD_CD": "11140",
        "DEAL_YMD": "202605",
        "numOfRows": "20",
        "pageNo": "1"
    }
    print(f"\n=================== Testing {name.upper()} API ===================")
    try:
        response = requests.get(url, params=params, timeout=15)
        print("Status Code:", response.status_code)
        if response.status_code != 200:
            print("Failed to call API:", response.text[:300])
            return
            
        if "<errMsg>" in response.text or "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in response.text:
            print("Authentication failed!")
            return
            
        data_dict = xmltodict.parse(response.text)
        body = data_dict.get("response", {}).get("body", {})
        items_node = body.get("items", {})
        if items_node and "item" in items_node:
            items = items_node["item"]
            if isinstance(items, dict):
                items = [items]
                
            print(f"Retrieved {len(items)} items.")
            # Get unique keys
            unique_keys = set()
            for item in items:
                unique_keys.update(item.keys())
            print("Unique keys:", sorted(list(unique_keys)))
            
            # Print first item
            print("\nSample Item (first):")
            first_item = items[0]
            for k, v in first_item.items():
                print(f"  {k}: {repr(v)}")
        else:
            print("No items found. Response:")
            print(response.text[:300])
    except Exception as e:
        print("Exception:", e)

if __name__ == "__main__":
    for name, url in endpoints.items():
        test_api(name, url)
