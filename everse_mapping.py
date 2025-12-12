import json
import csv
import os
from tqdm import tqdm

# ================= 配置区域 =================
RAW_DATA_FILE = "knowledge.json"      # 原始文本文件
ENTITY_FILE = "entity_types.csv"      # 实体分类表
OUTPUT_FILE = "step1_entities_with_context.jsonl" # 输出文件

def load_entity_map():
    """读取 CSV，构建 {实体名: 类别} 字典"""
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

    # 为了避免短词（如“气”）误匹配到长词（如“天气”）内部
    # 我们可以先按长度倒序排列实体，优先匹配长词
    # 但最终输出时，我们要按【原文位置】排序
    sorted_entity_keys = sorted(entity_map.keys(), key=len, reverse=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
        matched_count = 0
        
        for item in tqdm(raw_data):
            context = item.get("context", "")
            if not context: continue
            
            # --- 1. 匹配并记录位置 ---
            found_candidates = []
            
            # 遍历所有已知实体
            for name in sorted_entity_keys:
                # 使用 find 获取实体在文本中的起始位置
                # 注意：这里只找第一个出现的位置，对于关系抽取这就够了
                # 如果一个实体出现多次，通常只列出一次 unique entity 即可
                start_index = context.find(name)
                
                if start_index != -1:
                    label = entity_map[name]
                    found_candidates.append({
                        "name": name, 
                        "label": label,
                        "start_index": start_index # 关键：记录位置
                    })
            
            # --- 2. 关键修正：按原文出现顺序排序 ---
            # 根据 start_index 从小到大排序
            found_candidates.sort(key=lambda x: x["start_index"])
            
            # --- 3. 移除临时用的 start_index 字段，生成最终列表 ---
            final_entities = [{"name": x["name"], "label": x["label"]} for x in found_candidates]

            # 只有当这段话里确实包含了我们关注的实体时，才保存
            if final_entities:
                output_record = {
                    "id": item.get("id"),
                    "season": item.get("season", "未知"),
                    "context": context,
                    "entities": final_entities # 现在这是有序的了！
                }
                
                f_out.write(json.dumps(output_record, ensure_ascii=False) + "\n")
                matched_count += 1

    print(f"✅ 处理完成！")
    print(f"结果已保存至: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()