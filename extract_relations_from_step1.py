import argparse
import json
import csv
import os
import torch
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModelForCausalLM

MODEL_PATH = "/Users/oyzh/KnowledgeGraph/models/Qwen3-4B-Instruct-2507" 

INPUT_FILE = "step1_entities_with_context.jsonl"

OUTPUT_FILE = "relations_with_season.csv"
PROGRESS_FILE = "relations_with_season.progress"

MAX_CANDIDATES = 60
MAX_CONTEXT_LENGTH = 1500

device = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"Using device: {device}")

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

def extract_relations(context, candidate_entities_list):
    if len(candidate_entities_list) > MAX_CANDIDATES:
        candidate_entities_list.sort(key=lambda x: len(x['name']), reverse=True)
        candidate_entities_list = candidate_entities_list[:MAX_CANDIDATES]
    
    if len(candidate_entities_list) < 2:
        return []

    candidates_str = "\n".join([f"- {item['name']} ({item['label']})" for item in candidate_entities_list])
    valid_candidate_names = set([item['name'] for item in candidate_entities_list])

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
        
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]
            
        result = json.loads(json_str)
        
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

def load_seen_relations(output_file):
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

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        total_lines = sum(1 for _ in f)

    print(f"Processing {total_lines} documents from {INPUT_FILE}...")

    seen_relations = load_seen_relations(OUTPUT_FILE)
    file_exists = os.path.exists(OUTPUT_FILE)

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

    with open(OUTPUT_FILE, "a", newline='', encoding='utf-8') as f_out:
        writer = csv.writer(f_out)
        
        if not file_exists or os.path.getsize(OUTPUT_FILE) == 0:
            writer.writerow(["source", "target", "type", "season"])
        
        with open(INPUT_FILE, "r", encoding="utf-8") as f_in:
            if start_line > 0:
                for _ in range(start_line):
                    next(f_in, None)

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
                        with open(PROGRESS_FILE, "w", encoding="utf-8") as pf: pf.write(str(idx))
                        continue
                    
                    if current_season != "未知":
                        season_ent = next((x for x in entities if x['name'] == current_season), None)
                        if season_ent:
                            entities.remove(season_ent)
                            entities.insert(0, season_ent)

                    relations = extract_relations(context, entities)
                    
                    for rel in relations:
                        head, relation_type, tail = rel
                        
                        if head in ["养生", "饮食", "方法", "措施"] and relation_type in ["包含", "属于", "包括", "涉及"]:
                            continue
                        if relation_type == "属于" and tail == "养生":
                            continue

                        rel_tuple = (head, tail, relation_type, current_season)
                        
                        if rel_tuple not in seen_relations:
                            writer.writerow([head, tail, relation_type, current_season])
                            seen_relations.add(rel_tuple)
                            f_out.flush()

                    with open(PROGRESS_FILE, "w", encoding="utf-8") as pf:
                        pf.write(str(idx))
                            
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    with open(PROGRESS_FILE, "w", encoding="utf-8") as pf: pf.write(str(idx))
                    continue

    if os.path.exists(PROGRESS_FILE):
        try: os.remove(PROGRESS_FILE)
        except: pass

    print(f"Done! Relations saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
