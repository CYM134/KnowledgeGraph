from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import os
import time
from urllib.parse import quote
import re
import shutil
import random

class SearchCrawler:
    def __init__(self):
        self.keyword = "二十四节气与养生"
        self.results = []
        self.zhihu_logged_in = False  # 知乎登录状态
        self.playwright = None
        self.browser = None
        self.context = None
        self.zhihu_page = None  # 复用一个页面访问知乎，避免频繁新开被识别
        self.last_zhihu_fetch = 0  # 控制知乎请求节奏
        # 二十四节气列表
        self.solar_terms = [
            '立春', '雨水', '惊蛰', '春分', '清明', '谷雨',
            '立夏', '小满', '芒种', '夏至', '小暑', '大暑',
            '立秋', '处暑', '白露', '秋分', '寒露', '霜降',
            '立冬', '小雪', '大雪', '冬至', '小寒', '大寒'
        ]

    def _resolve_user_data_dir(self):
        """确定 Chromium 使用的用户数据目录，默认放在脚本同级的 browser_data_chromium"""
        env_dir = os.environ.get('CHROMIUM_USER_DATA_DIR')
        if env_dir:
            env_dir = os.path.expanduser(env_dir)
            os.makedirs(env_dir, exist_ok=True)
            print(f"使用环境变量指定的浏览器用户数据目录: {env_dir}")
            return env_dir

        default_dir = os.path.join(os.path.dirname(__file__), 'browser_data_chromium')
        os.makedirs(default_dir, exist_ok=True)
        print(f"使用本地持久化浏览器数据目录: {default_dir}")
        return default_dir

    def _launch_chromium_context(self, user_data_dir):
        """启动 Playwright 自带 Chromium 的持久化上下文"""
        launch_kwargs = {
            'user_data_dir': user_data_dir,
            'headless': False,
            'args': [
                '--start-maximized',
                '--disable-blink-features=AutomationControlled'
            ],
            'ignore_default_args': ['--enable-automation'],
            # 模拟 Edge 143 桌面 UA，贴近可访问请求头
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0',
            'locale': 'zh-CN',
            'no_viewport': True,
        }

        try:
            return self.playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as e:
            print(f"✗ 启动 Chromium 持久化上下文失败: {e}")
            if 'edge://' in str(e).lower():
                print("  提示: 旧的浏览器数据目录可能包含 Edge 配置，建议使用全新目录。")

            clean_dir = os.path.join(os.path.dirname(__file__), 'browser_data_chromium_clean')
            if os.path.abspath(clean_dir) != os.path.abspath(user_data_dir):
                if os.path.exists(clean_dir):
                    shutil.rmtree(clean_dir, ignore_errors=True)
                os.makedirs(clean_dir, exist_ok=True)
                print(f"  将尝试使用全新数据目录: {clean_dir}")
                launch_kwargs['user_data_dir'] = clean_dir
                try:
                    ctx = self.playwright.chromium.launch_persistent_context(**launch_kwargs)
                    print("  ✓ 全新数据目录启动成功")
                    return ctx
                except Exception as e2:
                    print(f"  ✗ 全新数据目录仍然启动失败: {e2}")

            raise
    
    def _apply_stealth(self, page):
        """降低被识别为自动化的概率"""
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = window.chrome || { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
            if (originalQuery) {
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            }
            Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        """)
        page.set_extra_http_headers({
            # 贴近可访问示例请求头
            "sec-ch-ua": '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            "sec-ch-ua-platform": '"Windows"',
            "sec-ch-ua-mobile": "?0",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6"
        })
    
    def _check_zhihu_logged_in(self, page):
        """访问知乎首页，检查是否已登录"""
        try:
            self._apply_stealth(page)
            page.goto('https://www.zhihu.com', wait_until='domcontentloaded', timeout=15000)
            time.sleep(1.5)
            content_snippet = page.content()[:8000]
            if '登录' not in content_snippet and 'Sign In' not in content_snippet:
                self.zhihu_logged_in = True
                print("✓ 检测到知乎已登录")
                return True
        except Exception as e:
            print(f"⚠ 检测知乎登录状态失败: {e}")
        return False
    
    def __enter__(self):
        """上下文管理器入口"""
        self.playwright = sync_playwright().start()
        
        # 尝试加载已保存的登录状态
        storage_path = os.path.join(os.path.dirname(__file__), 'zhihu_state.json')
        storage_state = None
        if os.path.exists(storage_path):
            print(f"找到已保存的登录状态: {storage_path}")
            with open(storage_path, 'r', encoding='utf-8') as f:
                storage_state = json.load(f)
            self.zhihu_logged_in = True
        
        # 使用 Playwright 内置的 Chromium，持久化浏览器数据目录
        user_data_dir = self._resolve_user_data_dir()
        
        self.browser = self._launch_chromium_context(user_data_dir)
        
        self.context = self.browser  # 持久化上下文本身就是 context
        
        # 启动时检测知乎登录状态，不足则提示一次手动登录
        login_page = self.context.new_page()
        try:
            self._apply_stealth(login_page)
            if not self._check_zhihu_logged_in(login_page):
                self.zhihu_login_manual(login_page, force=False)
        finally:
            try:
                login_page.close()
            except:
                pass
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()
        
    def search(self, max_pages=3):
        """使用 Playwright 搜索必应并获取结果"""
        print(f"开始搜索关键词: {self.keyword}（使用Bing + Playwright）")
        
        # 为了获取不同页面，使用不同的搜索变体
        search_variations = [
            '"二十四节气" 养生',
            '二十四节气 养生知识',
            '节气 养生方法',
        ]

        page_obj = self.context.new_page()
        
        try:
            for page in range(max_pages):
                # 使用不同的搜索词变体
                query = search_variations[page % len(search_variations)]
                
                url = f"https://cn.bing.com/search?q={quote(query)}&mkt=zh-CN&setlang=zh-Hans"

                try:
                    print(f"正在访问第 {page + 1} 页（查询: {query}）...")
                    page_obj.goto(url, wait_until='networkidle', timeout=30000)
                    time.sleep(2)  # 等待页面完全加载
                    
                    html = page_obj.content()
                    print(f"成功获取第 {page + 1} 页")
                    self.parse_results(html, page + 1)
                    print(f"已完成第 {page + 1} 页，当前共 {len(self.results)} 条结果")
                    time.sleep(3)

                except Exception as e:
                    print(f"抓取第 {page + 1} 页时出错: {str(e)}")
        finally:
            page_obj.close()

        print(f"搜索完成，共获取 {len(self.results)} 条结果")
        
    def parse_results(self, html, page_num):
        """解析必应搜索结果页面"""
        soup = BeautifulSoup(html, 'html.parser')

        # 必应搜索结果有多种可能的容器类名
        results = soup.find_all('li', class_='b_algo') or soup.find_all('div', class_='b_algo')

        print(f"  第 {page_num} 页找到 {len(results)} 个搜索结果容器")

        for idx, result in enumerate(results):
            try:
                h2 = result.find('h2')
                if not h2:
                    continue

                a = h2.find('a')
                if not a:
                    continue

                title = a.get_text(strip=True)
                link = a.get('href', '')

                if not link or not link.startswith('http'):
                    continue

                print(f"  结果 {idx + 1}: 标题={title[:30]}..., 链接={link[:50]}...")

                # 相关性预过滤：仅基于标题判断（不再使用摘要/知识抽取）
                if self.is_relevant_title(title):
                    item = {
                        'title': title,
                        'link': link,
                        'source': 'Bing搜索',
                        'context': ''
                    }
                    self.results.append(item)
                    print(f"    ✓ 通过标题相关性过滤")
                else:
                    print(f"    ✗ 标题未通过相关性过滤")

            except Exception as e:
                print(f"  解析单条结果时出错: {str(e)}")
                continue
    
    def is_relevant_title(self, title):
        """基于标题的简单相关性判断：包含'养生'或'节气'或任一节气名即认为相关"""
        text = title
        if '养生' in text or '节气' in text or '二十四节气' in text:
            return True
        if any(term in text for term in self.solar_terms):
            return True
        return False
    
    def zhihu_login_manual(self, page, force=False):
        """手动登录知乎 - 暂停等待用户登录"""
        if self.zhihu_logged_in and not force:
            return True
        
        print("\n" + "="*60)
        print("  检测到知乎链接，需要登录")
        print("  正在打开知乎登录页面...")
        print("="*60)
        
        try:
            page.goto('https://www.zhihu.com/signin', wait_until='networkidle', timeout=30000)
            time.sleep(2)
            
            print("\n请在浏览器中手动登录知乎...")
            print("登录完成后，请按 Enter 键继续...")
            input()  # 等待用户按回车
            
            # 检查是否登录成功
            current_url = page.url
            page_content = page.content()
            
            if 'signin' not in current_url and ('首页' in page_content or 'notifications' in current_url or 'www.zhihu.com' in current_url):
                print("  ✓ 检测到登录成功！")
                self.zhihu_logged_in = True
                print("  ✓ 登录状态已自动保存到浏览器数据目录")
                
                return True
            else:
                print("  ⚠ 未检测到登录，将尝试继续...")
                return False
                
        except Exception as e:
            print(f"  ✗ 登录过程异常: {str(e)}")
            return False
    
    def fetch_page_content(self, url):
        """使用 Playwright 获取页面内容"""
        is_zhihu = 'zhihu.com' in url
        page = None
        
        try:
            if is_zhihu:
                print(f"  ⚠ 知乎链接，使用已保存的登录状态访问...")
                if self.zhihu_page is None:
                    self.zhihu_page = self.context.new_page()
                page = self.zhihu_page
                self._apply_stealth(page)
                if not self.zhihu_logged_in:
                    self.zhihu_login_manual(page)
                # 节流，避免短时间多次请求被风控
                gap = 6 + random.uniform(0, 4)
                since_last = time.time() - self.last_zhihu_fetch
                if since_last < gap:
                    wait_time = gap - since_last
                    print(f"  等待 {wait_time:.1f}s 再访问知乎以降低风险...")
                    time.sleep(wait_time)
                self.last_zhihu_fetch = time.time()
                # 先访问首页，再跳转目标，模拟用户浏览路径
                try:
                    page.goto('https://www.zhihu.com/', wait_until='domcontentloaded', timeout=20000)
                    jitter = random.randint(500, 1200)
                    page.wait_for_timeout(jitter)
                except Exception:
                    pass
            else:
                page = self.context.new_page()
            
            print(f"  正在访问: {url[:60]}...")
            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            if not response:
                print(f"    ✗ 无法加载页面")
                return ''
            
            status = response.status
            
            if status == 404:
                print(f"    ✗ 页面不存在（404）")
                return ''
            elif status == 403:
                print(f"    ✗ 访问被禁止（403），尝试一次重试...")
                try:
                    page.wait_for_timeout(2000 + random.randint(0, 1500))
                    response = page.goto(url, wait_until='domcontentloaded', timeout=30000, referer='https://www.zhihu.com/' if is_zhihu else None)
                    if response and response.status != 403:
                        status = response.status
                    else:
                        print("    ✗ 重试仍被禁止")
                        return ''
                except Exception:
                    return ''
            elif status == 401:
                print(f"    ✗ 需要身份验证（401）")
                return ''
            
            # 等待页面加载并模拟滚动
            page.wait_for_timeout(1000 + random.randint(0, 600))
            try:
                page.evaluate("""() => {
                    const h = document.body.scrollHeight || 2000;
                    window.scrollTo(0, h * 0.35);
                }""")
                page.wait_for_timeout(600 + random.randint(0, 400))
                page.evaluate("""() => {
                    const h = document.body.scrollHeight || 2000;
                    window.scrollTo(0, h * 0.7);
                }""")
            except Exception:
                pass
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            # 移除脚本和样式标签
            for script in soup(['script', 'style', 'nav', 'footer', 'aside', 'header']):
                script.decompose()
            
            content = ''
            
            # 知乎特殊处理
            if is_zhihu:
                selectors = [
                    ('div', 'RichContent-inner'),
                    ('div', 'Post-RichTextContainer'),
                    ('div', 'QuestionAnswer-content'),
                    ('div', 'ContentItem-main'),
                    ('div', 'List-item'),
                    ('article', None),
                ]
                
                for tag, class_name in selectors:
                    if class_name:
                        content_div = soup.find(tag, class_=class_name)
                    else:
                        content_div = soup.find(tag)
                    
                    if content_div:
                        content = content_div.get_text(separator='\n', strip=True)
                        if len(content) > 100:
                            break
                
                if not content or len(content) < 100:
                    body = soup.find('body')
                    if body:
                        content = body.get_text(separator='\n', strip=True)
            else:
                # 其他网站的通用处理
                main_content = soup.find('article') or soup.find('div', class_=re.compile('content|article|main|post', re.I))
                
                if main_content:
                    content = main_content.get_text(separator='\n', strip=True)
                else:
                    body = soup.find('body')
                    content = body.get_text(separator='\n', strip=True) if body else ''
            
            # 清理多余空白
            content = re.sub(r'\n\s*\n+', '\n', content)
            content = re.sub(r'[ \t\u3000]+', ' ', content)
            
            if len(content) < 50:
                print(f"    ⚠ 获取内容过短（{len(content)}字符），可能需要登录或被限制")
                return ''
            
            print(f"  ✓ 成功获取内容，长度: {len(content)}")
            return content[:12000]
            
        except Exception as e:
            print(f"    ✗ 获取页面内容失败: {str(e)}")
            return ''
        finally:
            if page and not is_zhihu:
                try:
                    page.close()
                except Exception:
                    pass
    
    # 知识抽取相关的函数已移除，输出仅保存页面全文到 `context`。
    
    def enrich_results(self):
        """丰富结果数据，获取页面内容和提取信息"""
        print("\n开始获取页面详细内容...")
        
        filtered = []

        for i, item in enumerate(self.results):
            print(f"\n正在处理第 {i+1}/{len(self.results)} 条: {item['title'][:40]}...")

            # 获取页面内容
            context = self.fetch_page_content(item['link'])
            item['context'] = context

            if context:
                print(f"  ✓ 成功获取页面内容，长度: {len(context)}")
            else:
                print(f"  ✗ 未能获取页面内容")

            # 将页面全文保存到 context 字段（不再做知识抽取）
            item['context'] = context
            filtered.append(item)
            print(f"  ✓ 已保存页面全文到 context 字段，长度: {len(context)}")

            time.sleep(1.5)  # 避免请求过快

        self.results = filtered
    
    def save_to_json(self):
        """保存结果到JSON文件"""
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        filename = os.path.join(data_dir, '二十四节气与养生_搜索结果.json')
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
            
        print(f"\n数据已保存至: {filename}")
        print(f"共保存 {len(self.results)} 条强相关数据")

def main():
    with SearchCrawler() as crawler:
        crawler.search(max_pages=3)  # 搜索3页结果
        
        if not crawler.results:
            print("\n警告: 未获取到任何搜索结果！")
            return
        
        # 去重
        unique_results = []
        seen_titles = set()
        for item in crawler.results:
            if item['title'] not in seen_titles:
                unique_results.append(item)
                seen_titles.add(item['title'])
        
        crawler.results = unique_results
        print(f"\n去重后剩余 {len(crawler.results)} 条结果")
        
        # 获取页面内容并提取信息
        crawler.enrich_results()
        
        crawler.save_to_json()

if __name__ == '__main__':
    main()
