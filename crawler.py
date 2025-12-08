from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import os
import time
from urllib.parse import quote
import re

class SearchCrawler:
    def __init__(self):
        self.keyword = "二十四节气与养生"
        self.results = []
        self.zhihu_logged_in = False  # 知乎登录状态
        self.playwright = None
        self.browser = None
        self.context = None
        # 二十四节气列表
        self.solar_terms = [
            '立春', '雨水', '惊蛰', '春分', '清明', '谷雨',
            '立夏', '小满', '芒种', '夏至', '小暑', '大暑',
            '立秋', '处暑', '白露', '秋分', '寒露', '霜降',
            '立冬', '小雪', '大雪', '冬至', '小寒', '大寒'
        ]
    
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
        
        # 使用本地 Edge 浏览器，指定用户数据目录以保持登录状态
        user_data_dir = os.path.join(os.path.dirname(__file__), 'browser_data')
        os.makedirs(user_data_dir, exist_ok=True)
        
        self.browser = self.playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,  # 使用持久化的用户数据目录
            headless=False,
            channel="msedge",  # 使用 Edge 浏览器
            args=['--start-maximized'],
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='zh-CN',
            no_viewport=True  # 使用窗口的实际大小
        )
        
        self.context = self.browser  # 持久化上下文本身就是 context
        
        # 检查是否已有知乎登录状态
        if len(self.context.pages) > 0:
            test_page = self.context.pages[0]
        else:
            test_page = self.context.new_page()
        
        try:
            test_page.goto('https://www.zhihu.com', timeout=10000)
            time.sleep(1)
            if '登录' not in test_page.content()[:5000]:
                self.zhihu_logged_in = True
                print("✓ 检测到已有知乎登录状态")
            test_page.close()
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
    
    def zhihu_login_manual(self, page):
        """手动登录知乎 - 暂停等待用户登录"""
        if self.zhihu_logged_in:
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
        page = self.context.new_page()
        
        try:
            is_zhihu = 'zhihu.com' in url
            
            if is_zhihu:
                print(f"  ⚠ 知乎链接，使用已保存的登录状态访问...")
                if not self.zhihu_logged_in:
                    self.zhihu_login_manual(page)
            
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
                print(f"    ✗ 访问被禁止（403）")
                return ''
            elif status == 401:
                print(f"    ✗ 需要身份验证（401）")
                return ''
            
            # 等待页面加载
            time.sleep(2)
            
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
                print(f"    ⚠ 获取内容过短（{len(content)}字符），可能需要登录")
                return ''
            
            print(f"  ✓ 成功获取内容，长度: {len(content)}")
            return content[:12000]
            
        except Exception as e:
            print(f"    ✗ 获取页面内容失败: {str(e)}")
            return ''
        finally:
            page.close()
    
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
