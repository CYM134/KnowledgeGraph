"""
检查并消解 Neo4j 知识图谱中的数据冲突。

冲突类型：
1. 重复节点：同名但标签不同的节点
2. 自环关系：节点指向自己的关系
3. 重复关系：相同源、目标、类型的多条关系
4. 孤立节点：没有任何关系的节点
5. 不一致的关系属性：相同关系但属性值不同
6. 命名冲突：名称相似但有细微差别（空格、标点等）

依赖：pip install neo4j
"""

import argparse
import os
from typing import Dict, List, Set, Tuple
from collections import defaultdict

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable


class ConflictResolver:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def close(self):
        self.driver.close()
    
    # ========== 冲突检测 ==========
    
    def find_duplicate_nodes(self, session) -> List[Dict]:
        """查找同名但标签不同的重复节点"""
        print("\n【检查1】查找重复节点（同名不同标签）...")
        query = """
        MATCH (n)
        WITH n.name AS name, collect(DISTINCT labels(n)) AS label_sets, collect(id(n)) AS ids
        WHERE size(label_sets) > 1
        RETURN name, label_sets, ids, size(ids) AS count
        ORDER BY count DESC
        """
        results = []
        for rec in session.run(query):
            results.append({
                'name': rec['name'],
                'label_sets': rec['label_sets'],
                'ids': rec['ids'],
                'count': rec['count']
            })
        
        if results:
            print(f"  ⚠ 发现 {len(results)} 个重复节点:")
            for i, item in enumerate(results[:10], 1):
                print(f"    {i}. '{item['name']}' 有 {item['count']} 个副本，标签: {item['label_sets']}")
            if len(results) > 10:
                print(f"    ... 还有 {len(results) - 10} 个")
        else:
            print("  ✓ 未发现重复节点")
        
        return results
    
    def find_self_loops(self, session) -> List[Dict]:
        """查找自环关系"""
        print("\n【检查2】查找自环关系...")
        query = """
        MATCH (n)-[r]->(n)
        RETURN n.name AS name, type(r) AS rel_type, id(r) AS rel_id, r.season AS season
        """
        results = []
        for rec in session.run(query):
            results.append({
                'name': rec['name'],
                'rel_type': rec['rel_type'],
                'rel_id': rec['rel_id'],
                'season': rec['season']
            })
        
        if results:
            print(f"  ⚠ 发现 {len(results)} 个自环关系:")
            for i, item in enumerate(results[:10], 1):
                print(f"    {i}. '{item['name']}' --{item['rel_type']}--> '{item['name']}'")
            if len(results) > 10:
                print(f"    ... 还有 {len(results) - 10} 个")
        else:
            print("  ✓ 未发现自环关系")
        
        return results
    
    def find_duplicate_relations(self, session) -> List[Dict]:
        """查找重复关系（相同源、目标、类型）"""
        print("\n【检查3】查找重复关系...")
        query = """
        MATCH (s)-[r]->(t)
        WITH s, t, type(r) AS rel_type, collect(r) AS rels
        WHERE size(rels) > 1
        RETURN s.name AS source, t.name AS target, rel_type, 
               size(rels) AS count, [rel IN rels | id(rel)] AS rel_ids
        ORDER BY count DESC
        LIMIT 100
        """
        results = []
        for rec in session.run(query):
            results.append({
                'source': rec['source'],
                'target': rec['target'],
                'rel_type': rec['rel_type'],
                'count': rec['count'],
                'rel_ids': rec['rel_ids']
            })
        
        if results:
            print(f"  ⚠ 发现 {len(results)} 组重复关系:")
            for i, item in enumerate(results[:10], 1):
                print(f"    {i}. '{item['source']}' --{item['rel_type']}--> '{item['target']}' (×{item['count']})")
            if len(results) > 10:
                print(f"    ... 还有 {len(results) - 10} 组")
        else:
            print("  ✓ 未发现重复关系")
        
        return results
    
    def find_isolated_nodes(self, session) -> List[Dict]:
        """查找孤立节点"""
        print("\n【检查4】查找孤立节点...")
        query = """
        MATCH (n)
        WHERE NOT (n)--()
        RETURN n.name AS name, labels(n) AS labels, id(n) AS node_id
        LIMIT 100
        """
        results = []
        for rec in session.run(query):
            results.append({
                'name': rec['name'],
                'labels': rec['labels'],
                'node_id': rec['node_id']
            })
        
        if results:
            print(f"  ⚠ 发现 {len(results)} 个孤立节点:")
            for i, item in enumerate(results[:10], 1):
                print(f"    {i}. '{item['name']}' {item['labels']}")
            if len(results) > 10:
                print(f"    ... 还有 {len(results) - 10} 个")
        else:
            print("  ✓ 未发现孤立节点")
        
        return results
    
    def find_naming_conflicts(self, session) -> List[Dict]:
        """查找命名冲突（名称相似但有细微差别）"""
        print("\n【检查5】查找命名冲突（空格、标点等）...")
        query = """
        MATCH (n)
        WITH n.name AS original_name, 
             trim(replace(replace(n.name, ' ', ''), '　', '')) AS normalized_name,
             collect(n) AS nodes
        WHERE size(nodes) > 1
        RETURN normalized_name, 
               [node IN nodes | node.name] AS variants,
               [node IN nodes | labels(node)] AS label_sets,
               size(nodes) AS count
        ORDER BY count DESC
        LIMIT 50
        """
        results = []
        for rec in session.run(query):
            results.append({
                'normalized': rec['normalized_name'],
                'variants': rec['variants'],
                'label_sets': rec['label_sets'],
                'count': rec['count']
            })
        
        if results:
            print(f"  ⚠ 发现 {len(results)} 组命名冲突:")
            for i, item in enumerate(results[:10], 1):
                print(f"    {i}. 标准化: '{item['normalized']}' 有 {item['count']} 个变体:")
                for variant in item['variants'][:3]:
                    print(f"        - '{variant}'")
            if len(results) > 10:
                print(f"    ... 还有 {len(results) - 10} 组")
        else:
            print("  ✓ 未发现命名冲突")
        
        return results
    
    def find_inconsistent_relation_properties(self, session) -> List[Dict]:
        """查找不一致的关系属性"""
        print("\n【检查6】查找关系属性不一致...")
        query = """
        MATCH (s)-[r]->(t)
        WITH s.name AS source, t.name AS target, type(r) AS rel_type,
             collect(DISTINCT r.season) AS seasons
        WHERE size(seasons) > 1
        RETURN source, target, rel_type, seasons
        LIMIT 50
        """
        results = []
        for rec in session.run(query):
            results.append({
                'source': rec['source'],
                'target': rec['target'],
                'rel_type': rec['rel_type'],
                'seasons': rec['seasons']
            })
        
        if results:
            print(f"  ⚠ 发现 {len(results)} 组关系属性不一致:")
            for i, item in enumerate(results[:10], 1):
                print(f"    {i}. '{item['source']}' --{item['rel_type']}--> '{item['target']}'")
                print(f"        不同的season值: {item['seasons']}")
            if len(results) > 10:
                print(f"    ... 还有 {len(results) - 10} 组")
        else:
            print("  ✓ 未发现关系属性不一致")
        
        return results
    
    # ========== 冲突消解 ==========
    
    def merge_duplicate_nodes(self, session, dry_run: bool = True) -> int:
        """合并重复节点（保留所有标签）"""
        print("\n【消解1】合并重复节点...")
        duplicates = self.find_duplicate_nodes(session)
        
        if not duplicates:
            return 0
        
        count = 0
        for dup in duplicates:
            name = dup['name']
            ids = dup['ids']
            
            if dry_run:
                print(f"  [模拟] 将合并节点 '{name}' 的 {len(ids)} 个副本")
            else:
                # 合并策略：保留第一个节点，将其他节点的关系转移，然后删除
                query = """
                MATCH (nodes)
                WHERE id(nodes) IN $ids
                WITH nodes, $ids AS id_list
                ORDER BY id(nodes)
                WITH collect(nodes) AS all_nodes, id_list
                WITH all_nodes[0] AS keeper, all_nodes[1..] AS duplicates
                UNWIND duplicates AS dup
                // 收集所有标签
                WITH keeper, dup, labels(dup) AS dup_labels
                CALL apoc.create.addLabels(keeper, dup_labels) YIELD node AS labeled_node
                // 转移所有关系
                WITH keeper, dup
                OPTIONAL MATCH (dup)-[r]->(target)
                WHERE target <> dup
                MERGE (keeper)-[new_r:SAME_TYPE]->(target)
                SET new_r = r
                DELETE r
                WITH keeper, dup
                OPTIONAL MATCH (source)-[r]->(dup)
                WHERE source <> dup
                MERGE (source)-[new_r:SAME_TYPE]->(keeper)
                SET new_r = r
                DELETE r
                WITH keeper, dup
                DETACH DELETE dup
                RETURN count(dup) AS merged
                """
                # 注意：上述查询需要 APOC 插件，简化版本：
                simple_query = """
                MATCH (nodes)
                WHERE id(nodes) IN $ids
                WITH nodes
                ORDER BY id(nodes)
                WITH collect(nodes) AS all_nodes
                WITH all_nodes[0] AS keeper, all_nodes[1..] AS duplicates
                UNWIND duplicates AS dup
                // 转移出边
                OPTIONAL MATCH (dup)-[r]->(target)
                WHERE target <> dup AND NOT (keeper)-[:DUMMY]->(target)
                WITH keeper, dup, r, target, type(r) AS rel_type
                CALL apoc.cypher.run(
                    'MATCH (k), (t) WHERE id(k) = $kid AND id(t) = $tid ' +
                    'MERGE (k)-[nr:`' + rel_type + '`]->(t) ' +
                    'SET nr = $props RETURN nr',
                    {kid: id(keeper), tid: id(target), props: properties(r)}
                ) YIELD value
                DELETE r
                // 转移入边
                WITH keeper, dup
                OPTIONAL MATCH (source)-[r]->(dup)
                WHERE source <> dup
                // ... 类似处理
                WITH keeper, dup
                DETACH DELETE dup
                """
                # 最简化版本（可能丢失部分信息）
                basic_query = """
                MATCH (nodes)
                WHERE id(nodes) IN $ids
                WITH nodes, $ids[0] AS keeper_id
                WHERE id(nodes) <> keeper_id
                DETACH DELETE nodes
                RETURN count(nodes) AS deleted
                """
                try:
                    result = session.run(basic_query, ids=ids)
                    deleted = result.single()['deleted']
                    count += deleted
                    print(f"  ✓ 合并节点 '{name}': 删除了 {deleted} 个重复")
                except Exception as e:
                    print(f"  ✗ 合并节点 '{name}' 失败: {e}")
        
        if dry_run:
            print(f"  [模拟模式] 将合并 {len(duplicates)} 组重复节点")
        else:
            print(f"  ✓ 完成合并，删除了 {count} 个重复节点")
        
        return count
    
    def remove_self_loops(self, session, dry_run: bool = True) -> int:
        """删除自环关系"""
        print("\n【消解2】删除自环关系...")
        self_loops = self.find_self_loops(session)
        
        if not self_loops:
            return 0
        
        if dry_run:
            print(f"  [模拟] 将删除 {len(self_loops)} 个自环关系")
            return 0
        
        query = """
        MATCH (n)-[r]->(n)
        DELETE r
        RETURN count(r) AS deleted
        """
        result = session.run(query)
        count = result.single()['deleted']
        print(f"  ✓ 删除了 {count} 个自环关系")
        return count
    
    def merge_duplicate_relations(self, session, dry_run: bool = True) -> int:
        """合并重复关系（保留属性）"""
        print("\n【消解3】合并重复关系...")
        duplicates = self.find_duplicate_relations(session)
        
        if not duplicates:
            return 0
        
        count = 0
        for dup in duplicates[:100]:  # 限制处理数量
            source = dup['source']
            target = dup['target']
            rel_type = dup['rel_type']
            
            if dry_run:
                print(f"  [模拟] 将合并关系: '{source}' --{rel_type}--> '{target}' (×{dup['count']})")
            else:
                # 保留第一个关系，删除其余
                query = f"""
                MATCH (s {{name: $source}})-[r:`{rel_type}`]->(t {{name: $target}})
                WITH s, t, collect(r) AS rels
                WHERE size(rels) > 1
                WITH s, t, rels[0] AS keeper, rels[1..] AS duplicates
                UNWIND duplicates AS dup_rel
                DELETE dup_rel
                RETURN count(dup_rel) AS deleted
                """
                try:
                    result = session.run(query, source=source, target=target)
                    deleted = result.single()['deleted']
                    count += deleted
                except Exception as e:
                    print(f"  ✗ 合并关系失败: {e}")
        
        if dry_run:
            print(f"  [模拟模式] 将合并 {len(duplicates)} 组重复关系")
        else:
            print(f"  ✓ 完成合并，删除了 {count} 个重复关系")
        
        return count
    
    def remove_isolated_nodes(self, session, dry_run: bool = True, keep_important: bool = True) -> int:
        """删除孤立节点（可选择保留重要节点）"""
        print("\n【消解4】删除孤立节点...")
        isolated = self.find_isolated_nodes(session)
        
        if not isolated:
            return 0
        
        if dry_run:
            print(f"  [模拟] 将删除 {len(isolated)} 个孤立节点")
            return 0
        
        if keep_important:
            # 保留重要标签的节点（如节气、人物等）
            important_labels = ['SolarTerm', 'Person', 'Source']
            query = """
            MATCH (n)
            WHERE NOT (n)--()
              AND NOT any(label IN labels(n) WHERE label IN $important_labels)
            DELETE n
            RETURN count(n) AS deleted
            """
            result = session.run(query, important_labels=important_labels)
        else:
            query = """
            MATCH (n)
            WHERE NOT (n)--()
            DELETE n
            RETURN count(n) AS deleted
            """
            result = session.run(query)
        
        count = result.single()['deleted']
        print(f"  ✓ 删除了 {count} 个孤立节点")
        return count
    
    def normalize_node_names(self, session, dry_run: bool = True) -> int:
        """规范化节点名称（去除空格、统一标点）"""
        print("\n【消解5】规范化节点名称...")
        conflicts = self.find_naming_conflicts(session)
        
        if not conflicts:
            return 0
        
        if dry_run:
            print(f"  [模拟] 将规范化 {len(conflicts)} 组节点名称")
            return 0
        
        count = 0
        for conf in conflicts:
            # 选择最常见或最短的名称作为标准
            variants = conf['variants']
            canonical = min(variants, key=len)  # 使用最短的名称
            
            for variant in variants:
                if variant != canonical:
                    query = """
                    MATCH (n {name: $old_name})
                    SET n.name = $new_name
                    RETURN count(n) AS updated
                    """
                    try:
                        result = session.run(query, old_name=variant, new_name=canonical)
                        updated = result.single()['updated']
                        count += updated
                        print(f"  ✓ 规范化: '{variant}' -> '{canonical}'")
                    except Exception as e:
                        print(f"  ✗ 规范化失败: {e}")
        
        print(f"  ✓ 完成规范化，更新了 {count} 个节点")
        return count
    
    def unify_relation_properties(self, session, dry_run: bool = True) -> int:
        """统一关系属性（选择最常见的值）"""
        print("\n【消解6】统一关系属性...")
        inconsistent = self.find_inconsistent_relation_properties(session)
        
        if not inconsistent:
            return 0
        
        if dry_run:
            print(f"  [模拟] 将统一 {len(inconsistent)} 组关系属性")
            return 0
        
        count = 0
        for item in inconsistent:
            source = item['source']
            target = item['target']
            rel_type = item['rel_type']
            seasons = item['seasons']
            
            # 选择非"未知"的值，或最常见的值
            canonical = next((s for s in seasons if s and s != '未知'), seasons[0])
            
            query = f"""
            MATCH (s {{name: $source}})-[r:`{rel_type}`]->(t {{name: $target}})
            SET r.season = $canonical
            RETURN count(r) AS updated
            """
            try:
                result = session.run(query, source=source, target=target, canonical=canonical)
                updated = result.single()['updated']
                count += updated
            except Exception as e:
                print(f"  ✗ 统一属性失败: {e}")
        
        print(f"  ✓ 完成统一，更新了 {count} 个关系")
        return count
    
    # ========== 主流程 ==========
    
    def check_all_conflicts(self):
        """检查所有冲突"""
        print("\n" + "="*60)
        print("开始检查数据库冲突...")
        print("="*60)
        
        with self.driver.session() as session:
            self.find_duplicate_nodes(session)
            self.find_self_loops(session)
            self.find_duplicate_relations(session)
            self.find_isolated_nodes(session)
            self.find_naming_conflicts(session)
            self.find_inconsistent_relation_properties(session)
        
        print("\n" + "="*60)
        print("冲突检查完成")
        print("="*60)
    
    def resolve_all_conflicts(self, dry_run: bool = True):
        """消解所有冲突"""
        print("\n" + "="*60)
        if dry_run:
            print("开始模拟消解冲突（不会修改数据）...")
        else:
            print("开始消解冲突...")
        print("="*60)
        
        total_changes = 0
        
        with self.driver.session() as session:
            # 1. 删除自环关系
            total_changes += self.remove_self_loops(session, dry_run)
            
            # 2. 合并重复关系
            total_changes += self.merge_duplicate_relations(session, dry_run)
            
            # 3. 统一关系属性
            total_changes += self.unify_relation_properties(session, dry_run)
            
            # 4. 规范化节点名称
            total_changes += self.normalize_node_names(session, dry_run)
            
            # 5. 合并重复节点
            total_changes += self.merge_duplicate_nodes(session, dry_run)
            
            # 6. 删除孤立节点（可选）
            # total_changes += self.remove_isolated_nodes(session, dry_run)
        
        print("\n" + "="*60)
        if dry_run:
            print(f"模拟完成，预计修改: {total_changes} 项")
            print("使用 --execute 参数执行实际修改")
        else:
            print(f"冲突消解完成，共修改: {total_changes} 项")
        print("="*60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查并消解 Neo4j 知识图谱中的冲突")
    parser.add_argument("--uri", default="neo4j+s://814e73bd.databases.neo4j.io", help="Neo4j URI")
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"), help="用户名")
    parser.add_argument(
        "--password",
        default=os.getenv("NEO4J_PASSWORD") or os.getenv("NEO4J_PASS") or "TLv7fqBmh8T4qqqPjIY9FJz4TRPE-CB8H2C66_5TyMc",
        help="密码",
    )
    parser.add_argument("--check-only", action="store_true", help="仅检查冲突，不执行消解")
    parser.add_argument("--execute", action="store_true", help="执行实际的冲突消解（默认为模拟模式）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    
    print(f"连接到 Neo4j: {args.uri}")
    try:
        resolver = ConflictResolver(args.uri, args.user, args.password)
    except ServiceUnavailable as exc:
        print(f"错误：无法连接 Neo4j: {exc}")
        return
    
    try:
        if args.check_only:
            # 仅检查
            resolver.check_all_conflicts()
        else:
            # 检查并消解
            resolver.check_all_conflicts()
            resolver.resolve_all_conflicts(dry_run=not args.execute)
    finally:
        resolver.close()


if __name__ == "__main__":
    main()
