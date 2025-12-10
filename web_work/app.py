"""
24节气养生知识图谱问答系统 - 后端服务
提供基于Neo4j的知识图谱查询和问答接口
"""

from flask import Flask, request, jsonify, render_template
from neo4j import GraphDatabase
import re
import os
from typing import List, Dict, Tuple, Any

app = Flask(__name__)

# Neo4j 配置
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://814e73bd.databases.neo4j.io")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "TLv7fqBmh8T4qqqPjIY9FJz4TRPE-CB8H2C66_5TyMc")

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

# 实体类型关键词
ENTITY_KEYWORDS = {
    "节气": SOLAR_TERMS,
    "脏腑": ["心", "肝", "脾", "肺", "肾", "胃", "胆", "小肠", "大肠", "膀胱", "三焦"],
    "饮食": ["茶", "粥", "汤", "药膳", "食疗", "饮食", "进补", "滋补"],
    "疾病": ["咳嗽", "感冒", "腹泻", "便秘", "失眠", "头痛", "风寒", "湿热"],
    "养生": ["养生", "保健", "调理", "导引", "按摩", "针灸", "艾灸", "运动"]
}


def extract_entities(question: str) -> Dict[str, List[str]]:
    """从问句中提取关键实体"""
    entities = {}
    
    # 提取节气
    for term in SOLAR_TERMS:
        if term in question:
            entities.setdefault("节气", []).append(term)
    
    # 提取脏腑
    for organ in ENTITY_KEYWORDS["脏腑"]:
        if organ in question:
            entities.setdefault("脏腑", []).append(organ)
    
    # 提取饮食关键词
    for food in ENTITY_KEYWORDS["饮食"]:
        if food in question:
            entities.setdefault("饮食", []).append(food)
    
    # 提取疾病
    for disease in ENTITY_KEYWORDS["疾病"]:
        if disease in question:
            entities.setdefault("疾病", []).append(disease)
    
    return entities


def classify_intent(question: str, entities: Dict[str, List[str]]) -> str:
    """意图分类"""
    # 饮食养生查询
    if any(kw in question for kw in ["吃", "食", "饮", "喝", "饮食", "食疗"]):
        return "饮食养生"
    
    # 疾病预防/治疗查询
    if any(kw in question for kw in ["病", "症", "治疗", "预防", "缓解", "调理"]) or "疾病" in entities:
        return "疾病预防"
    
    # 养生方法查询
    if any(kw in question for kw in ["养生", "保健", "如何", "怎么", "方法", "注意"]):
        return "养生方法"
    
    # 节气知识查询
    if "节气" in entities or any(kw in question for kw in ["什么是", "介绍", "特点"]):
        return "节气知识"
    
    return "通用查询"


def build_cypher_query(intent: str, entities: Dict[str, List[str]]) -> Tuple[str, str]:
    """根据意图和实体生成Cypher查询"""
    
    # 如果提取到节气,优先查询节气相关信息
    if "节气" in entities and entities["节气"]:
        term = entities["节气"][0]
        
        if intent == "饮食养生":
            cypher = f"""
            MATCH (n)-[r]->(m)
            WHERE (n.name =~ '.*{term}.*' OR m.name =~ '.*{term}.*')
              AND (type(r) =~ '.*饮食.*' OR type(r) =~ '.*食疗.*' OR type(r) =~ '.*进补.*'
                   OR m.name =~ '.*(茶|粥|汤|食|饮).*')
            RETURN n.name as source, type(r) as relation, m.name as target
            LIMIT 10
            """
            description = f"查询【{term}】节气的饮食养生建议"
            
        elif intent == "疾病预防":
            cypher = f"""
            MATCH (n)-[r]->(m)
            WHERE (n.name =~ '.*{term}.*' OR m.name =~ '.*{term}.*')
              AND (type(r) =~ '.*(治疗|预防|缓解|调理).*' OR m.name =~ '.*(病|症).*')
            RETURN n.name as source, type(r) as relation, m.name as target
            LIMIT 10
            """
            description = f"查询【{term}】节气的疾病预防和调理方法"
            
        else:  # 养生方法或通用查询
            cypher = f"""
            MATCH (n)-[r]->(m)
            WHERE n.name =~ '.*{term}.*' OR m.name =~ '.*{term}.*'
            RETURN n.name as source, type(r) as relation, m.name as target
            LIMIT 15
            """
            description = f"查询【{term}】节气的养生知识"
    
    # 如果提取到脏腑
    elif "脏腑" in entities and entities["脏腑"]:
        organ = entities["脏腑"][0]
        cypher = f"""
        MATCH (n)-[r]->(m)
        WHERE n.name =~ '.*{organ}.*' OR m.name =~ '.*{organ}.*'
        RETURN n.name as source, type(r) as relation, m.name as target
        LIMIT 15
        """
        description = f"查询【{organ}】相关的养生知识"
    
    # 如果提取到疾病
    elif "疾病" in entities and entities["疾病"]:
        disease = entities["疾病"][0]
        cypher = f"""
        MATCH (n)-[r]->(m)
        WHERE (n.name =~ '.*{disease}.*' OR m.name =~ '.*{disease}.*')
          AND (type(r) =~ '.*(治疗|预防|缓解|调理).*')
        RETURN n.name as source, type(r) as relation, m.name as target
        LIMIT 10
        """
        description = f"查询【{disease}】的预防和治疗方法"
    
    # 通用查询
    else:
        # 尝试提取问句中的关键词
        keywords = re.findall(r'[\u4e00-\u9fa5]{2,}', question)
        if keywords:
            kw = keywords[0]
            cypher = f"""
            MATCH (n)-[r]->(m)
            WHERE n.name =~ '.*{kw}.*' OR m.name =~ '.*{kw}.*'
            RETURN n.name as source, type(r) as relation, m.name as target
            LIMIT 15
            """
            description = f"查询与【{kw}】相关的知识"
        else:
            # 返回一些随机的养生知识
            cypher = """
            MATCH (n)-[r]->(m)
            WHERE type(r) =~ '.*(养生|功能|作用|调理).*'
            RETURN n.name as source, type(r) as relation, m.name as target
            LIMIT 10
            """
            description = "查询常见养生知识"
    
    return cypher, description


def query_neo4j(cypher: str) -> List[Dict[str, Any]]:
    """执行Neo4j查询"""
    if not driver:
        return []
    
    try:
        with driver.session() as session:
            result = session.run(cypher)
            records = []
            for record in result:
                records.append({
                    "source": record.get("source", ""),
                    "relation": record.get("relation", ""),
                    "target": record.get("target", "")
                })
            return records
    except Exception as e:
        print(f"✗ Neo4j查询错误: {e}")
        return []


def format_answer(records: List[Dict[str, Any]], question: str, intent: str) -> str:
    """将图查询结果格式化为自然语言回答"""
    if not records:
        return "抱歉,暂时没有找到相关的养生知识。您可以尝试询问特定节气的养生方法、饮食建议等。"
    
    # 按关系类型分组
    grouped = {}
    for rec in records:
        rel = rec["relation"]
        grouped.setdefault(rel, []).append(rec)
    
    # 构建回答
    answer_parts = []
    
    if intent == "饮食养生":
        answer_parts.append("根据知识图谱,以下是相关的饮食养生建议:\n")
    elif intent == "疾病预防":
        answer_parts.append("根据知识图谱,以下是相关的疾病预防和调理方法:\n")
    else:
        answer_parts.append("根据知识图谱,为您找到以下养生知识:\n")
    
    # 限制输出条目
    count = 0
    for rel_type, items in list(grouped.items())[:5]:
        if count >= 8:
            break
        answer_parts.append(f"\n【{rel_type}】")
        for item in items[:3]:
            if count >= 8:
                break
            answer_parts.append(f"  • {item['source']} → {item['target']}")
            count += 1
    
    if len(records) > count:
        answer_parts.append(f"\n\n(还有 {len(records) - count} 条相关信息...)")
    
    return "\n".join(answer_parts)


@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/api/ask', methods=['POST'])
def ask():
    """问答接口"""
    data = request.json
    question = data.get('question', '').strip()
    
    if not question:
        return jsonify({"error": "问题不能为空"}), 400
    
    print(f"\n{'='*60}")
    print(f"📝 用户问题: {question}")
    
    # 1. 提取实体
    entities = extract_entities(question)
    print(f"🔍 提取实体: {entities}")
    
    # 2. 意图分类
    intent = classify_intent(question, entities)
    print(f"🎯 意图分类: {intent}")
    
    # 3. 生成Cypher查询
    cypher, description = build_cypher_query(intent, entities)
    print(f"📊 查询描述: {description}")
    print(f"💾 Cypher查询:\n{cypher}")
    
    # 4. 执行查询
    records = query_neo4j(cypher)
    print(f"✓ 查询到 {len(records)} 条结果")
    
    # 5. 输出结构化证据
    print(f"\n{'='*60}")
    print("📋 结构化证据链:")
    if records:
        for i, rec in enumerate(records[:10], 1):
            print(f"  [{i}] {rec['source']} --[{rec['relation']}]--> {rec['target']}")
    else:
        print("  (无结果)")
    print(f"{'='*60}\n")
    
    # 6. 格式化答案
    answer = format_answer(records, question, intent)
    
    return jsonify({
        "question": question,
        "intent": intent,
        "entities": entities,
        "cypher": cypher,
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
