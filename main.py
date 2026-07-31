import requests
from bs4 import BeautifulSoup
import json
import os
import sys
import time  # 新增：用於翻頁時的延遲保護

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

# 邏輯修改 1：函數現在接收 request_url 參數，不再寫死為 TARGET_URL
def fetch_data(request_url):
    """負責繞過防護並提取 Inertia JSON 數據"""
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
        print("錯誤：無法在 HTML 中找到 JSON 結構。")
        return None
    
    try:
        page_data = json.loads(raw_json_string.strip())
        return page_data.get('props', {})
    except json.JSONDecodeError:
        print("JSON 解析失敗。")
        return None

def send_discord_alert(item_name, price, estimated_value, item_url):
    ratio = (price / estimated_value) * 100
    message = {
        "content": f"🚨 **低價合約警報** 🚨\n"
                   f"**物品:** {item_name}\n"
                   f"**合約價:** {price:,.2f} ISK\n"
                   f"**估計價:** {estimated_value:,.2f} ISK\n"
                   f"**折數:** {ratio:.1f}%\n"
                   f"🔗 [點此前往 Mutamarket 查看]({item_url})"
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
    
    # 邏輯修改 2：分頁狀態變數初始化
    current_page = 1
    last_page = 1  # 預設至少執行一頁，後續會由 JSON 動態覆寫

    # 邏輯修改 3：啟動爬行迴圈
    while current_page <= last_page:
        # 根據頁碼組裝正確的網址
        if current_page == 1:
            current_url = TARGET_URL
        else:
            current_url = f"{TARGET_URL}/page/{current_page}"
            
        print(f"正在抓取資料: 第 {current_page} 頁 / 共 {last_page} 頁 ...")
        
        data = fetch_data(current_url)
        if not data:
            print("資料獲取失敗，中斷後續分頁抓取。")
            break

        modules_node = data.get('modules', {})
        
        # 解析該頁的合約陣列與最大頁數
        if isinstance(modules_node, dict) and 'data' in modules_node:
            item_list = modules_node['data']
            # 動態從伺服器回傳的數據更新總頁數
            last_page = modules_node.get('last_page', 1)
        elif isinstance(modules_node, list):
            item_list = modules_node
            last_page = 1 # 如果沒有分頁元數據，就只抓一頁
        else:
            print("無法解析資料結構。")
            break

        # 處理當前頁面的所有合約
        for item in item_list:
            contract_id = str(item.get('contract_id'))
            if not contract_id or contract_id == 'None':
                continue
                
            price = item.get('price')
            estimated_value = item.get('estimated_value')
            item_name = item.get('type_name') or f"Type ID: {item.get('type_id', 'Unknown')}"
            
            if not price or not estimated_value or estimated_value <= 0:
                continue
                
            if price < 80000000:
                continue
                
            if (price / estimated_value) < 0.8:
                if contract_id not in notified_contracts:
                    item_id = item.get('id') or item.get('item_id')
                    item_url = f"https://mutamarket.com/module/{item_id}" if item_id else TARGET_URL
                    
                    send_discord_alert(item_name, price, estimated_value, item_url)
                    notified_contracts.add(contract_id)
                    new_alerts_sent = True
                    print(f"已發送警報: {item_name} ({price / estimated_value:.1%})")

        # 當前頁面處理完畢，準備進入下一頁
        current_page += 1
        
        # 節流防護：如果還有下一頁，強制休眠 2 秒，避免被防火牆判定為 DDoS 攻擊
        if current_page <= last_page:
            time.sleep(2)

    if new_alerts_sent:
        save_notified_contracts(notified_contracts)
        print("已更新狀態檔案。")
    else:
        print("本次執行沒有發現符合條件的新合約。")

if __name__ == "__main__":
    main()
