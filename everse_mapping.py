import json
import csv
import os
from tqdm import tqdm

RAW_DATA_FILE = "knowledge.json"
ENTITY_FILE = "entity_types.csv"
OUTPUT_FILE = "step1_entities_with_context.jsonl"

def load_entity_map():
    print("正在加载实体表...")
    entity_map = {}
    if not os.path.exists(ENTITY_FILE):
        print(f"错误: 找不到 {ENTITY_FILE}")
        return {}
        
    with open(ENTITY_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        for row in reader:
            if len(row) >= 2:
                name, label = row[0].strip(), row[1].strip()
                if name:
                    entity_map[name] = label
    
    print(f"✅ 已加载 {len(entity_map)} 个唯一实体。")
    return entity_map

def main():
    entity_map = load_entity_map()
    if not entity_map: return

    if not os.path.exists(RAW_DATA_FILE):
        print(f"错误: 找不到 {RAW_DATA_FILE}")
        return

    print("正在读取原始数据...")
    with open(RAW_DATA_FILE, "r", encoding="utf-8") as f:
        try:
            raw_data = json.load(f)
        except:
            f.seek(0)
            raw_data = [json.loads(line) for line in f if line.strip()]

    print(f"开始反向映射 {len(raw_data)} 条文档...")

    sorted_entity_keys = sorted(entity_map.keys(), key=len, reverse=True)  # 长词优先，避免子串误匹配

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
        matched_count = 0
        
        for item in tqdm(raw_data):
            context = item.get("context", "")
            if not context: continue

            found_candidates = []

            for name in sorted_entity_keys:
                start_index = context.find(name)
                
                if start_index != -1:
                    label = entity_map[name]
                    found_candidates.append({
                        "name": name, 
                        "label": label,
                        "start_index": start_index
                    })

            found_candidates.sort(key=lambda x: x["start_index"])

            final_entities = [{"name": x["name"], "label": x["label"]} for x in found_candidates]

            if final_entities:
                output_record = {
                    "id": item.get("id"),
                    "season": item.get("season", "未知"),
                    "context": context,
                    "entities": final_entities
                }
                
                f_out.write(json.dumps(output_record, ensure_ascii=False) + "\n")
                matched_count += 1

    print(f"✅ 处理完成！")
    print(f"结果已保存至: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
