import requests
from bs4 import BeautifulSoup
import json
import os
import sys
import time
import datetime

# --- 設定區塊 ---
TARGET_URL = "https://mutamarket.com/modules/type/abyssal-warp-scrambler/no-multi-item-contracts/contracts-only"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

STATE_FILE = "notified.txt"

def load_notified_contracts():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_notified_contracts(contracts):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        for c_id in contracts:
            f.write(f"{c_id}\n")

def fetch_data(request_url):
    try:
        response = requests.get(request_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"網路請求失敗 ({request_url}): {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    raw_json_string = None

    script_nodes = soup.find_all('script', type="application/json")
    for script in script_nodes:
        if script.text and '"props":' in script.text:
            raw_json_string = script.text
            break
        elif script.has_attr('data-page') and len(script['data-page']) > 10:
            raw_json_string = script['data-page']
            break

    if not raw_json_string:
        div_nodes = soup.find_all(lambda tag: tag.has_attr('data-page') and len(tag['data-page']) > 50)
        if div_nodes:
            raw_json_string = div_nodes[0]['data-page']

    if not raw_json_string:
        return None
    
    try:
        page_data = json.loads(raw_json_string.strip())
        return page_data.get('props', {})
    except json.JSONDecodeError:
        return None

def send_discord_alert(item_name, price, estimated_value, item_url):
    ratio = (price / estimated_value) * 100
    
    embed_color = 5763719 if ratio < 50 else 16753920
    
    message = {
        "embeds": [
            {
                "title": "🚨 發現低價深淵裝備",
                "url": item_url,
                "color": embed_color,
                "fields": [
                    {
                        "name": "裝備名稱",
                        "value": f"**{item_name}**",
                        "inline": False
                    },
                    {
                        "name": "合約價格",
                        "value": f"{price:,.2f} ISK",
                        "inline": True
                    },
                    {
                        "name": "估計價值",
                        "value": f"{estimated_value:,.2f} ISK",
                        "inline": True
                    },
                    {
                        "name": "折數",
                        "value": f"**{ratio:.1f}%**",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "Mutamarket 監控系統"
                },
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
        ]
    }
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=message)
    except Exception as e:
        print(f"Discord 推送失敗: {e}")

def main():
    if not DISCORD_WEBHOOK_URL:
        print("嚴重錯誤：找不到 DISCORD_WEBHOOK_URL，請檢查 GitHub Secrets 設定。")
        sys.exit(1)

    notified_contracts = load_notified_contracts()
    print(f"啟動時已讀取 {len(notified_contracts)} 筆歷史通知紀錄。")

    new_alerts_sent = False
    current_page = 1

    while True:
        current_url = TARGET_URL if current_page == 1 else f"{TARGET_URL}/page/{current_page}"
        print(f"正在檢查第 {current_page} 頁...")
        
        data = fetch_data(current_url)
        if not data:
            print("無法提取資料，結束分頁抓取。")
            break

        modules_node = data.get('modules', {})
        
        if isinstance(modules_node, dict) and 'data' in modules_node:
            item_list = modules_node['data']
        elif isinstance(modules_node, list):
            item_list = modules_node
        else:
            print("無法解析模組列表，結束抓取。")
            break

        if not item_list or len(item_list) == 0:
            print(f"第 {current_page} 頁無資料，判定已達最後一頁。")
            break

        for item in item_list:
            contract = item.get('contract') or {}
            
            contract_id_val = item.get('contract_id') or contract.get('id')
            item_id_val = item.get('id') or item.get('item_id')
            
            unique_key = str(contract_id_val) if contract_id_val else str(item_id_val)

            if not unique_key or unique_key == 'None':
                continue
                
            raw_price = item.get('price') or contract.get('price')
            raw_estimated_value = item.get('estimated_value') or item.get('est_value')
            
            item_name = item.get('type', {}).get('name') or "未知深淵裝備"
            
            if raw_price is None or raw_estimated_value is None:
                continue
                
            try:
                price = float(raw_price)
                estimated_value = float(raw_estimated_value)
            except (ValueError, TypeError):
                continue
                
            if estimated_value <= 0 or price < 80000000:
                continue
                
            if (price / estimated_value) < 0.8:
                if unique_key not in notified_contracts:
                    
                    # --- 邏輯修正：URL Slugification ---
                    if item_id_val:
                        # 將名稱轉換為小寫並替換空白鍵
                        slug = item_name.lower().replace(" ", "-")
                        item_url = f"https://mutamarket.com/modules/{slug}-{item_id_val}"
                    else:
                        item_url = TARGET_URL
                    
                    send_discord_alert(item_name, price, estimated_value, item_url)
                    notified_contracts.add(unique_key)
                    new_alerts_sent = True
                    print(f"觸發警報: {item_name} ({price / estimated_value:.1%})")

        current_page += 1
        time.sleep(2) 

    if new_alerts_sent:
        save_notified_contracts(notified_contracts)
        print("已更新狀態檔案。")
    else:
        print("本次執行沒有發現符合條件的新合約。")

if __name__ == "__main__":
    main()
