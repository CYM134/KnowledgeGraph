import time
import random
import json
import os
from playwright.sync_api import sync_playwright

# === 配置区域 ===
KEYWORD = "24节气 养生"
SAVE_FILENAME = "24_solar_terms_wellness_full.json"
TARGET_COUNT = 20  # 目标抓取条数（抓够这么多条后停止）
MAX_PAGES = 5      # 最大翻页数（兜底防止死循环）

def random_sleep(min_time=1.5, max_time=4.0):
    """随机等待，模拟人类阅读和思考时间"""
    time.sleep(random.uniform(min_time, max_time))

def text_cleaner(page_content):
    """
    JS注入清洗：移除广告、导航、脚本，提取纯净正文
    """
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
    
    # Python 端二次清洗：去除连续空行
    lines = [line.strip() for line in clean_text.split('\n') if line.strip()]
    return "\n".join(lines)

def run_spider():
    results = []
    visited_urls = set() # 用于去重
    
    # 启动参数：隐藏自动化特征
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars",
    ]

    with sync_playwright() as p:
        # 启动浏览器 (headless=False 方便观察，稳定后可改为 True)
        browser = p.chromium.launch(
            headless=False,  
            args=launch_args
        )
        
        # 创建上下文
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN"
        )

        # 注入反爬绕过脚本 (Stealth)
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        # 搜索页（主控页）
        page_search = context.new_page()
        
        print(f"🚀 开始访问 Bing 搜索: {KEYWORD}")
        page_search.goto("https://www.bing.com", wait_until="networkidle")
        
        # 输入并搜索
        search_box = "#sb_form_q"
        page_search.wait_for_selector(search_box)
        random_sleep(1, 2)
        page_search.type(search_box, KEYWORD, delay=random.randint(100, 250))
        page_search.keyboard.press("Enter")
        
        page_current_idx = 1
        
        # === 主循环：翻页抓取 ===
        while len(results) < TARGET_COUNT and page_current_idx <= MAX_PAGES:
            print(f"\n--- 正在处理第 {page_current_idx} 页搜索结果 (当前已采集: {len(results)}/{TARGET_COUNT}) ---")
            
            # 等待搜索结果加载
            try:
                page_search.wait_for_selector(".b_algo", timeout=10000)
            except:
                print("未检测到搜索结果，可能已到尽头或被拦截。")
                break

            # 模拟滚动，触发懒加载
            page_search.evaluate("window.scrollBy(0, document.body.scrollHeight / 2)")
            random_sleep(1, 2)

            # 获取当前页所有链接元素
            # 注意：这里只获取 Locator，不直接取值，防止元素失效
            link_locators = page_search.locator(".b_algo h2 a").all()
            
            print(f"🔍 本页发现 {len(link_locators)} 个结果，开始筛选...")

            # 遍历当前页的链接
            for link_loc in link_locators:
                if len(results) >= TARGET_COUNT:
                    break

                url = link_loc.get_attribute("href")
                title = link_loc.inner_text()

                # 过滤无效链接或已抓取链接
                if not url or not url.startswith("http") or url in visited_urls:
                    continue
                
                visited_urls.add(url)
                
                # === 打开新标签页抓取详情 (不干扰搜索页) ===
                print(f"   [抓取中] {title[:30]}...")
                page_detail = context.new_page()
                
                try:
                    page_detail.goto(url, timeout=25000, wait_until="domcontentloaded")
                    
                    # 模拟阅读滚动
                    page_detail.evaluate("window.scrollBy(0, 500)")
                    random_sleep(0.5, 1.5)
                    
                    content = text_cleaner(page_detail)
                    
                    if len(content) > 100: # 只要大于100字才保存
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
                    page_detail.close() # 关掉详情页
                    random_sleep(1.5, 3.0) # 篇与篇之间的间隔

            # === 翻页逻辑 ===
            if len(results) >= TARGET_COUNT:
                print("🎉 已达到目标抓取数量，停止任务。")
                break
            
            # 寻找下一页按钮
            # Bing 的下一页按钮通常是 class="sb_pagN"
            next_btn = page_search.locator("a.sb_pagN")
            
            if next_btn.is_visible():
                print("👉 正在翻至下一页...")
                # 随机移动鼠标到按钮位置再点击（反爬）
                box = next_btn.bounding_box()
                if box:
                    page_search.mouse.move(
                        box["x"] + box["width"] / 2 + random.randint(-5, 5),
                        box["y"] + box["height"] / 2 + random.randint(-5, 5)
                    )
                next_btn.click()
                random_sleep(3, 5) # 翻页后多等一会
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