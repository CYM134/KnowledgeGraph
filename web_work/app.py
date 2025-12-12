"""
24节气养生知识图谱问答系统 - 后端服务
提供基于Neo4j的知识图谱查询和问答接口
"""

import csv
import os
from typing import Any, Dict, List, Tuple

from flask import Flask, jsonify, render_template, request
from neo4j import GraphDatabase

app = Flask(__name__)

# Neo4j 配置
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://814e73bd.databases.neo4j.io")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "TLv7fqBmh8T4qqqPjIY9FJz4TRPE-CB8H2C66_5TyMc")

# 数据文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
ENTITY_CSV_PATH = os.path.join(DATA_DIR, "entity_types.csv")
RELATION_CSV_PATH = os.path.join(DATA_DIR, "relations_with_season.csv")

# 本地词表
ENTITY_VOCAB: List[Tuple[str, str]] = []  # [(name, label)]
NAME_TO_LABEL: Dict[str, str] = {}
RELATION_TYPES: List[str] = []

# 初始化Neo4j驱动
try:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    print(f"✓ 成功连接到 Neo4j: {NEO4J_URI}")
except Exception as e:
    print(f"✗ Neo4j连接失败: {e}")
    driver = None

# 24节气列表
SOLAR_TERMS = [
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒"
]

# 实体类型关键词，用于兜底意图识别
ENTITY_KEYWORDS = {
    "节气": SOLAR_TERMS,
    "脏腑": ["心", "肝", "脾", "肺", "肾", "胃", "胆", "小肠", "大肠", "膀胱", "三焦"],
    "饮食": ["茶", "粥", "汤", "药膳", "食疗", "饮食", "进补", "滋补"],
    "疾病": ["咳嗽", "感冒", "腹泻", "便秘", "失眠", "头痛", "风寒", "湿热"],
    "养生": ["养生", "保健", "调理", "导引", "按摩", "针灸", "艾灸", "运动"],
    "作息": ["睡", "睡眠", "失眠", "作息", "休息", "熬夜", "早睡", "晚睡", "午休", "睡好"],
    "情志": ["情绪", "心情", "焦虑", "烦躁", "抑郁", "压力", "情志", "心烦", "烦闷", "放松", "安神"],
    "运动": ["运动", "锻炼", "跑步", "散步", "拉伸", "太极", "八段锦", "气功", "瑜伽", "功法", "体操"],
}


def load_local_lexicon() -> None:
    """加载实体/关系词表，便于问句匹配"""
    global ENTITY_VOCAB, NAME_TO_LABEL, RELATION_TYPES

    if os.path.exists(ENTITY_CSV_PATH):
        seen = set()
        with open(ENTITY_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or "").strip()
                label = (row.get("label") or "Other").strip() or "Other"
                if not name or name in seen:
                    continue
                seen.add(name)
                NAME_TO_LABEL[name] = label
                ENTITY_VOCAB.append((name, label))
        ENTITY_VOCAB.sort(key=lambda x: len(x[0]), reverse=True)
        print(f"✓ 载入实体词表 {len(ENTITY_VOCAB)} 条")
    else:
        print(f"⚠️ 未找到实体词表: {ENTITY_CSV_PATH}")

    if os.path.exists(RELATION_CSV_PATH):
        rels = set()
        with open(RELATION_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rel = (row.get("type") or "").strip()
                if rel:
                    rels.add(rel)
        RELATION_TYPES = sorted(rels, key=lambda x: len(x), reverse=True)
        print(f"✓ 载入关系类型 {len(RELATION_TYPES)} 种")
    else:
        print(f"⚠️ 未找到关系文件: {RELATION_CSV_PATH}")


def extract_entities(question: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """从问句中提取实体，返回{label:[name]}及匹配顺序"""
    entities: Dict[str, List[str]] = {}
    matched: List[str] = []
    text = question.strip()

    for name, label in ENTITY_VOCAB:
        if name and name in text:
            if name in matched:
                continue
            matched.append(name)
            entities.setdefault(label, []).append(name)
            # 避免一次匹配过多，按长度优先
            if len(matched) >= 12:
                break

    # 补充节气词
    for term in SOLAR_TERMS:
        if term in text and term not in matched:
            matched.append(term)
            entities.setdefault("SolarTerm", []).append(term)

    # 兜底关键词，辅助意图判断
    for group, kws in ENTITY_KEYWORDS.items():
        for kw in kws:
            if kw in text and kw not in matched:
                matched.append(kw)
                entities.setdefault(group, []).append(kw)

    return entities, matched


def classify_intent(question: str, entities: Dict[str, List[str]], matched: List[str]) -> str:
    """意图分类 - 优先识别节气，再根据关键词确定具体意图"""
    q = question
    has_food = "FoodHerb" in entities or "饮食" in entities
    has_disease = "DiseaseSymptom" in entities or "疾病" in entities
    has_season = "SolarTerm" in entities or "节气" in entities
    has_sleep = "SleepDisorder" in entities or "作息" in entities
    has_emotion = "Emotion" in entities or "情志" in entities
    has_exercise = "Exercise" in entities or "运动" in entities
    relation_words = ["关系", "联系", "关联", "区别", "路径"]

    # 如果用户明确要求关系路径，直接返回
    if any(w in q for w in relation_words) and len(matched) >= 2:
        return "关系路径"
    
    # 如果有节气，优先判断具体意图
    if has_season:
        if has_food or any(kw in q for kw in ["吃", "食", "饮", "忌", "补", "膳", "菜", "药膳", "食疗"]):
            return "饮食养生"
        if has_sleep or any(kw in q for kw in ["睡", "失眠", "作息", "休息", "熬夜", "早睡", "晚睡", "午休"]):
            return "起居作息"
        if has_emotion or any(kw in q for kw in ["情绪", "心情", "焦虑", "烦躁", "抑郁", "压力", "情志", "心烦", "烦闷", "放松"]):
            return "情志调理"
        if has_exercise or any(kw in q for kw in ["运动", "锻炼", "跑步", "散步", "拉伸", "太极", "八段锦", "气功", "瑜伽", "功法"]):
            return "运动调理"
        if has_disease or any(kw in q for kw in ["病", "症", "治疗", "预防", "缓解"]):
            return "疾病调理"
        # 节气相关的养生问题
        if any(kw in q for kw in ["养生", "保健", "方法", "注意", "宜", "忌", "如何", "怎么", "适合", "事项"]):
            return "节气养生"
        # 默认也是节气养生
        return "节气养生"
    
    # 无节气时的分类
    if has_food or any(kw in q for kw in ["吃", "食", "饮", "忌", "补", "膳", "菜", "药膳", "食疗"]):
        return "饮食养生"
    if has_sleep or any(kw in q for kw in ["睡", "睡眠", "休息", "早睡", "晚睡", "午休", "规律", "调整", "起居"]):
        return "起居作息"
    if has_emotion or any(kw in q for kw in ["情绪", "心情", "焦虑", "烦躁", "抑郁", "压力", "情志", "心烦", "烦闷", "放松"]):
        return "情志调理"
    if has_exercise or any(kw in q for kw in ["运动", "锻炼", "跑步", "散步", "拉伸", "太极", "八段锦", "气功", "瑜伽", "功法"]):
        return "运动调理"
    if has_disease or any(kw in q for kw in ["病", "症", "治疗", "预防", "调理", "缓解"]):
        return "疾病调理"
    if len(matched) >= 2:
        return "关系路径"
    if any(kw in q for kw in ["养生", "保健", "方法", "注意"]):
        return "节气养生"
    return "通用查询"


def get_rel_keywords(intent: str) -> List[str]:
    """根据意图给出需要优先关注的关系关键词"""
    if intent == "饮食养生":
        return ["宜食", "忌食", "饮", "食", "补", "汤", "茶", "粥", "药膳", "食疗"]
    if intent == "疾病调理":
        return ["预防", "治疗", "缓解", "调理", "对应症状", "导致", "可能导致", "禁忌"]
    if intent == "节气养生":
        return ["养生", "保健", "功效", "宜", "忌", "导引", "功法", "方法", "注意", "对应时节"]
    if intent == "起居作息":
        return ["作息", "睡眠", "休息", "早睡", "熬夜", "规律", "调整", "起居"]
    if intent == "情志调理":
        return ["情志", "情绪", "心神", "安神", "静心", "舒缓", "放松"]
    if intent == "运动调理":
        return ["运动", "锻炼", "功法", "太极", "八段锦", "拉伸", "散步", "体操", "瑜伽"]
    return ["养生", "功效", "宜", "忌", "调理", "导引"]


def build_neighbor_query(
    focus: str, season: str, rel_keywords: List[str], limit: int = 30
) -> Tuple[str, Dict[str, Any], str]:
    """围绕单个实体的邻居查询"""
    cypher = """
    MATCH (n {name: $name})-[r]-(m)
    WHERE ($season IS NULL OR r.season = $season OR m.name CONTAINS $season OR n.name CONTAINS $season)
      AND ($rel_keywords = [] OR any(kw IN $rel_keywords WHERE coalesce(r.type, '') CONTAINS kw OR m.name CONTAINS kw))
    RETURN DISTINCT
      CASE WHEN startNode(r)=n THEN n.name ELSE m.name END AS source,
      coalesce(r.type, type(r)) AS relation,
      CASE WHEN startNode(r)=n THEN m.name ELSE n.name END AS target,
      coalesce(r.season, '') AS season
    ORDER BY CASE WHEN $season IS NOT NULL AND season = $season THEN 0 ELSE 1 END, relation, target
    LIMIT $limit
    """
    params = {
        "name": focus,
        "season": season,
        "rel_keywords": rel_keywords or [],
        "limit": limit,
    }
    desc = f"查询【{focus}】的关联知识"
    if season and season not in focus:
        desc += f" (优先节气 {season})"
    return cypher, params, desc


def build_path_query(src: str, tgt: str, limit: int = 40) -> Tuple[str, Dict[str, Any], str]:
    """两实体最短路径查询"""
    cypher = """
    MATCH (a {name:$src}), (b {name:$tgt})
    MATCH p = shortestPath((a)-[*..4]-(b))
    UNWIND range(0, size(relationships(p))-1) AS idx
    WITH nodes(p)[idx] AS s, relationships(p)[idx] AS r, nodes(p)[idx+1] AS t
    RETURN s.name AS source, coalesce(r.type, type(r)) AS relation, t.name AS target, coalesce(r.season, '') AS season
    LIMIT $limit
    """
    params = {"src": src, "tgt": tgt, "limit": limit}
    desc = f"查询【{src}】与【{tgt}】之间的关联路径"
    return cypher, params, desc


def build_general_query(
    season: str, rel_keywords: List[str], limit: int = 30
) -> Tuple[str, Dict[str, Any], str]:
    """无明确实体时，给出节气养生知识"""
    cypher = """
    MATCH (n)-[r]->(m)
    WHERE ($season IS NULL OR r.season = $season OR n.name CONTAINS $season OR m.name CONTAINS $season)
      AND ($rel_keywords = [] OR any(kw IN $rel_keywords WHERE coalesce(r.type, '') CONTAINS kw OR m.name CONTAINS kw))
    RETURN n.name AS source, coalesce(r.type, type(r)) AS relation, m.name AS target, coalesce(r.season, '') AS season
    ORDER BY CASE WHEN $season IS NOT NULL AND season = $season THEN 0 ELSE 1 END, relation, target
    LIMIT $limit
    """
    params = {"season": season, "rel_keywords": rel_keywords or [], "limit": limit}
    desc = "查询常见养生知识"
    if season:
        desc = f"查询与【{season}】相关的养生知识"
    return cypher, params, desc


def build_cypher_query(
    question: str, intent: str, entities: Dict[str, List[str]], matched: List[str]
) -> Tuple[str, Dict[str, Any], str]:
    """根据意图和实体生成Cypher查询"""
    # 优先使用节气作为季节过滤
    season_list = entities.get("SolarTerm") or entities.get("节气") or []
    season = season_list[0] if season_list else None
    rel_keywords = get_rel_keywords(intent)

    distinct_entities = []
    for name in matched:
        if name not in distinct_entities:
            distinct_entities.append(name)

    if intent == "关系路径" and len(distinct_entities) >= 2:
        return build_path_query(distinct_entities[0], distinct_entities[1])

    if distinct_entities:
        focus = season or distinct_entities[0]
        return build_neighbor_query(focus, season, rel_keywords)

    return build_general_query(season, rel_keywords)


# 预加载实体/关系词表，便于后续匹配
load_local_lexicon()


def query_neo4j(cypher: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """执行Neo4j查询"""
    if not driver:
        return []

    try:
        with driver.session() as session:
            result = session.run(cypher, parameters=params or {})
            records = []
            for record in result:
                records.append(
                    {
                        "source": record.get("source", "") or "",
                        "relation": record.get("relation", "") or "",
                        "target": record.get("target", "") or "",
                        "season": record.get("season", "") or "",
                    }
                )
            return records
    except Exception as e:
        print(f"✗ Neo4j查询错误: {e}")
        return []


def format_answer(
    records: List[Dict[str, Any]],
    intent: str,
    matched: List[str],
    season: str,
    rel_keywords: List[str],
) -> str:
    """将图查询结果格式化为自然语言回答"""
    if not records:
        suggestions = []
        if season:
            suggestions.append(f"尝试改问“{season} + 具体食材/功法/症状”，例如：'{season}宜吃什么？'")
        if matched:
            suggestions.append("也可以换一个更具体的实体名称或疾病症状再问。")
        tips = "；".join(suggestions) or "请尝试指定节气、食材或症状再问一次。"
        return f"抱歉，没有直接查到结果。{tips}"

    # 抽取并分类记录中的目标项以便生成流畅语句
    positives: List[str] = []
    negatives: List[str] = []
    methods: List[str] = []
    effects: List[str] = []
    others: List[str] = []

    food_hints = ["汤", "粥", "菜", "芽", "肉", "鱼", "蛋", "粉", "饼", "卷", "豆", "食", "果", "青菜", "韭"]
    method_hints = ["锻炼", "运动", "导引", "保健", "养生", "按摩", "功法", "起居", "注意"]

    def add_unique(lst: List[str], v: str):
        v = v.strip()
        if not v:
            return
        if v not in lst:
            lst.append(v)

    for rec in records:
        rel = (rec.get("relation") or "").strip()
        tgt = (rec.get("target") or "").strip()
        src = (rec.get("source") or "").strip()

        # 优先判断 relation 中的提示词
        if any(k in rel for k in ["宜食", "宜", "适宜", "宜吃"]):
            add_unique(positives, tgt)
            continue
        if any(k in rel for k in ["忌食", "忌", "不宜"]):
            add_unique(negatives, tgt)
            continue
        if any(k in rel for k in ["预防", "治疗", "缓解", "调理", "预防中暑"]):
            add_unique(effects, tgt)
            continue
        if any(k in rel for k in method_hints):
            add_unique(methods, tgt if tgt else rel)
            continue

        # 否则通过 target 名判断是否可能为食物或方法
        if any(h in tgt for h in food_hints):
            add_unique(positives, tgt)
            continue
        if any(h in tgt for h in method_hints):
            add_unique(methods, tgt)
            continue

        # 如果 relation 含导致/引起等，视为不良影响
        if any(k in rel for k in ["导致", "引起", "可致", "易引起"]):
            add_unique(effects, tgt)
            continue

        add_unique(others, tgt or rel)

    # 识别季节标签
    season_label = season or (records[0].get("season") or "")
    if season_label:
        season_prefix = f"{season_label}时节"
    else:
        season_prefix = "该时节"

    # 根据意图生成更自然的回答
    if intent == "节气养生":
        parts: List[str] = []
        # 饮食建议
        if positives:
            parts.append(f"{season_prefix}宜食：{ '、'.join(positives[:15]) }。")
            parts.append(f"食材注意点：注重清淡、应季，{season_prefix}可优先考虑上述食材搭配。")
        # 忌口
        if negatives:
            parts.append(f"{season_prefix}不宜：{ '、'.join(negatives[:15]) }。")
            parts.append("忌口提示：辛辣油腻或寒凉食物宜酌情减少，结合体质调整。")
        # 方法建议
        if methods:
            parts.append(f"建议注重：{ '、'.join(methods[:10]) }，以调摄身心。")
            parts.append("实践小贴士：每日择一两项坚持执行，配合充足睡眠更佳。")
        # 不良影响或注意事项
        if effects:
            parts.append(f"需注意：可能与{ '、'.join(effects[:10]) }相关，出现不适应及时就医或调理。")
            parts.append("观察反馈：若出现明显不适，请暂停尝试并咨询专业人士。")

        if not parts:
            # 兜底：列出几个关键条目，但用完整句子
            sample = (positives + methods + others)[:8]
            if sample:
                return f"{season_prefix}相关建议：{ '、'.join(sample) }。"
            return f"抱歉，未能找到明确的{season_prefix}养生建议。"

        header = f"{season_label}养生要点：" if season_label else "养生要点："
        return header + "\n" + "\n".join(parts)

    if intent == "饮食养生":
        parts = []
        if positives:
            parts.append(f"宜食：{ '、'.join(positives[:20]) }。")
            parts.append("搭配建议：主粮+优质蛋白+时令蔬果，少油少盐，温热适口。")
        if negatives:
            parts.append(f"忌食：{ '、'.join(negatives[:20]) }。")
            parts.append("若体质偏寒或脾胃虚弱，可进一步减少生冷或过辣食物。")
        if methods:
            parts.append(f"搭配建议：{ '、'.join(methods[:8]) }。")
            parts.append("实用提示：少量多餐、细嚼慢咽，避免过饱过快。")
        if parts:
            lead = f"关于{season_label}的饮食建议：" if season_label else "饮食建议："
            return lead + "\n" + "\n".join(parts)
        # 兜底
        sample = (positives + others)[:10]
        if sample:
            return f"建议：{ '、'.join(sample) }。"
        return "抱歉，未找到明确的饮食建议。"

    if intent == "起居作息":
        parts = []
        if methods:
            parts.append(f"作息调整建议：{ '、'.join(methods[:10]) }。")
            parts.append("节奏提示：固定起卧时间，避免大幅度熬夜，午休不宜过久。")
        if effects:
            parts.append(f"需要关注的风险/症状：{ '、'.join(effects[:8]) }，出现不适建议及时休息或就医。")
            parts.append("监测建议：若持续乏力或头痛，可适当减少刺激性饮品并增加水分。")
        if positives:
            parts.append(f"可辅助的食疗/用物：{ '、'.join(positives[:10]) }。")
            parts.append("食疗小贴士：睡前少量温水或安神茶饮，避免过饱过饿。")
        if negatives:
            parts.append(f"不宜：{ '、'.join(negatives[:8]) }。")
            parts.append("环境提示：睡前减少电子屏幕蓝光，保持卧室安静、温度适宜。")
        if parts:
            lead = f"{season_prefix}作息调养提示：" if season_label else "作息调养提示："
            return lead + "\n" + "\n".join(parts)
        return "抱歉，未找到明确的作息调养建议。"

    if intent == "情志调理":
        parts = []
        if methods:
            parts.append(f"舒缓情绪的方法：{ '、'.join(methods[:10]) }。")
            parts.append("实践建议：每日留出10-20分钟做放松练习或深呼吸。")
        if effects:
            parts.append(f"需留意的情绪关联/风险：{ '、'.join(effects[:8]) }。")
            parts.append("若情绪持续低落或影响睡眠，建议寻求专业心理支持。")
        if positives:
            parts.append(f"可辅助安神的食材/方式：{ '、'.join(positives[:10]) }。")
            parts.append("饮食搭配：清淡少刺激，晚间避免咖啡因与过甜食品。")
        if parts:
            lead = f"{season_prefix}情志调理建议：" if season_label else "情志调理建议："
            return lead + "\n" + "\n".join(parts)
        return "抱歉，未找到明确的情志调理建议。"

    if intent == "运动调理":
        parts = []
        if methods:
            parts.append(f"推荐的运动/功法：{ '、'.join(methods[:10]) }。")
            parts.append("执行要点：循序渐进，先热身再发力，运动后适度拉伸。")
        if effects:
            parts.append(f"运动时需留意：{ '、'.join(effects[:8]) }，循序渐进避免过量。")
            parts.append("安全提醒：如有不适（胸闷、头晕、心悸），立即停止并评估体力。")
        if positives:
            parts.append(f"可配合的食疗/补充：{ '、'.join(positives[:10]) }。")
            parts.append("能量补给：运动前后补充温水，适量碳水与优质蛋白。")
        if negatives:
            parts.append(f"不建议的搭配或动作：{ '、'.join(negatives[:8]) }。")
            parts.append("避免事项：高温时段不宜剧烈运动，空腹或过饱状态下谨慎训练。")
        if parts:
            lead = f"{season_prefix}运动调理要点：" if season_label else "运动调理要点："
            return lead + "\n" + "\n".join(parts)
        return "抱歉，未找到明确的运动调理建议。"

    if intent == "疾病调理":
        parts = []
        if effects:
            parts.append(f"在{season_label}，可能相关的症状/风险有：{ '、'.join(effects[:10]) }。")
        if methods:
            parts.append(f"建议采取的调理方法包括：{ '、'.join(methods[:8]) }。")
        if positives:
            parts.append(f"可能的病症原因：{ '、'.join(positives[:12]) }。")
        if parts:
            header = f"{season_label}疾病预防与调理建议：" if season_label else "疾病预防与调理建议："
            return header + "\n" + "\n".join(parts)
        return "抱歉，未找到明确的疾病调理建议。"

    # 关系路径或通用意图仍用简洁路径或要点列表
    if intent == "关系路径" and len(matched) >= 2:
        parts = [f"{matched[0]} 与 {matched[1]} 的关联路径："]
        for idx, rec in enumerate(records, 1):
            season = f"（节气：{rec.get('season','')}）" if rec.get('season') else ""
            parts.append(f"{idx}. {rec.get('source','')} --{rec.get('relation','')}--> {rec.get('target','')}{season}")
        return "\n".join(parts)

    # 通用列举（保留之前的要点风格，但更友好）
    header = "关联知识要点："
    lines = [header]
    seen = set()
    for r in records[:8]:
        src = r.get('source','')
        rel = r.get('relation','')
        tgt = r.get('target','')
        key = f"{src}|{rel}|{tgt}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {src} {rel} {tgt}")
    if len(records) > 8:
        lines.append(f"… 还有 {len(records) - 8} 条关联可继续查看。")
    return "\n".join(lines)


@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/api/ask', methods=['POST'])
def ask():
    """问答接口"""
    data = request.json or {}
    question = data.get('question', '').strip()

    if not question:
        return jsonify({"error": "问题不能为空"}), 400

    print(f"\n{'='*60}")
    print(f"📝 用户问题: {question}")

    # 1. 提取实体
    entities, matched = extract_entities(question)
    print(f"🔍 提取实体: {matched}")
    print(f"   实体映射: {entities}")

    # 2. 意图分类
    intent = classify_intent(question, entities, matched)
    print(f"🎯 意图分类: {intent}")

    # 2.5 额外上下文
    season_list = entities.get("SolarTerm") or entities.get("节气") or []
    season = season_list[0] if season_list else None
    rel_keywords = get_rel_keywords(intent)

    # 3. 生成Cypher查询
    cypher, params, description = build_cypher_query(question, intent, entities, matched)
    print(f"📊 查询描述: {description}")
    print(f"💾 Cypher查询:\n{cypher}")
    print(f"🔧 查询参数: {params}")

    # 4. 执行查询
    records = query_neo4j(cypher, params)
    print(f"✓ 查询到 {len(records)} 条结果")

    # 如果是关系路径但未命中，回退到邻居查询
    if intent == "关系路径" and not records and matched:
        season_list = entities.get("SolarTerm") or entities.get("节气") or []
        season = season_list[0] if season_list else None
        rel_keywords = get_rel_keywords("节气养生")
        fallback_cypher, fallback_params, fallback_desc = build_neighbor_query(
            matched[0],
            season,
            get_rel_keywords("节气养生"),
        )
        print("⚠️ 未找到路径，改为邻居查询")
        print(f"📊 回退描述: {fallback_desc}")
        print(f"💾 回退Cypher:\n{fallback_cypher}")
        print(f"🔧 回退参数: {fallback_params}")
        cypher, params, description = fallback_cypher, fallback_params, fallback_desc
        records = query_neo4j(cypher, params)
        print(f"✓ 回退后查询到 {len(records)} 条结果")

    # 5. 输出结构化证据
    print(f"\n{'='*60}")
    print("📋 结构化证据链:")
    if records:
        for i, rec in enumerate(records[:10], 1):
            print(f"  [{i}] {rec['source']} --[{rec['relation']}]--> {rec['target']} (季节:{rec.get('season','')})")
    else:
        print("  (无结果)")
    print(f"{'='*60}\n")
    
    # 6. 格式化答案
    answer = format_answer(records, intent, matched, season, rel_keywords)

    return jsonify({
        "question": question,
        "intent": intent,
        "entities": entities,
        "matched_entities": matched,
        "season": season,
        "cypher": cypher,
        "params": params,
        "description": description,
        "evidence_count": len(records),
        "answer": answer
    })


@app.route('/api/health', methods=['GET'])
def health():
    """健康检查"""
    neo4j_ok = False
    if driver:
        try:
            with driver.session() as session:
                result = session.run("RETURN 1")
                neo4j_ok = result.single() is not None
        except:
            pass
    
    return jsonify({
        "status": "ok" if neo4j_ok else "neo4j_disconnected",
        "neo4j": neo4j_ok
    })


if __name__ == '__main__':
    print("\n" + "="*60)
    print("🌿 24节气养生知识图谱问答系统")
    print("="*60)
    print(f"Neo4j URI: {NEO4J_URI}")
    print(f"Neo4j User: {NEO4J_USER}")
    print("="*60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
