"""
PDF文档段落提取脚本
功能：从knowledge文件夹中的PDF文件提取正文段落，保存为JSON格式
输出：knowledge.json，包含id、title、context三个字段
"""

import os
import json
import re
from pathlib import Path
from typing import List

try:
    import pdfplumber
except ImportError:
    print("未安装pdfplumber库，正在安装...")
    os.system("pip install pdfplumber")
    import pdfplumber


class PDFExtractor:
    def __init__(self, pdf_folder: str = "knowledge", output_file: str = "knowledge.json"):
        self.pdf_folder = pdf_folder
        self.output_file = output_file
        self.data: List[dict] = []
        self.paragraph_id = 1

        # 过滤关键词
        self.skip_keywords = [
            "作者", "通讯作者", "关键词", "文章编号", "中图分类号",
            "文献标识码", "文献标志码", "收稿日期", "修回日期", "出版日期",
            "基金项目", "引用格式", "第一作者", "通信作者", "版权", "出版社"
        ]

        # 标记性关键词
        self.abstract_markers = ["摘要", "abstract", "【摘要】"]
        self.keyword_markers = ["关键词", "key words", "【关键词】"]
        self.reference_markers = ["参考文献", "references", "[参考文献]"]

        # 相关性关键字
        self.relevant_keywords = [
            "二十四节气", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
            "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑",
            "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
            "小寒", "大寒", "节气", "养生"
        ]
        
        # 放松检索关键词（用于特殊文件）
        self.relaxed_keywords = ["宜吃", "调配", "保健", "少吃", "不能吃"]
        
        # 24节气列表（用于匹配season）
        self.solar_terms = [
            "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
            "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
            "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
            "立冬", "小雪", "大雪", "冬至", "小寒", "大寒"
        ]

    def clean_text(self, text: str, preserve_punctuation: bool = True, preserve_raw: bool = False) -> str:
        """清理文本：删除引用、数字、英文、括号等"""
        if not text:
            return ""
        
        # 删除中括号引用（始终删除引用编号）
        text = re.sub(r"[\[［【〔]\s*\d+[^\]］】〕]*[\]］】〕]", "", text)
        # 删除控制字符
        text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", text)
        # 删除波浪号
        text = text.replace("~", "")
        # 删除空的双引号对（连续的成对引号）
        text = re.sub(r'""', '', text)
        text = re.sub(r"''", '', text)
        # 删除只包含空格的引号
        text = re.sub(r'"\s+"', '', text)
        text = re.sub(r"'\s+'", '', text)

        if not preserve_raw:
            # 删除英文字母（含全角）
            text = re.sub(r"[A-Za-zＡ-Ｚａ-ｚ]+", "", text)
            # 删除数字（含全角）
            text = re.sub(r"[0-9０-９]+", "", text)
            # 删除各种括号
            text = re.sub(r"[\[\]\(\)（）【】［］〈〉<>{}]", "", text)

        if preserve_punctuation:
            # 保留句号和逗号，只删除多余空白
            text = re.sub(r"[ \t]+", " ", text)
        else:
            # 规范化空格（删除所有空白）
            text = re.sub(r"\s+", "", text)
        
        return text.strip()

    def should_skip_line(self, text: str, preserve_raw: bool = False) -> bool:
        """判断是否应该跳过此行"""
        if not text or len(text) < 5:
            return True

        text_lower = text.lower()
        
        # 检查过滤关键词
        for keyword in self.skip_keywords:
            if keyword in text or keyword.lower() in text_lower:
                return True
        
        # 过滤页码
        if re.fullmatch(r"[·\s]*\d+[·\s]*", text):
            return True
        
        # 过滤期刊信息
        if re.search(r"第\s*\d+\s*卷|第\s*\d+\s*期", text):
            return True
        
        # 过滤日期
        if re.search(r"\d{4}\s*年\s*\d{1,2}\s*月", text):
            return True
        
        # 过滤DOI
        if re.search(r"doi", text_lower):
            return True
        
        # 必须包含中文（除非 preserve_raw 为 True）
        if not preserve_raw and not re.search(r"[\u4e00-\u9fff]", text):
            return True
        
        return False

    def is_valid_paragraph(self, text: str) -> bool:
        """判断是否是有效段落"""
        if not text or len(text) < 30:
            return False
        
        # 必须包含足够的中文字符
        chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        if chinese_count < 20:
            return False
        
        return True

    def is_relevant(self, text: str) -> bool:
        """判断段落是否与节气养生相关"""
        # 基础关键词检查
        if any(keyword in text for keyword in self.relevant_keywords):
            return True
        
        # 放松检索：如果包含特定饮食保健关键词也保留
        if any(keyword in text for keyword in self.relaxed_keywords):
            return True
        
        return False

    def normalize_title(self, filename: str) -> str:
        """提取文件标题"""
        base = filename.replace(".pdf", "")
        return base.split("_")[0]

    def detect_columns(self, chars: List[dict], page_width: float) -> List[float]:
        """检测列分割线位置"""
        if not chars:
            return []
        
        # 统计字符的x0位置分布
        x_positions = [char['x0'] for char in chars]
        x_positions.sort()
        
        # 寻找较大的间隙作为列分割线
        gaps = []
        for i in range(len(x_positions) - 1):
            gap = x_positions[i + 1] - x_positions[i]
            if gap > page_width * 0.05:  # 间隙超过页面宽度5%
                gaps.append((x_positions[i] + gap / 2, gap))
        
        # 按间隙大小排序，取最大的1-2个作为列分割线
        gaps.sort(key=lambda x: x[1], reverse=True)
        column_dividers = [g[0] for g in gaps[:2]]
        column_dividers.sort()
        
        return column_dividers

    def assign_column(self, x0: float, dividers: List[float]) -> int:
        """根据x0坐标分配列号"""
        for idx, divider in enumerate(dividers):
            if x0 < divider:
                return idx
        return len(dividers)

    def extract_full_text(self, pdf_path: Path) -> str:
        """提取PDF全文，按列顺序排序"""
        full_text = []
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    # 提取所有字符及其坐标
                    chars = page.chars
                    if not chars:
                        continue
                    
                    # 检测列分割线
                    column_dividers = self.detect_columns(chars, page.width)
                    
                    # 为每个字符分配列号
                    for char in chars:
                        char['page'] = page_num
                        char['column'] = self.assign_column(char['x0'], column_dividers)
                    
                    # 先按列和top分组，然后在每组内按x0排序
                    from collections import defaultdict
                    lines_dict = defaultdict(list)
                    
                    for char in chars:
                        # 使用列号和取整的top作为行键（容差5像素）
                        line_key = (char['column'], round(char['top'] / 5) * 5)
                        lines_dict[line_key].append(char)
                    
                    # 对每行内的字符按x0排序
                    sorted_lines = []
                    for line_key in sorted(lines_dict.keys()):
                        line_chars = sorted(lines_dict[line_key], key=lambda c: c['x0'])
                        line_text = ''.join([c['text'] for c in line_chars])
                        sorted_lines.append(line_text)
                    
                    full_text.append('\n'.join(sorted_lines))
                    
        except Exception as e:
            print(f"  提取文本失败: {e}")
            return ""
        
        return "\n".join(full_text)

    def process_text(self, text: str, preserve_raw: bool = False) -> str:
        """处理全文：删除无用部分"""
        lines = text.split("\n")
        processed_lines = []
        
        in_abstract = False
        in_keywords = False
        in_references = False
        
        for line in lines:
            line = line.strip()
            
            if not line:
                if in_abstract or in_keywords:
                    in_abstract = False
                    in_keywords = False
                continue
            
            line_lower = line.lower()
            
            # 检测参考文献标记
            if any(marker in line or marker in line_lower for marker in self.reference_markers):
                in_references = True
                continue
            
            if in_references:
                continue
            
            # 检测摘要标记
            if any(marker in line or marker in line_lower for marker in self.abstract_markers):
                in_abstract = True
                continue
            
            # 检测关键词标记
            if any(marker in line or marker in line_lower for marker in self.keyword_markers):
                in_keywords = True
                continue
            
            if in_abstract or in_keywords:
                continue
            
            # 跳过无用行
            if self.should_skip_line(line, preserve_raw=preserve_raw):
                continue
            
            # 对特殊文件不清除英数字符和括号，先保留原行
            processed_lines.append(line)
        
        return "\n".join(processed_lines)

    def split_paragraphs(self, text: str, preserve_raw: bool = False) -> List[str]:
        """分割段落"""
        # 先按双换行符分割
        blocks = text.split("\n\n")
        
        paragraphs = []
        current_para = ""
        
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            
            # 清理并拼接
            cleaned = self.clean_text(block, preserve_punctuation=True, preserve_raw=preserve_raw)
            if not cleaned:
                continue
            
            # 检查是否应该合并到上一段
            if current_para and len(cleaned) < 100:
                current_para += cleaned
            elif current_para and not current_para[-1] in "。！？；：":
                current_para += cleaned
            else:
                if current_para and self.is_valid_paragraph(current_para) and self.is_relevant(current_para):
                    paragraphs.append(current_para)
                current_para = cleaned
        
        # 处理最后一段
        if current_para and self.is_valid_paragraph(current_para) and self.is_relevant(current_para):
            paragraphs.append(current_para)
        
        # 如果段落太少，尝试按单换行符分割
        if len(paragraphs) < 3:
            return self.split_by_sentences(text, preserve_raw=preserve_raw)
        
        return paragraphs

    def split_by_sentences(self, text: str, preserve_raw: bool = False) -> List[str]:
        """按句子分割（兜底方案）"""
        cleaned = self.clean_text(text, preserve_punctuation=True, preserve_raw=preserve_raw)
        
        # 按句号等分割
        sentences = re.split(r"[。！？]", cleaned)
        
        paragraphs = []
        current = ""
        
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            
            current += sent
            
            if len(current) >= 80:
                if self.is_valid_paragraph(current) and self.is_relevant(current):
                    paragraphs.append(current)
                current = ""
        
        if current and self.is_valid_paragraph(current) and self.is_relevant(current):
            paragraphs.append(current)
        
        return paragraphs

    def detect_season(self, paragraph: str, full_text: str) -> str:
        """检测段落所属的节气"""
        # 首先检查段落本身是否包含节气名称
        for term in self.solar_terms:
            if term in paragraph:
                return term
        
        # 如果段落中没有，尝试从上下文中查找章节标题
        # 查找段落在全文中的位置
        para_pos = full_text.find(paragraph[:50])  # 用前50个字符定位
        
        if para_pos > 0:
            # 向前查找最近的章节标题（包含节气名称）
            context_before = full_text[max(0, para_pos - 500):para_pos]
            
            # 按行分割，从后往前找包含节气的标题
            lines = context_before.split('\n')
            for line in reversed(lines):
                for term in self.solar_terms:
                    # 匹配类似 "01 立春 LICHUN" 或 "立春" 的标题
                    if term in line and len(line) < 100:  # 标题通常较短
                        return term
        
        return "未知"
    
    def extract_from_pdf(self, pdf_path: Path) -> List[dict]:
        """从PDF提取段落"""
        paragraphs = []
        
        try:
            # 提取全文
            full_text = self.extract_full_text(pdf_path)
            if not full_text:
                return paragraphs
            
            # 检测是否为特殊文件（需保留英文/数字/括号）
            special_file_keywords = ["二十四节气养生经", "24节气养生法", "Z-Library"]
            is_special_file = any(k in pdf_path.name for k in special_file_keywords)

            # 处理文本
            processed_text = self.process_text(full_text, preserve_raw=is_special_file)
            
            # 分割段落
            title = self.normalize_title(pdf_path.name)
            paragraph_texts = self.split_paragraphs(processed_text, preserve_raw=is_special_file)
            
            if len(paragraph_texts) < 5:
                print(f"  警告: {pdf_path.name} 仅提取 {len(paragraph_texts)} 个相关段落")
            
            # 为每个段落分配season - 使用简单的状态机
            current_season = "未知"
            
            for para_text in paragraph_texts:
                # 检查段落开头是否是节气标题
                if is_special_file:
                    # 先检查段落开头 (格式: 数字+空格+中文节气名+空格+英文大写)
                    heading_match = re.match(r'^\s*\d{1,2}[\s\u3000]+([\u4e00-\u9fff]{2,3})[\s\u3000]+[A-Z]+', para_text.strip())
                    if heading_match and heading_match.group(1) in self.solar_terms:
                        # 更新当前节气
                        current_season = heading_match.group(1)
                        print(f"  检测到标题(开头): {heading_match.group(0).strip()} -> {current_season}")
                        # 跳过标题行，不作为段落输出
                        continue
                    
                    # 检查段落中间或末尾是否包含节气标题
                    # 使用 findall 找到所有匹配 (格式: 数字+空格+中文节气名+空格+英文大写)
                    heading_pattern = re.compile(r'\d{1,2}[\s\u3000]+([\u4e00-\u9fff]{2,3})[\s\u3000]+[A-Z]+')
                    matches = list(heading_pattern.finditer(para_text))
                    
                    if matches:
                        # 处理包含标题的段落
                        last_pos = 0
                        for match in matches:
                            season_name = match.group(1)
                            if season_name not in self.solar_terms:
                                continue
                            
                            # 输出标题之前的内容
                            before_heading = para_text[last_pos:match.start()].strip()
                            if before_heading and len(before_heading) > 20:
                                context_text = before_heading.replace("\n", "  ")
                                season = current_season if current_season != "未知" else self.detect_season(before_heading, full_text)
                                
                                paragraphs.append({
                                    "id": self.paragraph_id,
                                    "title": title,
                                    "context": context_text,
                                    "season": season
                                })
                                self.paragraph_id += 1
                            
                            # 更新当前节气
                            current_season = season_name
                            print(f"  检测到标题(段落中): {match.group(0).strip()} -> {current_season}")
                            
                            # 更新位置,跳过标题文本
                            last_pos = match.end()
                        
                        # 处理最后一个标题之后的内容
                        after_last_heading = para_text[last_pos:].strip()
                        if after_last_heading and len(after_last_heading) > 20:
                            context_text = after_last_heading.replace("\n", "  ")
                            season = current_season if current_season != "未知" else self.detect_season(after_last_heading, full_text)
                            
                            paragraphs.append({
                                "id": self.paragraph_id,
                                "title": title,
                                "context": context_text,
                                "season": season
                            })
                            self.paragraph_id += 1
                        
                        # 跳过这个段落的正常处理
                        continue
                
                # 使用当前节气作为段落的season
                season = current_season if current_season != "未知" else self.detect_season(para_text, full_text)
                
                # 将段落内的换行符替换为两个空格
                context_text = para_text.replace("\n", "  ")

                paragraphs.append({
                    "id": self.paragraph_id,
                    "title": title,
                    "context": context_text,
                    "season": season
                })
                self.paragraph_id += 1
                
        except Exception as e:
            print(f"  处理失败: {e}")
            import traceback
            traceback.print_exc()
        
        return paragraphs

    def process_all_pdfs(self) -> None:
        """处理所有PDF文件"""
        pdf_folder_path = Path(self.pdf_folder)
        
        if not pdf_folder_path.exists():
            print(f"错误: 文件夹 {self.pdf_folder} 不存在")
            return
        
        pdf_files = sorted(pdf_folder_path.glob("*.pdf"))
        if not pdf_files:
            print(f"警告: 在 {self.pdf_folder} 文件夹中没有找到PDF文件")
            return
        
        print(f"找到 {len(pdf_files)} 个PDF文件")
        
        for idx, pdf_file in enumerate(pdf_files, 1):
            print(f"正在处理 ({idx}/{len(pdf_files)}): {pdf_file.name}")
            paragraphs = self.extract_from_pdf(pdf_file)
            self.data.extend(paragraphs)
            print(f"  提取了 {len(paragraphs)} 个段落")
        
        print(f"\n总共提取了 {len(self.data)} 个段落")

    def save_to_json(self) -> None:
        """保存为JSON文件"""
        with open(self.output_file, "w", encoding="utf-8") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)
        
        print(f"\n数据已保存到 {self.output_file}")
        print(f"文件大小: {os.path.getsize(self.output_file) / 1024:.2f} KB")

    def run(self) -> None:
        """运行主流程"""
        print("=" * 60)
        print("PDF段落提取工具")
        print("=" * 60)
        
        self.process_all_pdfs()
        
        if self.data:
            self.save_to_json()
            
            print("\n统计信息:")
            titles = set(item["title"] for item in self.data)
            print(f"  文档数: {len(titles)}")
            print(f"  段落数: {len(self.data)}")
            print(f"  平均每文档段落数: {len(self.data) / len(titles):.1f}")
            
            if self.data:
                sample = self.data[0]
                print("\n第一个段落示例:")
                print(f"  ID: {sample['id']}")
                print(f"  标题: {sample['title']}")
                print(f"  内容预览: {sample['context'][:100]}...")
        else:
            print("\n警告: 没有提取到任何有效段落")


if __name__ == "__main__":
    extractor = PDFExtractor()
    extractor.run()
