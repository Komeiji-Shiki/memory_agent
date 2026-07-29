#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
JSON索引迁移到SQLite脚本

将现有的 .memory_index.json 迁移到 .memory_index.db

功能：
1. 读取现有JSON索引
2. 创建SQLite数据库
3. 验证迁移结果
4. 保留原文件作为备份

用法：
    python migrate_to_sqlite.py [lifebook_path]
    
    如果不指定路径，默认使用 ./lifebook
"""

import os
import sys
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory_store.sqlite_indexer import SqliteIndexer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_json_to_sqlite(lifebook_path: str, force: bool = False) -> bool:
    """
    将JSON索引迁移到SQLite
    
    Args:
        lifebook_path: LifeBook根目录路径
        force: 是否强制重建（即使SQLite已存在）
    
    Returns:
        是否成功
    """
    root = Path(lifebook_path)
    json_file = root / ".memory_index.json"
    db_file = root / ".memory_index.db"
    backup_file = root / f".memory_index.json.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # 检查JSON文件
    if not json_file.exists():
        logger.warning(f"JSON索引文件不存在: {json_file}")
        logger.info("将直接创建新的SQLite索引...")
        
        # 直接创建SQLite索引
        indexer = SqliteIndexer(str(root))
        indexer.rebuild_index()
        
        logger.info("✓ SQLite索引创建成功")
        return True
    
    # 检查SQLite是否已存在
    if db_file.exists() and not force:
        logger.warning(f"SQLite数据库已存在: {db_file}")
        logger.info("使用 --force 参数强制重建")
        return False
    
    # 读取JSON索引
    logger.info(f"读取JSON索引: {json_file}")
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
    except Exception as e:
        logger.error(f"读取JSON失败: {e}")
        return False
    
    # 显示JSON统计
    json_stats = {
        "keywords": len(json_data.get("keywords", {})),
        "tags": len(json_data.get("tags", {})),
        "people": len(json_data.get("people", {})),
        "dates": len(json_data.get("dates", {})),
        "metadata": len(json_data.get("metadata", {})),
    }
    logger.info(f"JSON索引统计: {json_stats}")
    
    # 备份JSON文件
    logger.info(f"备份JSON文件到: {backup_file}")
    shutil.copy2(json_file, backup_file)
    
    # 删除旧的SQLite（如果存在）
    if db_file.exists():
        logger.info(f"删除旧的SQLite数据库: {db_file}")
        db_file.unlink()
    
    # 创建SQLite索引（会自动重建）
    logger.info("创建SQLite索引...")
    indexer = SqliteIndexer(str(root))
    
    # 注意：SqliteIndexer 的 __init__ 会检测空数据库并自动重建
    # 所以这里不需要手动调用 rebuild_index()
    
    # 验证迁移结果
    logger.info("验证迁移结果...")
    sqlite_stats = indexer.get_stats()
    
    logger.info(f"SQLite索引统计: {sqlite_stats}")
    
    # 比较关键指标
    success = True
    checks = []
    
    # 检查文件数量（metadata条目数）
    json_files = json_stats["metadata"]
    sqlite_files = sqlite_stats["total_files"]
    if sqlite_files >= json_files * 0.9:  # 允许10%误差
        checks.append(f"✓ 文件数量: JSON {json_files} → SQLite {sqlite_files}")
    else:
        checks.append(f"✗ 文件数量不匹配: JSON {json_files} → SQLite {sqlite_files}")
        success = False
    
    # 检查标签数量
    json_tags = json_stats["tags"]
    sqlite_tags = sqlite_stats["total_tags"]
    if sqlite_tags >= json_tags * 0.9:
        checks.append(f"✓ 标签数量: JSON {json_tags} → SQLite {sqlite_tags}")
    else:
        checks.append(f"✗ 标签数量不匹配: JSON {json_tags} → SQLite {sqlite_tags}")
        success = False
    
    # 检查人物数量
    json_people = json_stats["people"]
    sqlite_people = sqlite_stats["total_people"]
    if sqlite_people >= json_people * 0.9:
        checks.append(f"✓ 人物数量: JSON {json_people} → SQLite {sqlite_people}")
    else:
        checks.append(f"✗ 人物数量不匹配: JSON {json_people} → SQLite {sqlite_people}")
        success = False
    
    for check in checks:
        logger.info(check)
    
    if success:
        logger.info("\n" + "=" * 50)
        logger.info("✓ 迁移成功！")
        logger.info(f"  原JSON备份: {backup_file}")
        logger.info(f"  新SQLite数据库: {db_file}")
        logger.info("\n提示: 原 .memory_index.json 已保留，可在确认无误后手动删除")
    else:
        logger.warning("\n" + "=" * 50)
        logger.warning("⚠ 迁移可能存在问题，请检查数据")
        logger.info(f"  备份文件: {backup_file}")
    
    return success


def compare_search_results(lifebook_path: str) -> bool:
    """
    比较JSON和SQLite的搜索结果
    
    用于验证迁移后功能一致性
    """
    from memory_store.indexer import MemoryIndexer
    from memory_store.sqlite_indexer import SqliteIndexer
    
    root = Path(lifebook_path)
    
    # 检查两个索引都存在
    if not (root / ".memory_index.json").exists():
        logger.warning("JSON索引不存在，跳过比较")
        return True
    
    if not (root / ".memory_index.db").exists():
        logger.warning("SQLite索引不存在，跳过比较")
        return True
    
    logger.info("比较搜索结果...")
    
    # 初始化两个索引器
    json_indexer = MemoryIndexer(str(root))
    sqlite_indexer = SqliteIndexer(str(root))
    
    # 测试用例
    test_cases = [
        {"query": "主人", "limit": 5},
        {"query": "记忆", "limit": 5},
        {"tags": ["技术"], "limit": 5},
    ]
    
    all_match = True
    
    for test in test_cases:
        query = test.get("query", "")
        tags = test.get("tags", None)
        limit = test.get("limit", 10)
        
        json_results = json_indexer.search(query, tags=tags, limit=limit)
        sqlite_results = sqlite_indexer.search(query, tags=tags, limit=limit)
        
        # 比较结果数量
        if len(json_results) == len(sqlite_results):
            logger.info(f"  ✓ 搜索 '{query}' tags={tags}: 结果数量一致 ({len(json_results)})")
        else:
            logger.warning(f"  ✗ 搜索 '{query}' tags={tags}: JSON {len(json_results)} vs SQLite {len(sqlite_results)}")
            all_match = False
    
    return all_match


def rollback(lifebook_path: str) -> bool:
    """
    回滚到JSON索引
    
    删除SQLite数据库，恢复备份的JSON
    """
    root = Path(lifebook_path)
    db_file = root / ".memory_index.db"
    json_file = root / ".memory_index.json"
    
    # 查找最新的备份
    backups = list(root.glob(".memory_index.json.backup_*"))
    if not backups:
        logger.warning("未找到备份文件")
        return False
    
    latest_backup = max(backups, key=lambda p: p.stat().st_mtime)
    logger.info(f"找到备份: {latest_backup}")
    
    # 删除SQLite
    if db_file.exists():
        logger.info(f"删除SQLite数据库: {db_file}")
        db_file.unlink()
    
    # 恢复JSON
    logger.info(f"恢复JSON索引: {json_file}")
    shutil.copy2(latest_backup, json_file)
    
    logger.info("✓ 回滚完成")
    return True


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="将JSON索引迁移到SQLite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python migrate_to_sqlite.py                    # 使用默认路径 ./lifebook
  python migrate_to_sqlite.py /path/to/lifebook  # 指定路径
  python migrate_to_sqlite.py --force            # 强制重建
  python migrate_to_sqlite.py --compare          # 比较搜索结果
  python migrate_to_sqlite.py --rollback         # 回滚到JSON
        """
    )
    
    parser.add_argument(
        "path",
        nargs="?",
        default="./lifebook",
        help="LifeBook目录路径（默认: ./lifebook）"
    )
    
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="强制重建SQLite（即使已存在）"
    )
    
    parser.add_argument(
        "--compare", "-c",
        action="store_true",
        help="比较JSON和SQLite的搜索结果"
    )
    
    parser.add_argument(
        "--rollback", "-r",
        action="store_true",
        help="回滚到JSON索引"
    )
    
    args = parser.parse_args()
    
    # 检查路径
    if not os.path.isdir(args.path):
        logger.error(f"目录不存在: {args.path}")
        sys.exit(1)
    
    if args.rollback:
        success = rollback(args.path)
    elif args.compare:
        success = compare_search_results(args.path)
    else:
        success = migrate_json_to_sqlite(args.path, args.force)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()