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
    """意图分类"""
    q = question
    has_food = "FoodHerb" in entities or "饮食" in entities
    has_disease = "DiseaseSymptom" in entities or "疾病" in entities
    has_season = "SolarTerm" in entities or "节气" in entities
    relation_words = ["关系", "联系", "关联", "区别", "路径"]

    if len(matched) >= 2 and any(w in q for w in relation_words):
        return "关系路径"
    if has_food or any(kw in q for kw in ["吃", "食", "饮", "忌", "补", "膳", "菜", "药膳", "食疗"]):
        return "饮食养生"
    if has_disease or any(kw in q for kw in ["病", "症", "治疗", "预防", "调理", "缓解"]):
        return "疾病调理"
    if len(matched) >= 2 and not has_food and not has_disease:
        return "关系路径"
    if has_season or any(kw in q for kw in ["养生", "保健", "方法", "注意"]):
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
    records: List[Dict[str, Any]], question: str, intent: str, matched: List[str]
) -> str:
    """将图查询结果格式化为自然语言回答"""
    if not records:
        return "抱歉，没有直接查到结果。请尝试更换关键词，例如指定节气或具体功法/食材。"

    if intent == "关系路径" and len(matched) >= 2:
        parts = [f"{matched[0]} 与 {matched[1]} 的关联路径:"]
        for idx, rec in enumerate(records, 1):
            season = f" (节气: {rec['season']})" if rec.get("season") else ""
            parts.append(f"{idx}. {rec['source']} --{rec['relation']}--> {rec['target']}{season}")
        return "\n".join(parts)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        rel = rec.get("relation") or "关联"
        grouped.setdefault(rel, []).append(rec)

    if intent == "饮食养生":
        header = "为您找到与饮食养生相关的图谱证据："
    elif intent == "疾病调理":
        header = "为您找到与疾病预防/调理相关的图谱证据："
    elif intent == "节气养生":
        header = "为您找到节气养生相关的图谱证据："
    else:
        header = "根据知识图谱，为您整理出以下关联信息："

    lines = [header]
    count = 0
    for rel_type, items in list(grouped.items())[:6]:
        if count >= 12:
            break
        lines.append(f"\n【{rel_type}】")
        for item in items[:3]:
            if count >= 12:
                break
            season = f" (节气: {item['season']})" if item.get("season") else ""
            lines.append(f"- {item['source']} → {item['target']}{season}")
            count += 1

    if len(records) > count:
        lines.append(f"\n… 还有 {len(records) - count} 条关联可继续探索。")

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
    answer = format_answer(records, question, intent, matched)

    return jsonify({
        "question": question,
        "intent": intent,
        "entities": entities,
        "matched_entities": matched,
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
