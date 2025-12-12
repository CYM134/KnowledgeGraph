"""
将 entity_types.csv 和 relations_with_season.csv 导入到 Neo4j 数据库。

依赖：pip install neo4j
"""

import argparse
import csv
import os
from typing import Dict, List, Tuple

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable


def load_entities(csv_path: str) -> List[Tuple[str, str]]:
    """加载实体数据：(name, label)"""
    entities = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row['name'].strip()
            label = row['label'].strip()
            if name and label:
                entities.append((name, label))
    return entities


def load_relations(csv_path: str) -> List[Dict[str, str]]:
    """加载关系数据：{source, target, type, season}"""
    relations = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            source = row['source'].strip()
            target = row['target'].strip()
            rel_type = row['type'].strip()
            season = row['season'].strip()
            if source and target and rel_type:
                relations.append({
                    'source': source,
                    'target': target,
                    'type': rel_type,
                    'season': season
                })
    return relations


def create_entities(session, entities: List[Tuple[str, str]], batch_size: int = 500) -> None:
    """批量创建实体节点"""
    print(f"开始导入 {len(entities)} 个实体节点...")
    
    # 按标签分组
    label_groups: Dict[str, List[str]] = {}
    for name, label in entities:
        if label not in label_groups:
            label_groups[label] = []
        label_groups[label].append(name)
    
    total = 0
    for label, names in label_groups.items():
        print(f"  导入标签 '{label}': {len(names)} 个节点")
        for i in range(0, len(names), batch_size):
            batch = names[i:i + batch_size]
            query = f"""
            UNWIND $names AS name
            MERGE (n:{label} {{name: name}})
            """
            session.run(query, names=batch)
            total += len(batch)
            if (i + batch_size) % 5000 == 0:
                print(f"    已处理 {min(i + batch_size, len(names))}/{len(names)}")
    
    print(f"✓ 完成实体节点导入，共 {total} 个")


def create_relations(session, relations: List[Dict[str, str]], batch_size: int = 500) -> None:
    """批量创建关系"""
    print(f"\n开始导入 {len(relations)} 条关系...")
    
    # 按关系类型分组
    type_groups: Dict[str, List[Dict[str, str]]] = {}
    for rel in relations:
        rel_type = rel['type']
        if rel_type not in type_groups:
            type_groups[rel_type] = []
        type_groups[rel_type].append(rel)
    
    total = 0
    for rel_type, rels in type_groups.items():
        # 将关系类型转换为合法的 Cypher 标识符（去除特殊字符）
        safe_type = ''.join(c if c.isalnum() or c in ['_'] else '_' for c in rel_type)
        print(f"  导入关系类型 '{rel_type}': {len(rels)} 条")
        
        for i in range(0, len(rels), batch_size):
            batch = rels[i:i + batch_size]
            # 使用 MERGE 避免重复关系
            query = f"""
            UNWIND $rels AS rel
            MATCH (s {{name: rel.source}})
            MATCH (t {{name: rel.target}})
            MERGE (s)-[r:`{safe_type}`]->(t)
            SET r.season = rel.season,
                r.type = rel.type
            """
            session.run(query, rels=batch)
            total += len(batch)
            if (i + batch_size) % 5000 == 0:
                print(f"    已处理 {min(i + batch_size, len(rels))}/{len(rels)}")
    
    print(f"✓ 完成关系导入，共 {total} 条")


def create_indexes(session) -> None:
    """创建索引以提高查询性能"""
    print("\n创建索引...")
    
    # 为所有可能的标签创建索引
    labels = ['Person', 'Source', 'Technique', 'Concept', 'SolarTerm', 
              'OrgLocation', 'TimeSeason', 'Symptom', 'Food', 'Medicine']
    
    for label in labels:
        try:
            query = f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.name)"
            session.run(query)
            print(f"  ✓ 为标签 '{label}' 创建索引")
        except Exception as e:
            print(f"  ! 标签 '{label}' 索引创建失败或已存在: {e}")


def clear_database(session) -> None:
    """清空数据库（慎用！）"""
    print("警告：正在清空数据库...")
    session.run("MATCH (n) DETACH DELETE n")
    print("✓ 数据库已清空")


def verify_import(session) -> None:
    """验证导入结果"""
    print("\n验证导入结果...")
    
    node_count = session.run("MATCH (n) RETURN count(n) AS c").single()['c']
    rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()['c']
    
    print(f"  节点总数: {node_count}")
    print(f"  关系总数: {rel_count}")
    
    print("\n  前 5 个节点标签分布:")
    for rec in session.run(
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c "
        "ORDER BY c DESC LIMIT 5"
    ):
        print(f"    {rec['label']}: {rec['c']}")
    
    print("\n  前 5 个关系类型分布:")
    for rec in session.run(
        "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS c "
        "ORDER BY c DESC LIMIT 5"
    ):
        print(f"    {rec['type']}: {rec['c']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入节气养生知识图谱到 Neo4j")
    parser.add_argument("--uri", default="neo4j+s://814e73bd.databases.neo4j.io", help="Neo4j URI")
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"), help="用户名")
    parser.add_argument(
        "--password",
        default=os.getenv("NEO4J_PASSWORD") or os.getenv("NEO4J_PASS") or "TLv7fqBmh8T4qqqPjIY9FJz4TRPE-CB8H2C66_5TyMc",
        help="密码",
    )
    parser.add_argument("--entities", default="entity_types.csv", help="实体CSV文件路径")
    parser.add_argument("--relations", default="relations_with_season.csv", help="关系CSV文件路径")
    parser.add_argument("--batch-size", type=int, default=500, help="批量导入大小")
    parser.add_argument("--clear", action="store_true", help="导入前清空数据库（危险操作！）")
    parser.add_argument("--skip-indexes", action="store_true", help="跳过索引创建")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    
    # 检查文件是否存在
    if not os.path.exists(args.entities):
        print(f"错误：实体文件不存在: {args.entities}")
        return
    if not os.path.exists(args.relations):
        print(f"错误：关系文件不存在: {args.relations}")
        return
    
    # 加载数据
    print("加载数据文件...")
    entities = load_entities(args.entities)
    relations = load_relations(args.relations)
    print(f"✓ 加载完成: {len(entities)} 个实体, {len(relations)} 条关系")
    
    # 连接数据库
    print(f"\n连接到 Neo4j: {args.uri}")
    try:
        driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password or None))
    except ServiceUnavailable as exc:
        print(f"错误：无法连接 Neo4j: {exc}")
        return
    
    with driver.session() as session:
        # 清空数据库（可选）
        if args.clear:
            clear_database(session)
        
        # 创建索引
        if not args.skip_indexes:
            create_indexes(session)
        
        # 导入实体
        create_entities(session, entities, args.batch_size)
        
        # 导入关系
        create_relations(session, relations, args.batch_size)
        
        # 验证
        verify_import(session)
    
    driver.close()
    print("\n✓ 导入完成！")


if __name__ == "__main__":
    main()
