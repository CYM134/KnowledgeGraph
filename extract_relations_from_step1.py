import argparse
import json
import csv
import os
import torch
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModelForCausalLM

# ================= 配置区域 =================
# 1. 模型路径 (请确认无误)
MODEL_PATH = "/Users/oyzh/KnowledgeGraph/models/Qwen3-4B-Instruct-2507" 

# 2. 输入文件 (上一步生成的中间文件)
INPUT_FILE = "step1_entities_with_context.jsonl"

# 3. 输出文件
OUTPUT_FILE = "relations_with_season.csv"
PROGRESS_FILE = "relations_with_season.progress"

# 【安全限制】
MAX_CANDIDATES = 60       # 每条 Prompt 最多放入多少个候选实体
MAX_CONTEXT_LENGTH = 1500 # 输入文本最大长度

# 检测设备
device = "mps" if torch.backends.mps.is_available() else "cpu"
# device = "cuda"
print(f"Using device: {device}")

# ================= 1. 模型加载 =================
print("Loading model...")
try:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH, 
        torch_dtype=torch.float16, 
        device_map={"": device}, 
        trust_remote_code=True
    )
    model.eval()
except Exception as e:
    print(f"Error loading model: {e}")
    exit()

# ================= 2. 核心提取函数 (Prompt 最终优化版) =================

def extract_relations(context, candidate_entities_list):
    """
    context: 原文
    candidate_entities_list: [{"name": "立春", "label": "SolarTerm"}, ...]
    """
    # 1. 保护机制：如果候选实体太多，进行截断 (优先保留长的)
    if len(candidate_entities_list) > MAX_CANDIDATES:
        candidate_entities_list.sort(key=lambda x: len(x['name']), reverse=True)
        candidate_entities_list = candidate_entities_list[:MAX_CANDIDATES]
    
    # 如果实体少于2个，无法构成关系
    if len(candidate_entities_list) < 2:
        return []

    # 构造候选列表字符串
    candidates_str = "\n".join([f"- {item['name']} ({item['label']})" for item in candidate_entities_list])
    valid_candidate_names = set([item['name'] for item in candidate_entities_list])

    # ---------------------------------------------------------
    # 核心修改：Prompt 强化
    # ---------------------------------------------------------
    system_prompt = f"""你是一个中医知识图谱构建专家。
任务：根据【候选实体列表】，从【当前文本】中提取实体间的核心语义关系。

【候选实体列表】
{candidates_str}

【重要原则 - 请严格遵守】
1. **以节气/核心概念为主体**：
   - 如果文本在讲某个节气的养生建议，**头实体(Subject)优先选择该节气**。
   - 错误示例：["养生", "宜", "补肾"] (太泛化，丢失了节气信息)
   - 正确示例：["立冬", "宜", "补肾"] (将建议直接挂载到节气上)
   
2. **拒绝通用/废话关系**：
   - 不要提取定义类关系，如 ["补肾", "属于", "养生"]、["饮食", "包含", "羊肉"]、["方法", "包括", "导引"]。
   - 我们只关注 **【功效、宜食、忌食、导致(病因)、对应脏腑、主治、创编】** 等具有实际指导意义的关系。

3. **格式要求**：
   - 输出 JSON 列表：[["头实体", "关系", "尾实体"], ...]
   - 头尾实体必须严格来自候选列表，**禁止创造新词**。

示例输入：
文本："立冬之时，阳气潜藏，养生应以补肾藏精为主，宜食羊肉。"
候选：[立冬, 阳气, 养生, 补肾, 藏精, 羊肉]

示例输出：
[
    ["立冬", "特征", "阳气潜藏"], 
    ["立冬", "养生重点", "补肾"], 
    ["立冬", "养生重点", "藏精"], 
    ["立冬", "宜食", "羊肉"]
]"""
    # ---------------------------------------------------------

    safe_context = context[:MAX_CONTEXT_LENGTH]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"当前文本：\n{safe_context}"}
    ]

    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer([text], return_tensors="pt").to(device)

    try:
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=False,
                temperature=0.1
            )
        
        response = tokenizer.decode(output[0][len(inputs.input_ids[0]):], skip_special_tokens=True).strip()
        
        # 清洗 JSON
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]
            
        result = json.loads(json_str)
        
        # 二次验证：确保头尾实体都在候选列表中
        valid_relations = []
        if isinstance(result, list):
            for rel in result:
                if len(rel) == 3:
                    head, relation, tail = rel
                    if head in valid_candidate_names and tail in valid_candidate_names and head != tail:
                        valid_relations.append([head, relation, tail])
        
        return valid_relations

    except Exception as e:
        return []

# ================= 3. 主流程 =================

def load_seen_relations(output_file):
    """读取已有 CSV，用于内存去重"""
    seen = set()
    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        return seen

    with open(output_file, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for idx, row in enumerate(reader):
            if idx == 0: continue
            if len(row) >= 4:
                seen.add((row[0], row[1], row[2], row[3]))
    return seen

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-line", type=int, default=None, help="强制从第几行开始跑")
    return parser.parse_args()

def main():
    args = parse_args()
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found!")
        print("请先运行 reverse_mapping.py 生成这个文件。")
        return

    # 读取总行数
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        total_lines = sum(1 for _ in f)

    print(f"Processing {total_lines} documents from {INPUT_FILE}...")

    # 加载已有结果
    seen_relations = load_seen_relations(OUTPUT_FILE)
    file_exists = os.path.exists(OUTPUT_FILE)

    # 确定开始行
    start_line = 0
    if args.start_line is not None:
        start_line = max(args.start_line, 0)
    elif os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as pf:
                start_line = int(pf.read().strip() or 0)
        except: pass

    if start_line > 0:
        print(f"Resuming from line {start_line + 1}...")

    # 打开输出文件
    with open(OUTPUT_FILE, "a", newline='', encoding='utf-8') as f_out:
        writer = csv.writer(f_out)
        
        # 写表头
        if not file_exists or os.path.getsize(OUTPUT_FILE) == 0:
            writer.writerow(["source", "target", "type", "season"])
        
        # 读取输入文件
        with open(INPUT_FILE, "r", encoding="utf-8") as f_in:
            # 快速跳过已处理行
            if start_line > 0:
                for _ in range(start_line):
                    next(f_in, None)

            # 主循环
            for idx, line in enumerate(
                tqdm(f_in, total=total_lines, initial=start_line, desc="Extracting"),
                start=start_line + 1
            ):
                if not line.strip():
                    continue

                try:
                    data = json.loads(line)
                    context = data.get("context", "")
                    entities = data.get("entities", [])
                    current_season = data.get("season", "未知")
                    
                    if not entities or len(entities) < 2 or len(context) < 5:
                        # 即使跳过也要更新进度
                        with open(PROGRESS_FILE, "w", encoding="utf-8") as pf: pf.write(str(idx))
                        continue
                    
                    # 优化：将 current_season 实体提到最前 (Priming Effect)
                    if current_season != "未知":
                        season_ent = next((x for x in entities if x['name'] == current_season), None)
                        if season_ent:
                            entities.remove(season_ent)
                            entities.insert(0, season_ent)

                    # 调用抽取
                    relations = extract_relations(context, entities)
                    
                    for rel in relations:
                        head, relation_type, tail = rel
                        
                        # --- 规则清洗：过滤废话关系 ---
                        if head in ["养生", "饮食", "方法", "措施"] and relation_type in ["包含", "属于", "包括", "涉及"]:
                            continue
                        if relation_type == "属于" and tail == "养生": # 过滤 "补肾属于养生"
                            continue

                        rel_tuple = (head, tail, relation_type, current_season)
                        
                        if rel_tuple not in seen_relations:
                            writer.writerow([head, tail, relation_type, current_season])
                            seen_relations.add(rel_tuple)
                            f_out.flush() # 实时保存

                    # 记录进度
                    with open(PROGRESS_FILE, "w", encoding="utf-8") as pf:
                        pf.write(str(idx))
                            
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    # print(f"Error at line {idx}: {e}")
                    with open(PROGRESS_FILE, "w", encoding="utf-8") as pf: pf.write(str(idx))
                    continue

    # 跑完删除进度文件
    if os.path.exists(PROGRESS_FILE):
        try: os.remove(PROGRESS_FILE)
        except: pass

    print(f"Done! Relations saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()