import json
import re
import os
from tqdm import tqdm

# --- 配置区域 ---
INPUT_FILE = "extracted.jsonl"
OUTPUT_DIR = "cleaning_results_v2" # 输出到新文件夹

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

# 实体白名单 (单字也保留)
# 实体白名单 (即使长度为1也保留的实体)
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
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

class FileManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.files = {}
        self.passed_file = open(os.path.join(base_dir, "kg_final_passed.jsonl"), "w", encoding="utf-8")

    def write_passed(self, data):
        self.passed_file.write(json.dumps(data, ensure_ascii=False) + "\n")

    def write_rejected(self, reason_category, data):
        filename = f"reject_{reason_category}.jsonl"
        if filename not in self.files:
            self.files[filename] = open(os.path.join(self.base_dir, filename), "w", encoding="utf-8")
        self.files[filename].write(json.dumps(data, ensure_ascii=False) + "\n")

    def close_all(self):
        self.passed_file.close()
        for f in self.files.values():
            f.close()

def clean_string(text):
    if not text: return ""
    text = text.strip()
    text = re.sub(r'^[\"\'《“‘]+|[\"\'》”’。，]+$', '', text)
    return text

def validate_entity(entity):
    if not entity: return False, "empty"
    if len(entity) < 2 and entity not in ENTITY_WHITELIST: return False, "entity_too_short"
    if entity in ENTITY_BLACKLIST: return False, "entity_blacklist"
    if re.match(r'^[0-9\.]+$', entity): return False, "entity_numeric"
    if "http" in entity or "www" in entity: return False, "entity_url"
    return True, "passed"

def process_line(data, file_manager):
    extracted = data.get("extracted", {})
    doc_id = data.get("id")
    context_snippet = data.get("context", "")[:100]

    # --- 0. 核心检查：是否全是空？ ---
    # 如果 extracted 本身是 None，或者 三个字段都是空列表
    if not extracted:
        file_manager.write_rejected("empty_result", {"id": doc_id, "reason": "extracted field is missing", "context": context_snippet})
        return

    raw_entities = extracted.get("entities", [])
    raw_relations = extracted.get("relations", [])
    raw_attributes = extracted.get("attributes", [])

    # 检查是否三个列表都为空
    if not raw_entities and not raw_relations and not raw_attributes:
        file_manager.write_rejected("empty_result", {
            "id": doc_id, 
            "reason": "entities/relations/attributes all empty", 
            "context": context_snippet
        })
        return

    # --- 1. 处理实体 ---
    clean_entities_set = set()
    
    for ent in raw_entities:
        cleaned_ent = clean_string(ent)
        is_valid, reason = validate_entity(cleaned_ent)
        
        if is_valid:
            clean_entities_set.add(cleaned_ent)
        else:
            # 记录拒绝的实体
            file_manager.write_rejected(reason, {
                "id": doc_id,
                "invalid_entity": ent,
                "reason": reason,
                "context": context_snippet
            })

    # --- 2. 智能回填季节 ---
    current_season = data.get("season", "未知")
    if current_season == "未知" or not current_season:
        for ent in clean_entities_set:
            for term in SOLAR_TERMS:
                if term in ent:
                    current_season = term
                    break
            if current_season != "未知":
                break

    # --- 3. 处理关系 ---
    clean_relations_list = []
    seen_rels = set()
    
    for rel in raw_relations:
        if not isinstance(rel, list) or len(rel) < 3:
            file_manager.write_rejected("relation_format_error", {"id": doc_id, "invalid_rel": rel})
            continue

        head = clean_string(rel[0])
        relation_type = clean_string(rel[1])
        tail = clean_string(rel[2])

        # 依赖检查
        is_head_valid, h_reason = validate_entity(head)
        is_tail_valid, t_reason = validate_entity(tail)
        
        if not is_head_valid or not is_tail_valid:
            file_manager.write_rejected("relation_bad_entity", {
                "id": doc_id, 
                "invalid_rel": rel, 
                "reason": f"Head:{h_reason}, Tail:{t_reason}"
            })
            continue

        if head == tail:
            file_manager.write_rejected("relation_self_loop", {"id": doc_id, "invalid_rel": rel})
            continue

        # 确保关系中的实体被加入实体集
        clean_entities_set.add(head)
        clean_entities_set.add(tail)

        rel_tuple = (head, relation_type, tail)
        if rel_tuple not in seen_rels:
            seen_rels.add(rel_tuple)
            clean_relations_list.append([head, relation_type, tail])

    # --- 4. 再次检查清洗后的结果 ---
    # 如果清洗后变成了空结果（原本有脏数据，被洗没了），也算作空结果
    if not clean_entities_set and not clean_relations_list:
         file_manager.write_rejected("empty_after_cleaning", {
            "id": doc_id, 
            "reason": "All data filtered out", 
            "context": context_snippet
        })
         return

    # --- 5. 写入通过数据 ---
    final_data = {
        "id": doc_id,
        "title": data.get("title", ""),
        "season": current_season,
        "context": data.get("context", ""),
        "kg_data": {
            "entities": list(clean_entities_set),
            "relations": clean_relations_list
        }
    }
    file_manager.write_passed(final_data)

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"错误: 找不到输入文件 {INPUT_FILE}")
        return

    fm = FileManager(OUTPUT_DIR)
    
    print("开始清洗数据...")
    print(f"结果将保存在文件夹: {OUTPUT_DIR}/")
    
    with open(INPUT_FILE, "r", encoding="utf-8") as f_in:
        for line in tqdm(f_in):
            if not line.strip(): continue
            try:
                raw_data = json.loads(line)
                process_line(raw_data, fm)
            except json.JSONDecodeError:
                continue

    fm.close_all()
    print("\n清洗完成！")

if __name__ == "__main__":
    main()