#!/usr/bin/env python3
"""
查看 ChromaDB 向量数据库内容的工具
可以列出所有文档、统计信息，并支持关键词搜索。
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.vector_db import db

def list_all_documents(limit: int = 10, offset: int = 0):
    """列出向量数据库中的所有文档"""
    try:
        # 使用内部集合的 get 方法获取所有数据
        all_items = db.collection.get()
        
        ids = all_items.get("ids", [])
        documents = all_items.get("documents", [])
        metadatas = all_items.get("metadatas", [])
        
        total = len(ids)
        print(f"数据库中共有 {total} 个文档")
        
        if total == 0:
            print("数据库为空")
            return
        
        # 计算分页
        start = offset
        end = min(start + limit, total)
        
        print(f"\n显示第 {start+1} 到 {end} 个文档（共 {total} 个）:")
        print("=" * 80)
        
        for i in range(start, end):
            doc_id = ids[i]
            doc_content = documents[i] if i < len(documents) else ""
            metadata = metadatas[i] if i < len(metadatas) else {}
            
            # 截取内容预览（前200字符）
            preview = doc_content[:200] + "..." if len(doc_content) > 200 else doc_content
            
            print(f"\n文档 {i+1}: ID = {doc_id}")
            print(f"元数据: {metadata}")
            print(f"内容预览: {preview}")
            print("-" * 80)
        
        return total
        
    except Exception as e:
        print(f"获取文档列表时出错: {e}")
        import traceback
        traceback.print_exc()
        return 0

def show_statistics():
    """显示数据库统计信息"""
    try:
        all_items = db.collection.get()
        ids = all_items.get("ids", [])
        metadatas = all_items.get("metadatas", [])
        
        total = len(ids)
        print(f"文档总数: {total}")
        
        # 统计不同来源的文档
        sources = {}
        for metadata in metadatas:
            if metadata and 'source' in metadata:
                source = metadata['source']
                sources[source] = sources.get(source, 0) + 1
        
        if sources:
            print("\n按来源统计:")
            for source, count in sorted(sources.items(), key=lambda x: x[1], reverse=True):
                print(f"  {source}: {count} 个文档")
        
        # 平均文档长度
        documents = all_items.get("documents", [])
        if documents:
            avg_len = sum(len(doc) for doc in documents) / len(documents)
            print(f"\n平均文档长度: {avg_len:.1f} 字符")
            
            # 文档长度分布
            len_dist = {
                "短 (<100字符)": len([d for d in documents if len(d) < 100]),
                "中等 (100-500字符)": len([d for d in documents if 100 <= len(d) < 500]),
                "长 (500-1000字符)": len([d for d in documents if 500 <= len(d) < 1000]),
                "很长 (>=1000字符)": len([d for d in documents if len(d) >= 1000]),
            }
            print("文档长度分布:")
            for category, count in len_dist.items():
                if count > 0:
                    percentage = (count / total) * 100
                    print(f"  {category}: {count} 个 ({percentage:.1f}%)")
        
        return True
        
    except Exception as e:
        print(f"获取统计信息时出错: {e}")
        return False

def search_documents(query: str, n_results: int = 5):
    """搜索相关文档"""
    try:
        print(f"搜索查询: '{query}'")
        results = db.search_with_scores(query, n_results=n_results)
        
        if not results:
            print("未找到相关文档")
            return
        
        print(f"找到 {len(results)} 个相关文档:")
        print("=" * 80)
        
        for i, result in enumerate(results):
            doc_id = result.get("id", "未知")
            score = result.get("score", 0)
            distance = result.get("distance", 0)
            metadata = result.get("metadata", {})
            content = result.get("content", "")
            
            preview = content[:150] + "..." if len(content) > 150 else content
            
            print(f"\n结果 {i+1}:")
            print(f"  ID: {doc_id}")
            print(f"  相关性得分: {score:.4f} (距离: {distance:.4f})")
            print(f"  元数据: {metadata}")
            print(f"  内容预览: {preview}")
            print("-" * 80)
        
        return True
        
    except Exception as e:
        print(f"搜索时出错: {e}")
        return False

def main():
    """主函数"""
    print("=" * 80)
    print("ChromaDB 向量数据库查看工具")
    print("=" * 80)
    
    # 检查连接
    try:
        count = db.collection.count()
        print(f"成功连接到 ChromaDB，集合名称: '{db.collection.name}'")
        print(f"文档数量: {count}")
    except Exception as e:
        print(f"连接 ChromaDB 失败: {e}")
        print("请确保:")
        print("1. ChromaDB 数据目录存在 (默认: analyzer/chroma_db)")
        print("2. 已安装 chromadb 包 (pip install chromadb)")
        return
    
    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description='查看 ChromaDB 向量数据库内容')
    parser.add_argument('--list', action='store_true', help='列出所有文档')
    parser.add_argument('--stats', action='store_true', help='显示统计信息')
    parser.add_argument('--search', type=str, help='搜索关键词')
    parser.add_argument('--limit', type=int, default=10, help='列出文档的数量限制')
    parser.add_argument('--offset', type=int, default=0, help='列出文档的起始偏移')
    parser.add_argument('--n-results', type=int, default=5, help='搜索结果数量')
    
    args = parser.parse_args()
    
    # 如果没有指定任何操作，默认显示统计信息
    if not (args.list or args.stats or args.search):
        args.stats = True
    
    # 执行操作
    if args.stats:
        print("\n[统计信息]")
        show_statistics()
    
    if args.list:
        print(f"\n[文档列表]")
        list_all_documents(limit=args.limit, offset=args.offset)
    
    if args.search:
        print(f"\n[搜索]")
        search_documents(args.search, n_results=args.n_results)
    
    print("\n" + "=" * 80)
    print("工具执行完成")

if __name__ == "__main__":
    main()