import urllib.request
import json
import os

url = "https://raw.githubusercontent.com/WooilJeong/code/main/code/code_dong/code_bdong.json"
output_file = "code_bdong.json"

print(f"Downloading {url}...")
try:
    with urllib.request.urlopen(url) as response:
        content = response.read().decode('utf-8')
        print("Cleaning up 'nan' float strings...")
        content_cleaned = content.replace("nan", "null")
        
        # Validate JSON structure
        print("Validating JSON structure...")
        data = json.loads(content_cleaned)
        print(f"Validation successful! Total items: {len(data.get('data', {}).get('법정동코드', {}))}")
        
        # Save locally
        print(f"Saving to {output_file}...")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print("Done!")
except Exception as e:
    print("Error downloading database:", e)
