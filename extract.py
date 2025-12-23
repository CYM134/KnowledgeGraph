import json
import os
import re

import torch
from tqdm import tqdm
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_PATH = "E:\\hF_cache\\Qwen3-4B-Instruct-2507"
INPUT_FILE = "knowledge.json"
OUTPUT_FILE = "extracted.jsonl"

device = "cuda"
print(f"Using device: {device}")

print("Loading tokenizer & model...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    torch_dtype=torch.float16,
    device_map={"": device},
    trust_remote_code=True,
)
print("Model loaded.")


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r"[,，:：、.\\-]{2,}", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_json_robust(text):
    try:
        return json.loads(text)
    except:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass

    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != 0:
            return json.loads(text[start:end])
    except:
        pass
    return None


def post_process_data(data):
    if not data:
        return {"entities": [], "relations": [], "attributes": []}

    for key in ["entities", "relations", "attributes"]:
        if key not in data:
            data[key] = []

    fixed_relations = []
    for rel in data["relations"]:
        if isinstance(rel, list) and len(rel) >= 3:
            fixed_relations.append(rel)
        elif isinstance(rel, str):
            parts = re.split(r"[,，-]\s*", rel)
            if len(parts) >= 3:
                fixed_relations.append([parts[0].strip(), parts[1].strip(), parts[-1].strip()])

    data["relations"] = fixed_relations
    return data


def extract_knowledge(context_text):
    clean_context = clean_text(context_text)

    if len(clean_context) < 5:
        return {"entities": [], "relations": [], "attributes": []}

    few_shot_example = """
示例输入:
"苹果公司由史蒂夫·乔布斯、斯蒂夫·沃兹尼亚克和罗纳德·韦恩在1976年创立，总部位于加利福尼亚州。"
示例输出:
{
    "entities": ["苹果公司", "史蒂夫·乔布斯", "斯蒂夫·沃兹尼亚克", "罗纳德·韦恩", "1976年", "加利福尼亚州"],
    "relations": [
        ["苹果公司", "创始人", "史蒂夫·乔布斯"],
        ["苹果公司", "创始人", "斯蒂夫·沃兹尼亚克"],
        ["苹果公司", "创立时间", "1976年"],
        ["苹果公司", "总部位置", "加利福尼亚州"]
    ],
    "attributes": []
}
"""

    system_prompt = (
        "你是一个严格的知识图谱抽取专家。你的任务是从文本中提取结构化知识。\n"
        "请遵循以下规则：\n"
        "1. 抽取目标：\n"
        "   - entities: 文本中出现的专有名词（人名、地名、机构、书名、核心概念等）。\n"
        "   - relations: 实体之间的关系，格式严格为 [[Subject, Predicate, Object]] 的列表。\n"
        "   - attributes: 实体的属性描述，格式为 [{\"entity\": \"...\", \"attribute\": \"...\", \"value\": \"...\"}]。\n"
        "2. 约束条件：\n"
        "   - 必须忠实于原文，不要编造原文中不存在的信息。\n"
        "   - 实体必须完整（例如“李时珍”不能只写“李”）。\n"
        "   - 如果文本没有包含有效知识，返回空数组。\n"
        "3. 输出格式：\n"
        "   - 仅输出合法的 JSON 字符串，禁止输出 Markdown 代码块（如 ```json），禁止输出任何解释性文字。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{few_shot_example}\n\n现在处理以下文本：\n{clean_context}"},
    ]

    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer([prompt], return_tensors="pt").to(device)

    try:
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=False,
                temperature=0.1,
                repetition_penalty=1.1,
                eos_token_id=tokenizer.eos_token_id,
            )

        generated_tokens = output[0, inputs["input_ids"].shape[1] :].cpu()
        decoded = tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()

        parsed = parse_json_robust(decoded)
        return post_process_data(parsed)

    except Exception as e:
        print(f"Error during extraction: {e}")
        return {"entities": [], "relations": [], "attributes": []}
    finally:
        if device == "mps":
            torch.mps.empty_cache()


def main():
    if not os.path.exists(INPUT_FILE):
        print(f"文件 {INPUT_FILE} 不存在！")
        return

    print("正在读取 JSON 文件...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    print(f"成功加载 {len(dataset)} 条数据。开始抽取...")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
        for item in tqdm(dataset, desc="Extraction", ncols=80):
            extracted = extract_knowledge(item.get("context", ""))

            result = {
                "id": item.get("id"),
                "title": item.get("title", ""),
                "season": item.get("season", ""),
                "context": item.get("context", ""),
                "extracted": extracted,
            }

            f_out.write(json.dumps(result, ensure_ascii=False) + "\n")
            f_out.flush()

    print(f"完成！结果已保存至 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
