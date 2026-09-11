import requests
import sys

def main():
    url = "https://mutamarket.com/modules/type/abyssal-warp-scrambler/no-multi-item-contracts/contracts-only"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    print(f"[系統] 啟動底層診斷探針，目標網址: {url}")
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"請求失敗: {e}")
        sys.exit(1)

    raw_html = response.text
    print("[系統] 網頁原始碼下載成功，開始進行特徵碼比對...")

    # 我們要尋找的 EVE 裝備市場特徵值
    keywords = ["estimated_value", "contract_id", "price"]
    found = False

    for kw in keywords:
        idx = raw_html.find(kw)
        if idx != -1:
            print(f"\n[分析成功] 在 HTML 中尋獲特徵碼 '{kw}'")
            print("================ 原始碼片段開始 ================")
            # 印出特徵碼前後的字元，讓我們看清楚新的資料結構長怎樣
            print(raw_html[max(0, idx - 300) : idx + 1000])
            print("================ 原始碼片段結束 ================")
            found = True
            break

    if not found:
        print("\n[分析失敗] HTML 原始碼中完全找不到任何合約特徵碼。")
        print("推論：網站架構已改為 CSR (Client-Side Rendering)，資料由獨立 API 端點非同步獲取。我們需要切換至 API 攔截模式。")

if __name__ == "__main__":
    main()
