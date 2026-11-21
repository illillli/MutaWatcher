import requests
import re
from bs4 import BeautifulSoup
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

def load_notified_contracts():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_notified_contracts(contracts):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        for c_id in contracts:
            f.write(f"{c_id}\n")

# 邏輯重構：單純負責下載網頁純文字，不再處理 JSON 解析
def fetch_raw_html(request_url):
    try:
        response = requests.get(request_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        
        # 保留 Cloudflare 防火牆探針，以防萬一
        soup = BeautifulSoup(response.text, 'html.parser')
        page_title = soup.title.string.strip() if soup.title else ""
        if "Just a moment" in page_title or "Cloudflare" in response.text:
            print("  -> [致命錯誤] IP 被 Cloudflare 攔截。")
            return None
            
        return response.text
    except Exception as e:
        print(f"  -> 網路請求失敗: {e}")
        return None

# 全新模組：正則表達式萃取器 (Regex Extractor)
def parse_items_from_html(raw_html):
    items = []
    # 利用 Regex 捕捉物品 ID (Group 1) 與物品名稱 (Group 2) 作為每個裝備區塊的開頭
    pattern = r'\{id:\s*(\d+),\s*type:\s*\{id:\s*(\d+),\s*name:\s*"([^"]+)"\}'
    matches = list(re.finditer(pattern, raw_html))
    
    for i in range(len(matches)):
        # 將網頁字串切片，鎖定當前物品的資料範圍
        start = matches[i].start()
        end = matches[i+1].start() if i + 1 < len(matches) else len(raw_html)
        chunk = raw_html[start:end]
        
        item_id = matches[i].group(1)
        type_id = matches[i].group(2)
        item_name = matches[i].group(3)
        
        # 提取估算價值 (容錯處理，找不到就跳過此裝備)
        est_match = re.search(r'\bestimated_value:\s*([\d\.]+)', chunk)
        if not est_match:
            continue
        estimated_value = float(est_match.group(1))
        
        # 提取合約價格 (同時相容 price: 或 contract_price:)
        price_match = re.search(r'\b(?:contract_)?price:\s*([\d\.]+)', chunk)
        if not price_match:
            continue
        price = float(price_match.group(1))
        
        # 提取合約 ID 作為去重依據，找不到則退回使用物品 ID
        contract_id = item_id
        c_id_match = re.search(r'\bcontract_id:\s*(\d+)', chunk)
        if c_id_match:
            contract_id = c_id_match.group(1)
        else:
            c_match = re.search(r'\bcontract:\s*\{[^\}]*?id:\s*(\d+)', chunk)
            if c_match:
                contract_id = c_match.group(1)

        # 合約類型：item_exchange（一口價）或 auction（拍賣）
        type_match = re.search(r'\bcontract:\s*\{id:\s*\d+,\s*type:\s*"(\w+)"', chunk)
        contract_type = type_match.group(1) if type_match else ""

        items.append({
            'item_id': item_id,
            'item_name': item_name,
            'type_id': type_id,
            'price': price,
            'estimated_value': estimated_value,
            'contract_id': contract_id,
            'contract_type': contract_type,
        })
    return items

def fmt_isk(value):
    """把 ISK 寫成 1.23 B / 456 M 這種好讀的格式。"""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} B"
    return f"{value / 1_000_000:,.0f} M"


def deal_tier(ratio):
    """依 價格/估值 比例決定等級圖示、顏色。"""
    if ratio < 50:
        return "🔥", 0x00E676
    if ratio < 60:
        return "✨", 0x2ECC71
    return "👍", 0xF1C40F


def price_bar(ratio, blocks=10):
    """🟩 是你要付的、⬜ 是省下來的。"""
    filled = max(1, min(blocks, round(ratio / 100 * blocks)))
    return "🟩" * filled + "⬜" * (blocks - filled)


def build_alert_embed(item, item_url, module_type, preview=False):
    price = item['price']
    estimated_value = item['estimated_value']
    ratio = price / estimated_value * 100
    saved = estimated_value - price
    tier, color = deal_tier(ratio)
    category = module_type.replace("-", " ").title()

    description = "\n".join([
        f"{tier} Listed at **{ratio:.1f}%** of its estimated value",
        price_bar(ratio),
        "-# 🟩 Price　⬜ Savings　(vs. estimated value)",
    ])
    embed = {
        "author": {"name": f"Mutamarket · {category}", "url": f"https://mutamarket.com/modules/type/{module_type}"},
        "title": item['item_name'],
        "url": item_url,
        "description": description,
        "color": color,
        "fields": [
            {"name": "💵 Price", "value": f"**{fmt_isk(price)}** ISK", "inline": True},
            {"name": "📈 Estimated", "value": f"{fmt_isk(estimated_value)} ISK", "inline": True},
            {"name": "🪙 Savings", "value": f"**{fmt_isk(saved)}** ISK", "inline": True},
        ],
        "footer": {"text": "Mutamarket Monitor" + (" · Preview (not a new contract)" if preview else "")},
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if item.get('type_id'):
        embed["thumbnail"] = {"url": f"https://images.evetech.net/types/{item['type_id']}/icon?size=64"}
    return embed


def send_discord_alert(item, item_url, module_type, preview=False):
    message = {"embeds": [build_alert_embed(item, item_url, module_type, preview)]}
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=15)
        if r.status_code == 429:  # 被限速就等一下再送
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            r = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"Discord 推送失敗: {e}")


def item_url_for(item, base_url):
    if item['item_id']:
        slug = item['item_name'].lower().replace(" ", "-")
        return f"https://mutamarket.com/modules/{slug}-{item['item_id']}"
    return base_url


def passes_value_filter(item):
    # 拍賣的價格只是起標價，不準，直接跳過
    if item.get('contract_type') == 'auction':
        return False
    return 150_000_000 <= item['estimated_value'] <= 10_000_000_000 and item['price'] >= 80_000_000


def send_preview():
    """PREVIEW=1 時：挑第一種裝備第一頁裡最便宜的一筆發出去，看看樣式（不記錄、不影響正常通知）。"""
    module_type = MODULE_TYPES[0]
    base_url = f"https://mutamarket.com/modules/type/{module_type}/no-multi-item-contracts/contracts-only"
    raw_html = fetch_raw_html(base_url)
    items = [i for i in parse_items_from_html(raw_html or "") if passes_value_filter(i)]
    if not items:
        print("預覽：找不到可用的合約。")
        return
    best = min(items, key=lambda i: i['price'] / i['estimated_value'])
    send_discord_alert(best, item_url_for(best, base_url), module_type, preview=True)
    print(f"預覽已發送：{best['item_name']}")


def main():
    if not DISCORD_WEBHOOK_URL:
        print("嚴重錯誤：找不到 DISCORD_WEBHOOK_URL，請檢查 GitHub Secrets 設定。")
        sys.exit(1)

    if os.environ.get("PREVIEW") == "1":
        send_preview()
        return

    notified_contracts = load_notified_contracts()
    print(f"啟動時已讀取 {len(notified_contracts)} 筆歷史通知紀錄。")

    new_alerts_count = 0

    for module_type in MODULE_TYPES:
        print(f"\n[系統] 開始檢查裝備種類: {module_type}")
        base_url = f"https://mutamarket.com/modules/type/{module_type}/no-multi-item-contracts/contracts-only"
        
        current_page = 1
        MAX_PAGES = 3

        while True:
            current_url = base_url if current_page == 1 else f"{base_url}/page/{current_page}"
            print(f"  -> 正在獲取第 {current_page} 頁資料...")
            
            raw_html = fetch_raw_html(current_url)
            if not raw_html:
                break

            # 呼叫 Regex 模組進行萃取
            item_list = parse_items_from_html(raw_html)

            # 如果 Regex 沒有找到任何裝備，代表這頁是空的，可以直接換下一個裝備
            if not item_list or len(item_list) == 0:
                print(f"  -> 第 {current_page} 頁無資料，此種類檢查完畢。")
                break

            for item in item_list:
                unique_key = item['contract_id']
                price = item['price']
                estimated_value = item['estimated_value']
                item_name = item['item_name']

                if not passes_value_filter(item):
                    continue

                if (price / estimated_value) < 0.7:
                    if unique_key not in notified_contracts:
                        send_discord_alert(item, item_url_for(item, base_url), module_type)
                        notified_contracts.add(unique_key)
                        new_alerts_count += 1
                        print(f"  *** 觸發警報: {item_name} ({price / estimated_value:.1%}) ***")

            if current_page >= MAX_PAGES:
                print(f"  -> 已達到最大掃描深度 ({MAX_PAGES} 頁)，切換下一種裝備。")
                break

            current_page += 1
            time.sleep(2) 
            
        time.sleep(1)

    print("\n[系統] 所有裝備種類檢查完畢。")

    if new_alerts_count > 0:
        save_notified_contracts(notified_contracts)
        print("已更新狀態檔案。")
    else:
        print("本次執行沒有發現符合條件的新合約。")

if __name__ == "__main__":
    main()
