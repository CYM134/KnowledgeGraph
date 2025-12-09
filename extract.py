import json
import re
import torch
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModelForCausalLM

MODEL_PATH = "/Users/oyzh/KnowledgeGraph/models/Qwen3-4B-Instruct-2507"

device = "mps" if torch.backends.mps.is_available() else "cpu"
print("Using device:", device)

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    torch_dtype=torch.float16,
    device_map={"": device},
    trust_remote_code=True
)

def extract_knowledge(context_text):
    # 构造 messages 列表
    messages = [
        {"role": "system", "content":
            "你是一个严格的知识图谱抽取模型。你的唯一任务是从文本中抽取实体、关系、属性。"
            " 输出必须是严格合法 JSON，格式为 {\"entities\": [], \"relations\": [], \"attributes\": []}。"
            " 不允许输出任何额外说明、Markdown、代码框、解释。如果没有内容就输出空数组。"},
        {"role": "user", "content":
            "请从下面文本中抽取知识（实体 + 关系 + 属性）：\n\n" + context_text}
    ]

    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    inputs = tokenizer([prompt], return_tensors="pt").to(device)

    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=1024,
            do_sample=False,
            repetition_penalty=1.2,
            eos_token_id=tokenizer.eos_token_id
        )

    # 仅解码新生成的 tokens，避免把 prompt 也解码出来导致解析失败
    generated_tokens = output[0, inputs["input_ids"].shape[1]:].cpu()
    decoded = tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()

    # DEBUG 输出 raw
    print("\n----- RAW OUTPUT -----\n", decoded, "\n-----------------------\n")

    # 提取 JSON
    try:
        json_start = decoded.index("{")
        json_end = decoded.rindex("}") + 1
        json_str = decoded[json_start:json_end]
        parsed = json.loads(json_str)
        return parsed
    except Exception:
        # 再尝试用正则提取
        match = re.search(r"\{[\s\S]*\}", decoded)
        if match:
            candidate = match.group(0)
            try:
                return json.loads(candidate)
            except Exception:
                pass
        # 若解析失败，返回空结构
        return {"entities": [], "relations": [], "attributes": []}


def main():
    with open("knowledge.json", "r", encoding="utf-8") as f:
        dataset = json.load(f)

    output_file = open("extracted.jsonl", "w", encoding="utf-8")

    print("开始抽取知识...")

    for item in tqdm(dataset, desc="Processing", ncols=80):
        extracted = extract_knowledge(item["context"])
        result = {
            "id": item["id"],
            "title": item.get("title", ""),
            "season": item.get("season", ""),
            "context": item["context"],
            "extracted": extracted
        }
        output_file.write(json.dumps(result, ensure_ascii=False) + "\n")
        output_file.flush()

    output_file.close()
    print("抽取完成，结果保存在 extracted.jsonl")


if __name__ == "__main__":
    main()
