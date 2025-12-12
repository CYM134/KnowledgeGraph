import json
import csv
import os
import torch
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModelForCausalLM

# ================= 配置区域 =================
# 请确保路径正确
MODEL_PATH = "/Users/oyzh/KnowledgeGraph/models/Qwen3-4B-Instruct-2507" 
INPUT_FILE = "knowledge.json"  # 你的原始数据文件
OUTPUT_CSV = "entity_types.csv" # 最终输出的节点表

# 定义 Schema (分类标准)
SCHEMA_DESC = """
请从文本中提取以下类别的实体，并直接标记类别：
1. SolarTerm (节气): 24节气名称
2. Technique (功法): 具体的招式、动作、导引术
3. FoodHerb (食药): 食材、中药、饮品
4. DiseaseSymptom (病症): 疾病、症状、不适
5. BodyPart (部位): 脏腑、穴位、身体部位
6. Person (人物): 医家、作者、历史人物
7. Source (典籍): 书名、期刊名
8. Concept (概念): 中医理论、阴阳五行
9. TimeSeason (时间): 季节、朝代、时间段
10. OrgLocation (地点): 机构、城市、地理位置
11. Other (其他): 有意义但无法归类的实体
"""

# 检测设备
device = "mps" if torch.backends.mps.is_available() else "cpu"
# device = "cuda" # 如果是 NVIDIA 显卡请解开这行
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
    print("Model loaded successfully.")
except Exception as e:
    print(f"Error loading model: {e}")
    exit()

# ================= 2. 核心提取函数 =================

def extract_entities_from_text(text):
    """
    输入一段文本，输出提取到的实体列表 [{"name": "...", "label": "..."}, ...]
    """
    if not text or len(text) < 5: return []

    # Few-Shot 示例 (使用民俗生活场景，防止污染中医数据)
    few_shot = """
示例输入：
"冬至这天，北京市民张大爷在菜市场买了羊肉和白萝卜，回家给孙子包了顿饺子。俗话说‘冬至不端饺子碗，冻掉耳朵没人管’，一家人吃得很开心。"

示例输出：
[
    {{"name": "冬至", "label": "SolarTerm"}},
    {{"name": "北京", "label": "OrgLocation"}},
    {{"name": "张大爷", "label": "Person"}},
    {{"name": "菜市场", "label": "OrgLocation"}},
    {{"name": "羊肉", "label": "FoodHerb"}},
    {{"name": "白萝卜", "label": "FoodHerb"}},
    {{"name": "孙子", "label": "Person"}},
    {{"name": "饺子", "label": "FoodHerb"}},
    {{"name": "冻掉", "label": "DiseaseSymptom"}},
    {{"name": "耳朵", "label": "BodyPart"}}
]"""

    # System Prompt (加入防抄袭约束)
    system_prompt = f"""你是一个中医知识图谱构建助手。
{SCHEMA_DESC}

【输出要求】
1. 请严格输出一个 JSON 列表，列表包含对象，每个对象有 "name" 和 "label" 两个字段。
2. 不要提取纯数字、无意义的短词。
3. 不要输出任何 Markdown 标记或额外解释。
4. 【重要】禁止直接复制示例中的内容（如“张大爷”），除非它们真的出现在了用户的输入文本中。
5. 【重要】只从用户的“当前文本”中提取信息，不要编造。

{few_shot}"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请提取以下文本中的实体：\n{text}"}
    ]
    
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer([prompt], return_tensors="pt").to(device)
    
    try:
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=False, 
                temperature=0.1
            )
        
        response = tokenizer.decode(output[0][len(inputs.input_ids[0]):], skip_special_tokens=True).strip()
        
        # 简单的 JSON 提取逻辑
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]
            
        result = json.loads(json_str)
        if isinstance(result, list):
            return result
        return []
        
    except Exception as e:
        # print(f"Warning: Parse error - {e}")
        return []

# ================= 3. 主流程 (实时写入版) =================

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found.")
        return

    # 1. 读取数据
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except:
            print("Trying JSONL format...")
            f.seek(0)
            data = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(data)} documents. Starting extraction...")
    
    # 2. 准备实时写入
    # 使用 'seen_entities' 集合在内存中进行去重
    seen_entities = set()
    
    # 检查文件是否存在，决定是否写表头（支持断点续传的简单逻辑）
    file_exists = os.path.exists(OUTPUT_CSV)
    
    # 打开 CSV 文件准备写入 (使用 'a' 模式追加)
    with open(OUTPUT_CSV, "a", newline='', encoding='utf-8') as f_out:
        writer = csv.writer(f_out)
        
        # 如果是新文件，写入表头
        if not file_exists or os.path.getsize(OUTPUT_CSV) == 0:
            writer.writerow(["name", "label"])
        else:
            # 如果文件已存在，先读取已有的实体，防止重启脚本时重复写入
            print("Loading existing results to avoid duplicates...")
            with open(OUTPUT_CSV, "r", encoding="utf-8") as f_read:
                reader = csv.reader(f_read)
                next(reader, None) # 跳过表头
                for row in reader:
                    if row: seen_entities.add(row[0])
            print(f"Already extracted: {len(seen_entities)} entities.")

        # 3. 循环处理
        for item in tqdm(data, desc="Extracting"):
            context = item.get("context", "")
            
            # 如果这条数据太短或为空，跳过
            if not context or len(context) < 5:
                continue

            extracted_list = extract_entities_from_text(context)
            
            new_entries_count = 0
            for entity in extracted_list:
                name = entity.get("name", "").strip()
                label = entity.get("label", "").strip()
                
                # 简单的后处理规则：过滤过短的非白名单词
                # (这里保留了你的原始逻辑，但稍微放宽了条件，因为模型有上下文判断会更准)
                if len(name) < 2 and name not in ["肺", "心", "肝", "脾", "肾", "气", "血", "姜", "葱", "蒜", "茶", "酒"]:
                    continue
                
                # 核心去重逻辑：只写入没见过的实体
                if name and label and name not in seen_entities:
                    writer.writerow([name, label])
                    seen_entities.add(name) # 标记为已见
                    new_entries_count += 1
            
            # 【关键】每处理完一条文本，就强制刷新缓冲区，确保写入硬盘
            if new_entries_count > 0:
                f_out.flush()

    print(f"Done! Total unique entities saved: {len(seen_entities)}")

if __name__ == "__main__":
    main()