"""从 knowledge/ 的 PDF 提取相关段落到 knowledge.json。"""

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

        self.skip_keywords = [
            "作者", "通讯作者", "关键词", "文章编号", "中图分类号",
            "文献标识码", "文献标志码", "收稿日期", "修回日期", "出版日期",
            "基金项目", "引用格式", "第一作者", "通信作者", "版权", "出版社"
        ]

        self.abstract_markers = ["摘要", "abstract", "【摘要】"]
        self.keyword_markers = ["关键词", "key words", "【关键词】"]
        self.reference_markers = ["参考文献", "references", "[参考文献]"]

        self.relevant_keywords = [
            "二十四节气", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
            "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑",
            "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
            "小寒", "大寒", "节气", "养生"
        ]

        self.relaxed_keywords = ["宜吃", "调配", "保健", "少吃", "不能吃"]

        self.solar_terms = [
            "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
            "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
            "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
            "立冬", "小雪", "大雪", "冬至", "小寒", "大寒"
        ]

    def clean_text(self, text: str, preserve_punctuation: bool = True, preserve_raw: bool = False) -> str:
        if not text:
            return ""

        text = re.sub(r"[\[［【〔]\s*\d+[^\]］】〕]*[\]］】〕]", "", text)
        text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", text)
        text = text.replace("~", "")
        text = re.sub(r'""', '', text)
        text = re.sub(r"''", '', text)
        text = re.sub(r'"\s+"', '', text)
        text = re.sub(r"'\s+'", '', text)

        if not preserve_raw:
            text = re.sub(r"[A-Za-zＡ-Ｚａ-ｚ]+", "", text)
            text = re.sub(r"[0-9０-９]+", "", text)
            text = re.sub(r"[\[\]\(\)（）【】［］〈〉<>{}]", "", text)

        if preserve_punctuation:
            text = re.sub(r"[ \t]+", " ", text)
        else:
            text = re.sub(r"\s+", "", text)

        return text.strip()

    def should_skip_line(self, text: str, preserve_raw: bool = False) -> bool:
        if not text or len(text) < 5:
            return True

        text_lower = text.lower()

        for keyword in self.skip_keywords:
            if keyword in text or keyword.lower() in text_lower:
                return True

        if re.fullmatch(r"[·\s]*\d+[·\s]*", text):
            return True

        if re.search(r"第\s*\d+\s*卷|第\s*\d+\s*期", text):
            return True

        if re.search(r"\d{4}\s*年\s*\d{1,2}\s*月", text):
            return True

        if re.search(r"doi", text_lower):
            return True

        if not preserve_raw and not re.search(r"[\u4e00-\u9fff]", text):
            return True

        return False

    def is_valid_paragraph(self, text: str) -> bool:
        if not text or len(text) < 30:
            return False

        chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        if chinese_count < 20:
            return False

        return True

    def is_relevant(self, text: str) -> bool:
        if any(keyword in text for keyword in self.relevant_keywords):
            return True

        if any(keyword in text for keyword in self.relaxed_keywords):
            return True

        return False

    def normalize_title(self, filename: str) -> str:
        base = filename.replace(".pdf", "")
        return base.split("_")[0]

    def detect_columns(self, chars: List[dict], page_width: float) -> List[float]:
        if not chars:
            return []

        x_positions = [char['x0'] for char in chars]
        x_positions.sort()

        gaps = []
        for i in range(len(x_positions) - 1):
            gap = x_positions[i + 1] - x_positions[i]
            if gap > page_width * 0.05:  # 5% 宽度阈值
                gaps.append((x_positions[i] + gap / 2, gap))

        gaps.sort(key=lambda x: x[1], reverse=True)
        column_dividers = [g[0] for g in gaps[:2]]
        column_dividers.sort()

        return column_dividers

    def assign_column(self, x0: float, dividers: List[float]) -> int:
        for idx, divider in enumerate(dividers):
            if x0 < divider:
                return idx
        return len(dividers)

    def extract_full_text(self, pdf_path: Path) -> str:
        full_text = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    chars = page.chars
                    if not chars:
                        continue

                    column_dividers = self.detect_columns(chars, page.width)

                    for char in chars:
                        char['page'] = page_num
                        char['column'] = self.assign_column(char['x0'], column_dividers)

                    from collections import defaultdict
                    lines_dict = defaultdict(list)

                    for char in chars:
                        line_key = (char['column'], round(char['top'] / 5) * 5)  # top 5px 容差
                        lines_dict[line_key].append(char)

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

            if any(marker in line or marker in line_lower for marker in self.reference_markers):
                in_references = True
                continue
            
            if in_references:
                continue
            
            if any(marker in line or marker in line_lower for marker in self.abstract_markers):
                in_abstract = True
                continue

            if any(marker in line or marker in line_lower for marker in self.keyword_markers):
                in_keywords = True
                continue
            
            if in_abstract or in_keywords:
                continue
            
            if self.should_skip_line(line, preserve_raw=preserve_raw):
                continue

            processed_lines.append(line)

        return "\n".join(processed_lines)

    def split_paragraphs(self, text: str, preserve_raw: bool = False) -> List[str]:
        blocks = text.split("\n\n")
        
        paragraphs = []
        current_para = ""
        
        for block in blocks:
            block = block.strip()
            if not block:
                continue

            cleaned = self.clean_text(block, preserve_punctuation=True, preserve_raw=preserve_raw)
            if not cleaned:
                continue

            if current_para and len(cleaned) < 100:
                current_para += cleaned
            elif current_para and not current_para[-1] in "。！？；：":
                current_para += cleaned
            else:
                if current_para and self.is_valid_paragraph(current_para) and self.is_relevant(current_para):
                    paragraphs.append(current_para)
                current_para = cleaned

        if current_para and self.is_valid_paragraph(current_para) and self.is_relevant(current_para):
            paragraphs.append(current_para)

        if len(paragraphs) < 3:
            return self.split_by_sentences(text, preserve_raw=preserve_raw)

        return paragraphs

    def split_by_sentences(self, text: str, preserve_raw: bool = False) -> List[str]:
        cleaned = self.clean_text(text, preserve_punctuation=True, preserve_raw=preserve_raw)

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
        for term in self.solar_terms:
            if term in paragraph:
                return term

        para_pos = full_text.find(paragraph[:50])

        if para_pos > 0:
            context_before = full_text[max(0, para_pos - 500):para_pos]

            lines = context_before.split('\n')
            for line in reversed(lines):
                for term in self.solar_terms:
                    if term in line and len(line) < 100:
                        return term

        return "未知"
    
    def extract_from_pdf(self, pdf_path: Path) -> List[dict]:
        paragraphs = []

        try:
            full_text = self.extract_full_text(pdf_path)
            if not full_text:
                return paragraphs

            special_file_keywords = ["二十四节气养生经", "24节气养生法", "Z-Library"]  # 保留英数/括号
            is_special_file = any(k in pdf_path.name for k in special_file_keywords)

            processed_text = self.process_text(full_text, preserve_raw=is_special_file)

            title = self.normalize_title(pdf_path.name)
            paragraph_texts = self.split_paragraphs(processed_text, preserve_raw=is_special_file)
            
            if len(paragraph_texts) < 5:
                print(f"  警告: {pdf_path.name} 仅提取 {len(paragraph_texts)} 个相关段落")

            current_season = "未知"

            for para_text in paragraph_texts:
                if is_special_file:  # 标题格式：01 立春 LICHUN
                    heading_match = re.match(r'^\s*\d{1,2}[\s\u3000]+([\u4e00-\u9fff]{2,3})[\s\u3000]+[A-Z]+', para_text.strip())
                    if heading_match and heading_match.group(1) in self.solar_terms:
                        current_season = heading_match.group(1)
                        print(f"  检测到标题(开头): {heading_match.group(0).strip()} -> {current_season}")
                        continue

                    heading_pattern = re.compile(r'\d{1,2}[\s\u3000]+([\u4e00-\u9fff]{2,3})[\s\u3000]+[A-Z]+')
                    matches = list(heading_pattern.finditer(para_text))

                    if matches:
                        last_pos = 0
                        for match in matches:
                            season_name = match.group(1)
                            if season_name not in self.solar_terms:
                                continue

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

                            current_season = season_name
                            print(f"  检测到标题(段落中): {match.group(0).strip()} -> {current_season}")

                            last_pos = match.end()

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

                        continue

                season = current_season if current_season != "未知" else self.detect_season(para_text, full_text)
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
        with open(self.output_file, "w", encoding="utf-8") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)
        
        print(f"\n数据已保存到 {self.output_file}")
        print(f"文件大小: {os.path.getsize(self.output_file) / 1024:.2f} KB")

    def run(self) -> None:
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
