"""
验证 Neo4j 中的 24 节气养生知识图谱是否可用。

检查项：
- 节点/关系规模、标签/关系类型 TopN
- 24 节气覆盖与连通情况
- 实体邻居查看
- 限深最短路径

依赖：pip install neo4j
"""

import argparse
import os
from typing import List, Optional

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

SOLAR_TERMS = [
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
]


def summarize(session) -> None:
    node_count = session.run("MATCH (n) RETURN count(*) AS c").single().value()
    rel_count = session.run("MATCH ()-[r]->() RETURN count(*) AS c").single().value()
    print(f"节点数: {node_count}")
    print(f"关系数: {rel_count}")

    print("\n关系类型 Top 10:")
    for rec in session.run(
        "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS c "
        "ORDER BY c DESC LIMIT 10"
    ):
        print(f"  {rec['rel']}: {rec['c']}")

    print("\n标签 Top 10:")
    for rec in session.run(
        "MATCH (n) UNWIND labels(n) AS l "
        "RETURN l, count(*) AS c ORDER BY c DESC LIMIT 10"
    ):
        print(f"  {rec['l']}: {rec['c']}")


def check_solar_terms(session, node_label: Optional[str], name_prop: str) -> None:
    present = []
    missing = []
    connected = []
    for term in SOLAR_TERMS:
        label_clause = f":{node_label}" if node_label else ""
        query = (
            f"MATCH (n{label_clause} {{{name_prop}:$name}}) "
            "OPTIONAL MATCH (n)-[r]-() "
            "RETURN labels(n) AS labels, count(r) AS deg LIMIT 1"
        )
        rec = session.run(query, name=term).single()
        if rec:
            present.append(term)
            if rec["deg"] > 0:
                connected.append(term)
        else:
            missing.append(term)

    print("\n24 节气覆盖:")
    print(f"  已存在 {len(present)}/24: {present}")
    if missing:
        print(f"  缺失 {len(missing)}: {missing}")
    print(f"  有关系的节气: {len(connected)} -> {connected}")


def top_degree(session, limit: int, node_label: Optional[str], name_prop: str) -> None:
    if limit <= 0:
        return
    label_clause = f":{node_label}" if node_label else ""
    query = (
        f"MATCH (n{label_clause}) "
        "OPTIONAL MATCH (n)-[r]-() "
        f"RETURN n.{name_prop} AS name, labels(n) AS labels, count(r) AS deg "
        "ORDER BY deg DESC LIMIT $limit"
    )
    print(f"\n度数 Top {limit}:")
    for row in session.run(query, limit=limit):
        print(f"  {row['name']} {row['labels']} deg={row['deg']}")


def isolated_nodes(session, sample: int, node_label: Optional[str], name_prop: str) -> None:
    label_clause = f":{node_label}" if node_label else ""
    count_query = f"MATCH (n{label_clause}) WHERE NOT (n)--() RETURN count(n) AS c"
    count = session.run(count_query).single().value()
    print(f"\n孤立节点: {count}")
    if sample > 0 and count > 0:
        sample_query = (
            f"MATCH (n{label_clause}) WHERE NOT (n)--() "
            f"RETURN n.{name_prop} AS name, labels(n) AS labels "
            "LIMIT $limit"
        )
        print(f"  样例 (最多 {sample} 个):")
        for row in session.run(sample_query, limit=sample):
            print(f"    {row['name']} {row['labels']}")


def show_entity(session, name: str, limit: int, node_label: Optional[str], name_prop: str) -> None:
    label_clause = f":{node_label}" if node_label else ""
    rec = session.run(
        f"MATCH (n{label_clause} {{{name_prop}:$name}}) RETURN labels(n) AS labels",
        name=name,
    ).single()
    if not rec:
        print(f"\n实体: {name} 未找到")
        return
    print(f"\n实体: {name} (labels={rec['labels']})")

    print("  出边:")
    out_records = session.run(
        f"MATCH (n{label_clause} {{{name_prop}:$name}})-[r]->(m) "
        f"RETURN type(r) AS rel, m.{name_prop} AS target, labels(m) AS labels "
        "LIMIT $limit",
        name=name,
        limit=limit,
    )
    any_out = False
    for idx, row in enumerate(out_records, 1):
        any_out = True
        print(f"    {idx}. --{row['rel']}--> {row['target']} {row['labels']}")
    if not any_out:
        print("    无")

    print("  入边:")
    in_records = session.run(
        f"MATCH (m)-[r]->(n{label_clause} {{{name_prop}:$name}}) "
        f"RETURN type(r) AS rel, m.{name_prop} AS source, labels(m) AS labels "
        "LIMIT $limit",
        name=name,
        limit=limit,
    )
    any_in = False
    for idx, row in enumerate(in_records, 1):
        any_in = True
        print(f"    {idx}. {row['source']} {row['labels']} --{row['rel']}-->")
    if not any_in:
        print("    无")


def find_path(session, source: str, target: str, depth: int, node_label: Optional[str], name_prop: str) -> None:
    print(f"\n路径: {source} -> {target} (<= {depth} 跳)")
    label_clause = f":{node_label}" if node_label else ""
    rec = session.run(
        f"MATCH p = shortestPath((a{label_clause} {{{name_prop}:$src}})-[*..$d]-(b{label_clause} {{{name_prop}:$tgt}})) "
        "RETURN p LIMIT 1",
        src=source,
        tgt=target,
        d=depth,
    ).single()
    if not rec:
        print("  未找到路径。")
        return
    path = rec["p"]
    for i in range(len(path.relationships)):
        start_node = path.nodes[i]
        rel = path.relationships[i]
        end_node = path.nodes[i + 1]
        start_name = start_node.get(name_prop, start_node.get("name", ""))
        end_name = end_node.get(name_prop, end_node.get("name", ""))
        print(f"  {start_name} --{rel.type}--> {end_name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证 Neo4j 中的节气养生知识图谱")
    parser.add_argument("--uri", default="neo4j+s://814e73bd.databases.neo4j.io", help="Neo4j URI")
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"), help="用户名")
    parser.add_argument(
        "--password",
        default=os.getenv("NEO4J_PASSWORD") or os.getenv("NEO4J_PASS") or "TLv7fqBmh8T4qqqPjIY9FJz4TRPE-CB8H2C66_5TyMc",
        help="密码",
    )
    parser.add_argument("--node-label", help="实体节点的标签（如导入器默认的 Node）")
    parser.add_argument("--name-prop", default="name", help="实体名称属性键，默认 name")
    parser.add_argument("--entity", help="要查看邻居的实体名称")
    parser.add_argument("--path", nargs=2, metavar=("SOURCE", "TARGET"), help="查询两实体的最短路径")
    parser.add_argument("--max-depth", type=int, default=4, help="路径最大长度，默认 4")
    parser.add_argument("--neighbor-limit", type=int, default=20, help="邻居展示条数，默认 20")
    parser.add_argument("--top-degree", type=int, default=10, help="展示度数最高的节点数，0 表示关闭")
    parser.add_argument("--isolated-sample", type=int, default=0, help="展示孤立节点样例数，0 表示不展示")
    parser.add_argument("--no-summary", action="store_true", help="不输出全局概要")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password or None))
    except ServiceUnavailable as exc:
        print(f"无法连接 Neo4j: {exc}")
        return

    with driver.session() as session:
        if not args.no_summary:
            summarize(session)
            check_solar_terms(session, args.node_label, args.name_prop)
            top_degree(session, args.top_degree, args.node_label, args.name_prop)
            isolated_nodes(session, args.isolated_sample, args.node_label, args.name_prop)

        if args.entity:
            show_entity(session, args.entity, args.neighbor_limit, args.node_label, args.name_prop)

        if args.path:
            find_path(session, args.path[0], args.path[1], args.max_depth, args.node_label, args.name_prop)

    driver.close()


if __name__ == "__main__":
    main()
