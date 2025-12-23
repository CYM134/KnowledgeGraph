import csv
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Set, Tuple
from tqdm import tqdm

# --- 配置区域 ---
INPUT_NODES_FILE = "step1_entities_with_context.jsonl"
INPUT_RELATIONS_FILE = "relations_with_season.csv"
OUTPUT_DIR = "cleaning_results_v3"  
OUTPUT_NODES_FILE = os.path.join(OUTPUT_DIR, "clean_nodes.csv")
OUTPUT_RELATIONS_FILE = os.path.join(OUTPUT_DIR, "clean_relations.csv")

# 24节气（用于回填）
SOLAR_TERMS = {
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒"
}

# 实体黑名单
ENTITY_BLACKLIST = {
    "我们", "专家", "研究", "本文", "其中", "另外", "因此", "所以", "各种",
    "部分", "一些", "左右", "以上", "以下", "具有", "可以", "可能",
    "相关", "非常", "重要", "主要", "一般", "往往", "中医", "西医",
    "中国", "我国", "明显", "很多", "尤其", "但是", "而且", "这个", "那个"
}
# 实体白名单
ENTITY_WHITELIST = {
    # --- 1. 核心理论与自然 ---
    "金", "木", "水", "火", "土", 
    "阴", "阳", "精", "气", "神",
    "风", "雨", "雷", "电", "露", "霜", "雪", "冰", "雾",
    "寒", "暑", "湿", "燥", "热", "凉", "暖", "温",
    
    # --- 2. 脏腑与身体部位 ---
    "心", "肝", "脾", "肺", "肾", "胆", "胃", "肠",
    "头", "面", "口", "鼻", "耳", "目", "眼", "舌", "齿", "喉",
    "项", "背", "胸", "腹", "腰", "臀", "脐",
    "手", "臂", "指", "腿", "膝", "足", "脚",
    "身", "体", "肌", "肤", "皮", "肉", "骨", "筋", "脉", "血",
    "汗", "尿", "便", "痰", "津", "液",

    # --- 3. 食物与药物 ---
    "葱", "姜", "蒜", "韭", "椒", "芹", "芥", 
    "藕", "笋", "瓜", "茄", "豆", "芽", "苗", "叶", "根",
    "梨", "桃", "杏", "李", "梅", "枣", "栗", "柿", "橘", "柚",
    "鱼", "肉", "禽", "蛋", "奶", "虾", "蟹", "鳖", "龟",
    "粥", "汤", "饭", "面", "茶", "酒", "水", "饮",
    "醋", "盐", "糖", "蜜", "油", "酱",
    "谷", "麦", "黍", "稷", "稻", "粱", "米", "粮",
    "药", "毒", "仁", "草", "花", "果",

    # --- 4. 时间与节气 ---
    "春", "夏", "秋", "冬", 
    "年", "月", "日", "时", "季", "候", "旬",
    "晨", "午", "晚", "夜", "昼",
    # [新增] 核心理论 & 状态
    "养", # 养生核心 (id 5, 51)
    "营", # 营卫之气 (id 21)
    
    # [新增] 食物 & 味道 (补全)
    "酸", "甜", "苦", "辣", "咸", # 五味 (id 142, 446, 934, 988)
    "肥", # 肥甘厚味 (id 304)
    "蔬", "果", # 蔬果 (id 304)
    
    # [新增] 动物 (补全)
    "狗", # 常见食材 (id 486)
    "鹰", # 候鸟/物候 (id 963)
    "蝉", # 物候 (id 618)
    "獭", # 物候/祭鱼 (id 992)
    
    # [新增] 植物 (补全)
    "禾", # 禾苗/谷物 (id 957, 963)
    "桐", # 桐花 (id 773)
    "菌", # 食用菌 (id 779)
    
    # [新增] 人物 (姓氏/代称)
    "人", # 泛指人类 (id 629)
    "杨", "谭", # 医生/作者姓氏 (id 984)
    
    # [新增] 自然 & 方位
    "云", # 巧云/物候 (id 961)
    "外", # 户外/外邪 (id 977) 
}
os.makedirs(OUTPUT_DIR, exist_ok=True)


class RejectLogger:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.files: Dict[str, Any] = {}
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir, exist_ok=True)

    def log(self, category: str, data: dict) -> None:
        filename = os.path.join(self.base_dir, f"{category}.jsonl")
        if filename not in self.files:
            self.files[filename] = open(filename, "w", encoding="utf-8")
        self.files[filename].write(json.dumps(data, ensure_ascii=False) + "\n")

    def close(self) -> None:
        for f in self.files.values():
            f.close()


def clean_string(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r'^[\"\'《“‘]+|[\"\'》”’。，]+$', '', text)
    return text


def validate_entity(entity: str) -> Tuple[bool, str]:
    if not entity:
        return False, "empty"
    if len(entity) < 2 and entity not in ENTITY_WHITELIST:
        return False, "entity_too_short"
    if entity in ENTITY_BLACKLIST:
        return False, "entity_blacklist"
    if re.match(r'^[0-9\\.]+$', entity):
        return False, "entity_numeric"
    if "http" in entity or "www" in entity:
        return False, "entity_url"
    return True, "passed"


def infer_season(season: str, names: Iterable[str]) -> str:
    season = clean_string(season) or "未知"
    if season and season != "未知":
        return season
    for name in names:
        if not name:
            continue
        for term in SOLAR_TERMS:
            if term in name:
                return term
    return "未知"


def load_nodes(nodes_path: str, logger: RejectLogger) -> Tuple[Dict[str, str], Set[str]]:
    label_votes: Dict[str, Counter] = defaultdict(Counter)
    valid_nodes: Set[str] = set()
    total_entities = 0

    with open(nodes_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(tqdm(f, desc="加载节点", unit="行"), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.log("reject_node_json_error", {"line_no": line_no})
                continue

            context_snippet = record.get("context", "")[:100]
            for ent in record.get("entities") or []:
                total_entities += 1
                name = clean_string(ent.get("name", ""))
                label = ent.get("label") or "Entity"

                is_valid, reason = validate_entity(name)
                if not is_valid:
                    logger.log(
                        f"reject_node_{reason}",
                        {
                            "line_no": line_no,
                            "name": ent.get("name"),
                            "label": label,
                            "context": context_snippet,
                        },
                    )
                    continue

                valid_nodes.add(name)
                label_votes[name][label] += 1

    nodes: Dict[str, str] = {}
    for name, votes in label_votes.items():
        nodes[name] = votes.most_common(1)[0][0] if votes else "Entity"

    print(f"节点候选: {len(nodes)} 个，累计实体记录 {total_entities} 条")
    return nodes, valid_nodes


def load_relations(
    rel_path: str, valid_nodes: Set[str], logger: RejectLogger
) -> List[Tuple[str, str, str, str]]:
    cleaned: List[Tuple[str, str, str, str]] = []
    seen: Set[Tuple[str, str, str, str]] = set()

    with open(rel_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print("关系文件为空或缺少表头")
            return cleaned

        for row_no, row in enumerate(tqdm(reader, desc="加载关系", unit="条"), start=2):
            head = clean_string(
                row.get("source")
                or row.get("head")
                or row.get("subject")
                or ""
            )
            tail = clean_string(
                row.get("target")
                or row.get("tail")
                or row.get("object")
                or ""
            )
            relation_type = clean_string(row.get("type") or row.get("relation") or "")
            season = clean_string(row.get("season") or "") or "未知"

            if not relation_type:
                logger.log(
                    "reject_relation_format_error",
                    {"row": row_no, "relation": row},
                )
                continue

            is_head_valid, h_reason = validate_entity(head)
            is_tail_valid, t_reason = validate_entity(tail)
            if not is_head_valid or not is_tail_valid:
                logger.log(
                    "reject_relation_bad_entity",
                    {
                        "row": row_no,
                        "relation": row,
                        "reason": f"Head:{h_reason}, Tail:{t_reason}",
                    },
                )
                continue

            if head == tail:
                logger.log(
                    "reject_relation_self_loop",
                    {"row": row_no, "relation": row},
                )
                continue

            if valid_nodes and (head not in valid_nodes or tail not in valid_nodes):
                logger.log(
                    "reject_relation_missing_node",
                    {"row": row_no, "relation": row},
                )
                continue

            season = infer_season(season, [head, tail])
            rel_tuple = (head, tail, relation_type, season)
            if rel_tuple in seen:
                continue

            seen.add(rel_tuple)
            cleaned.append(rel_tuple)

    print(f"有效关系: {len(cleaned)} 条")
    return cleaned


def write_nodes(path: str, nodes: Dict[str, str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "label"])
        for name in sorted(nodes.keys()):
            writer.writerow([name, nodes[name]])


def write_relations(path: str, relations: List[Tuple[str, str, str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target", "type", "season"])
        for head, tail, relation_type, season in relations:
            writer.writerow([head, tail, relation_type, season])


def main() -> None:
    if not os.path.exists(INPUT_NODES_FILE):
        print(f"错误: 找不到节点文件 {INPUT_NODES_FILE}")
        return
    if not os.path.exists(INPUT_RELATIONS_FILE):
        print(f"错误: 找不到关系文件 {INPUT_RELATIONS_FILE}")
        return

    logger = RejectLogger(OUTPUT_DIR)

    print("开始清洗节点与关系...")
    nodes, valid_nodes = load_nodes(INPUT_NODES_FILE, logger)
    node_names = set(nodes.keys())

    if not node_names:
        logger.close()
        print("没有可用节点，终止。")
        return

    relations = load_relations(INPUT_RELATIONS_FILE, node_names, logger)

    write_nodes(OUTPUT_NODES_FILE, nodes)
    write_relations(OUTPUT_RELATIONS_FILE, relations)
    logger.close()

    print(f"已写入节点: {OUTPUT_NODES_FILE} ({len(nodes)} 条)")
    print(f"已写入关系: {OUTPUT_RELATIONS_FILE} ({len(relations)} 条)")
    print("清洗完成！")


if __name__ == "__main__":
    main()
