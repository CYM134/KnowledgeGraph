import time
import random
import json
import os
from playwright.sync_api import sync_playwright

KEYWORD = "24节气 养生"
SAVE_FILENAME = "24_solar_terms_wellness_full.json"
TARGET_COUNT = 20
MAX_PAGES = 5

def random_sleep(min_time=1.5, max_time=4.0):
    time.sleep(random.uniform(min_time, max_time))

def text_cleaner(page_content):
    clean_text = page_content.evaluate("""() => {
        // 1. 移除干扰标签
        const uselessTags = ['script', 'style', 'noscript', 'iframe', 'header', 'footer', 'nav', 'aside', 'svg', '.ads', '.advertisement'];
        uselessTags.forEach(selector => {
            document.querySelectorAll(selector).forEach(el => el.remove());
        });
        
        // 2. 智能提取正文容器
        // 优先查找常见的文章标签，如果找不到则回退到 body
        const potentialContent = document.querySelector('article') || 
                                 document.querySelector('.article-content') || 
                                 document.querySelector('.post-body') || 
                                 document.querySelector('.main-content') ||
                                 document.querySelector('#content') ||
                                 document.body;
        
        if (!potentialContent) return "";

        // 3. 获取文本并简单清洗
        return potentialContent.innerText;
    }""")
    
    lines = [line.strip() for line in clean_text.split('\n') if line.strip()]
    return "\n".join(lines)

def run_spider():
    results = []
    visited_urls = set()
    
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars",
    ]
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  
            args=launch_args
        )    
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN"
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page_search = context.new_page()
        
        print(f"🚀 开始访问 Bing 搜索: {KEYWORD}")
        page_search.goto("https://www.bing.com", wait_until="networkidle")
        
        search_box = "#sb_form_q"
        page_search.wait_for_selector(search_box)
        random_sleep(1, 2)
        page_search.type(search_box, KEYWORD, delay=random.randint(100, 250))
        page_search.keyboard.press("Enter")
        
        page_current_idx = 1
        
        while len(results) < TARGET_COUNT and page_current_idx <= MAX_PAGES:
            print(f"\n--- 正在处理第 {page_current_idx} 页搜索结果 (当前已采集: {len(results)}/{TARGET_COUNT}) ---")
            
            try:
                page_search.wait_for_selector(".b_algo", timeout=10000)
            except:
                print("未检测到搜索结果，可能已到尽头或被拦截。")
                break

            page_search.evaluate("window.scrollBy(0, document.body.scrollHeight / 2)")
            random_sleep(1, 2)

            link_locators = page_search.locator(".b_algo h2 a").all()
            
            print(f"🔍 本页发现 {len(link_locators)} 个结果，开始筛选...")

            for link_loc in link_locators:
                if len(results) >= TARGET_COUNT:
                    break

                url = link_loc.get_attribute("href")
                title = link_loc.inner_text()

                if not url or not url.startswith("http") or url in visited_urls:
                    continue
                
                visited_urls.add(url)
                
                print(f"   [抓取中] {title[:30]}...")
                page_detail = context.new_page()
                
                try:
                    page_detail.goto(url, timeout=25000, wait_until="domcontentloaded")
                    
                    page_detail.evaluate("window.scrollBy(0, 500)")
                    random_sleep(0.5, 1.5)
                    
                    content = text_cleaner(page_detail)
                    
                    if len(content) > 100:
                        results.append({
                            "title": title,
                            "url": url,
                            "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "content": content
                        })
                        print(f"   ✅ 成功 (字数: {len(content)})")
                    else:
                        print("   ⚠️ 内容过短，跳过")

                except Exception as e:
                    print(f"   ❌ 失败: {str(e)[:50]}")
                finally:
                    page_detail.close()
                    random_sleep(1.5, 3.0)

            if len(results) >= TARGET_COUNT:
                print("🎉 已达到目标抓取数量，停止任务。")
                break
            
            next_btn = page_search.locator("a.sb_pagN")
            
            if next_btn.is_visible():
                print("👉 正在翻至下一页...")
                box = next_btn.bounding_box()
                if box:
                    page_search.mouse.move(
                        box["x"] + box["width"] / 2 + random.randint(-5, 5),
                        box["y"] + box["height"] / 2 + random.randint(-5, 5)
                    )
                next_btn.click()
                random_sleep(3, 5)
                page_current_idx += 1
            else:
                print("🏁 未找到下一页按钮，任务结束。")
                break

        browser.close()
        return results

def save_to_file(data):
    if not data:
        print("无数据保存。")
        return
    
    with open(SAVE_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"\n💾 数据已保存至: {os.path.abspath(SAVE_FILENAME)} (共 {len(data)} 条)")

if __name__ == "__main__":
    data = run_spider()
    save_to_file(data)
