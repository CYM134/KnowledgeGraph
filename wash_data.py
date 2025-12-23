import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, Set, Tuple

SOLAR_TERMS = {
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
}

PERSON_RELATIONS = {
    "作者", "撰写", "参与", "参与研究", "主讲人", "提出", "提出者",
}

CREATION_RELATIONS = {"创建者", "创编", "创作", "发明"}

SOURCE_RELATIONS = {
    "刊载", "发表期刊", "发表地点", "出版", "发布平台", "刊发内容", "出版周期", "出版时间",
}

SEASON_KEYWORDS = {"春季", "夏季", "秋季", "冬季", "春天", "夏天", "秋天", "冬天", "季节", "时节"}

TECHNIQUE_KEYWORDS = {
    "导引", "功法", "气功", "坐功", "行功", "拳", "式", "八段锦", "导引术", "养生法", "功图", "功势", "太极",
}

FOOD_KEYWORDS = {
    "汤", "粥", "茶", "酒", "菜", "果", "瓜", "豆", "米", "饭", "面", "肉", "鱼", "鸡", "鸭", "蜂蜜", "枣", "粥",
}

DISEASE_KEYWORDS = {"病", "症", "炎", "癌", "中暑", "感冒", "高血压", "哮喘"}

BODY_KEYWORDS = {"心脏", "心", "肝", "脾", "胃", "肺", "肠", "头", "手", "足", "腰", "背", "鼻", "咽", "喉", "胸", "腹", "膝", "骨", "经", "穴", "脉"}

ORG_KEYWORDS = {"大学", "学院", "医院", "研究所", "中心", "机构", "委员会", "杂志社", "出版社", "临床", "附属", "实验室", "公司", "平台", "部门", "科"}

SOURCE_KEYWORDS = {"杂志", "期刊", "报", "出版社", "出版", "刊"}

LOCATION_KEYWORDS = {"市", "省", "区", "县", "镇", "村", "洲", "湾", "岭"}
LOCATION_HINTS = {
    "北京", "上海", "广州", "南京", "长春", "武汉", "成都", "中国", "广东", "江苏", "黑龙江",
    "青藏高原", "珠江三角洲", "华南", "华北", "江南", "岭南",
}

CHINESE_SURNAMES = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑裴陆荣翁荀羊於惠甄魏家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘斜厉戎祖武符刘姜")

NodeLabelCounter = Dict[str, Counter]
Relation = Tuple[str, str, str]


def sanitize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    return name.replace("《", "").replace("》", "").strip()


def contains_any(text: str, keywords: Set[str]) -> bool:
    return any(k in text for k in keywords)


def is_solar_term(name: str) -> bool:
    return name in SOLAR_TERMS or any(term in name for term in SOLAR_TERMS) or "节气" in name or name.endswith("时节")


def is_probable_person(name: str) -> bool:
    if not re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", name):
        return False
    if name[0] not in CHINESE_SURNAMES:
        return False
    non_person_tokens = {"气", "经", "穴", "病", "症", "血", "雨", "雪", "风", "节", "季"}
    if contains_any(name, non_person_tokens):
        return False
    return True


def infer_label(name: str, relation_type: str, is_subject: bool) -> str:
    relation_type = relation_type or ""
    clean_name = sanitize_name(name)
    if not clean_name:
        return "Entity"

    if relation_type in CREATION_RELATIONS:
        return "Technique" if is_subject else "Person"
    if relation_type in PERSON_RELATIONS and is_subject:
        return "Person"
    if relation_type in SOURCE_RELATIONS or contains_any(relation_type, SOURCE_KEYWORDS):
        return "Source"

    if is_solar_term(clean_name):
        return "SolarTerm"
    if contains_any(clean_name, SEASON_KEYWORDS):
        return "Season"
    if contains_any(clean_name, TECHNIQUE_KEYWORDS) or clean_name.endswith("式"):
        return "Technique"
    if contains_any(clean_name, DISEASE_KEYWORDS):
        return "Disease"
    if contains_any(clean_name, BODY_KEYWORDS):
        return "BodyPart"
    if contains_any(clean_name, FOOD_KEYWORDS):
        return "Food"
    if contains_any(clean_name, SOURCE_KEYWORDS):
        return "Source"
    if contains_any(clean_name, ORG_KEYWORDS):
        return "Organization"
    if contains_any(clean_name, LOCATION_KEYWORDS) or contains_any(clean_name, LOCATION_HINTS):
        return "Location"
    if is_probable_person(clean_name):
        return "Person"

    return "Entity"


def load_jsonl(path: str) -> Iterable[dict]:
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                print(f"跳过无法解析的行: {line_no}")


def collect_graph(
    records: Iterable[dict],
    max_name_length: int,
) -> Tuple[NodeLabelCounter, Set[Relation]]:
    node_labels: NodeLabelCounter = defaultdict(Counter)
    relations: Set[Relation] = set()

    for entry in records:
        kg = entry.get("kg_data") or {}

        for ent in kg.get("entities") or []:
            cleaned = sanitize_name(ent)
            if cleaned and len(cleaned) <= max_name_length:
                node_labels[cleaned][infer_label(cleaned, "", False)] += 1

        for rel in kg.get("relations") or []:
            if not isinstance(rel, list) or len(rel) < 3:
                continue

            subj_name = sanitize_name(rel[0])
            pred = sanitize_name(rel[1])
            obj_name = sanitize_name(rel[2])

            if not subj_name or not obj_name or not pred:
                continue
            if len(subj_name) > max_name_length or len(obj_name) > max_name_length:
                continue

            node_labels[subj_name][infer_label(subj_name, pred, True)] += 1
            node_labels[obj_name][infer_label(obj_name, pred, False)] += 1
            relations.add((subj_name, obj_name, pred))

    return node_labels, relations


def resolve_labels(node_labels: NodeLabelCounter) -> Dict[str, str]:
    resolved = {}
    for name, votes in node_labels.items():
        resolved[name] = votes.most_common(1)[0][0] if votes else "Entity"
    return resolved


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def write_nodes(path: str, nodes: Dict[str, str]) -> None:
    ensure_parent_dir(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "label"])
        for name in sorted(nodes.keys()):
            writer.writerow([name, nodes[name]])


def write_relations(path: str, relations: Set[Relation]) -> None:
    ensure_parent_dir(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target", "type"])
        for subj, obj, pred in sorted(relations):
            writer.writerow([subj, obj, pred])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将清洗后的 JSONL 转为图谱 CSV")
    parser.add_argument(
        "--input",
        default="cleaning_results_v2/kg_final_passed.jsonl",
        help="清洗后的 JSONL 文件路径",
    )
    parser.add_argument(
        "--nodes-output",
        default="nodes.csv",
        help="生成的节点 CSV 输出路径",
    )
    parser.add_argument(
        "--relations-output",
        default="relations.csv",
        help="生成的关系 CSV 输出路径",
    )
    parser.add_argument(
        "--max-name-length",
        type=int,
        default=32,
        help="超过该长度的实体将被视为噪声而跳过",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.exists(args.input):
        print(f"未找到输入文件: {args.input}")
        return

    records = load_jsonl(args.input)
    node_labels, relations = collect_graph(records, args.max_name_length)
    nodes = resolve_labels(node_labels)

    write_nodes(args.nodes_output, nodes)
    write_relations(args.relations_output, relations)

    print(
        f"处理完成：生成 {args.nodes_output} ({len(nodes)} 个节点) "
        f"和 {args.relations_output} ({len(relations)} 条关系)"
    )


if __name__ == "__main__":
    main()
