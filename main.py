import requests
from bs4 import BeautifulSoup
import json
import os
import sys
import time
import datetime

# --- 設定區塊 ---
MODULE_TYPES = [
    "abyssal-warp-scrambler",
    "abyssal-stasis-webifier",
    "abyssal-warp-disruptor",
    "abyssal-magnetic-field-stabilizer",
    "abyssal-heat-sink",
    "abyssal-gyrostabilizer",
    "abyssal-entropic-radiation-sink",
    "abyssal-ballistic-control-system",
    "medium-abyssal-shield-booster",
    "large-abyssal-shield-booster",
    "x-large-abyssal-shield-booster",
    "small-abyssal-armor-repairer",
    "medium-abyssal-armor-repairer",
    "large-abyssal-armor-repairer",
    "10mn-abyssal-afterburner",
    "100mn-abyssal-afterburner",
    "50mn-abyssal-microwarpdrive",
    "small-abyssal-energy-neutralizer",
    "medium-abyssal-energy-neutralizer",
    "small-abyssal-energy-nosferatu",
    "medium-abyssal-energy-nosferatu",
    "large-abyssal-cap-battery"
]

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

STATE_FILE = "notified.txt"

# --- 核心函數區塊 ---

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
    
    price_mil = int(round(price / 1000000))
    estimated_value_mil = int(round(estimated_value / 1000000))
    
    message = {
        "embeds": [
            {
                # 邏輯修改：將標題改為物品名稱，並由下方的 url 屬性賦予超連結能力
                "title": f"🚨 {item_name}",
                "url": item_url,
                "color": embed_color,
                "fields": [
                    # 邏輯修改：移除原本顯示 Module 名稱的欄位
                    {
                        "name": "Contract Price",
                        "value": f"{price_mil:,} mil",
                        "inline": True
                    },
                    {
                        "name": "Estimated Value",
                        "value": f"{estimated_value_mil:,} mil",
                        "inline": True
                    },
                    {
                        "name": "Ratio",
                        "value": f"**{ratio:.1f}%**",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "Mutamarket Monitor"
                },
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
        ]
    }
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=message)
    except Exception as e:
        print(f"Discord 推送失敗: {e}")

def send_discord_summary(start_time, end_time, updated_count):
    time_format = "%Y-%m-%d %H:%M:%S"
    start_str = start_time.strftime(time_format)
    end_str = end_time.strftime(time_format)
    
    message = {
        "embeds": [
            {
                "title": "✅ 監控掃描完成 (System Scan Complete)",
                "color": 8026746, 
                "fields": [
                    {
                        "name": "開始時間 (UTC+8)",
                        "value": f"`{start_str}`",
                        "inline": True
                    },
                    {
                        "name": "結束時間 (UTC+8)",
                        "value": f"`{end_str}`",
                        "inline": True
                    },
                    {
                        "name": "本次新增警報數",
                        "value": f"**{updated_count}**",
                        "inline": False
                    }
                ],
                "footer": {
                    "text": "Mutamarket Monitor - Lifecycle Log"
                }
            }
        ]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=message)
    except Exception as e:
        print(f"Discord 結算推播失敗: {e}")

def main():
    if not DISCORD_WEBHOOK_URL:
        print("嚴重錯誤：找不到 DISCORD_WEBHOOK_URL，請檢查 GitHub Secrets 設定。")
        sys.exit(1)

    tz_utc_8 = datetime.timezone(datetime.timedelta(hours=8))
    run_start_time = datetime.datetime.now(tz_utc_8)

    notified_contracts = load_notified_contracts()
    print(f"啟動時已讀取 {len(notified_contracts)} 筆歷史通知紀錄。")

    new_alerts_count = 0

    for module_type in MODULE_TYPES:
        print(f"\n[系統] 開始檢查裝備種類: {module_type}")
        base_url = f"https://mutamarket.com/modules/type/{module_type}/no-multi-item-contracts/contracts-only"
        
        current_page = 1

        while True:
            current_url = base_url if current_page == 1 else f"{base_url}/page/{current_page}"
            print(f"  -> 正在獲取第 {current_page} 頁資料...")
            
            data = fetch_data(current_url)
            if not data:
                print("  -> 無法提取資料，結束此裝備種類抓取。")
                break

            modules_node = data.get('modules', {})
            
            if isinstance(modules_node, dict) and 'data' in modules_node:
                item_list = modules_node['data']
            elif isinstance(modules_node, list):
                item_list = modules_node
            else:
                print("  -> 無法解析模組列表，結束此裝備種類抓取。")
                break

            if not item_list or len(item_list) == 0:
                print(f"  -> 第 {current_page} 頁無資料，此種類檢查完畢。")
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
                
                item_name = item.get('type', {}).get('name') or "Unknown Abyssal Module"
                
                if raw_price is None or raw_estimated_value is None:
                    continue
                    
                try:
                    price = float(raw_price)
                    estimated_value = float(raw_estimated_value)
                except (ValueError, TypeError):
                    continue
                
                if estimated_value > 10000000000 or estimated_value < 150000000:
                    continue
                    
                if price < 80000000:
                    continue
                
                if (price / estimated_value) < 0.75:
                    if unique_key not in notified_contracts:
                        
                        if item_id_val:
                            slug = item_name.lower().replace(" ", "-")
                            item_url = f"https://mutamarket.com/modules/{slug}-{item_id_val}"
                        else:
                            item_url = base_url
                        
                        send_discord_alert(item_name, price, estimated_value, item_url)
                        notified_contracts.add(unique_key)
                        new_alerts_count += 1
                        print(f"  *** 觸發警報: {item_name} ({price / estimated_value:.1%}) ***")

            current_page += 1
            time.sleep(2) 
            
        time.sleep(1)

    print("\n[系統] 所有裝備種類檢查完畢。")
    
    run_end_time = datetime.datetime.now(tz_utc_8)
    send_discord_summary(run_start_time, run_end_time, new_alerts_count)

    if new_alerts_count > 0:
        save_notified_contracts(notified_contracts)
        print("已更新狀態檔案。")
    else:
        print("本次執行沒有發現符合條件的新合約。")

if __name__ == "__main__":
    main()
