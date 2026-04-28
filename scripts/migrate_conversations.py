#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对话文件迁移脚本

将旧的扁平结构迁移到日期子目录结构：
  旧: lifebook/conversations/2026-01-22_185629_a7b27ae4.jsonl
  新: lifebook/conversations/2026-01-22/185629_a7b27ae4.jsonl
"""

import os
import sys
import shutil
from pathlib import Path
from datetime import datetime

# Windows 终端编码问题
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def is_date_format(name: str) -> bool:
    """检查是否为日期格式 YYYY-MM-DD"""
    if len(name) != 10:
        return False
    try:
        datetime.strptime(name, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def migrate_conversations(conv_dir: Path, dry_run: bool = True):
    """
    迁移对话文件到日期子目录结构
    
    Args:
        conv_dir: 对话目录路径
        dry_run: 是否为试运行（不实际移动文件）
    """
    if not conv_dir.exists():
        print(f"[ERROR] 目录不存在: {conv_dir}")
        return
    
    # 收集需要迁移的文件
    files_to_migrate = []
    
    for f in conv_dir.glob("*.jsonl"):
        if not f.is_file():
            continue
        
        try:
            # 解析文件名: YYYY-MM-DD_HHMMSS_xxx.jsonl
            parts = f.stem.split('_')
            if len(parts) < 2:
                print(f"[SKIP] 格式不符: {f.name}")
                continue
            
            date_part = parts[0]
            if not is_date_format(date_part):
                print(f"[SKIP] 日期格式不符: {f.name}")
                continue
            
            # 新文件名（去掉日期前缀）
            new_name = '_'.join(parts[1:]) + '.jsonl'
            target_dir = conv_dir / date_part
            target_path = target_dir / new_name
            
            files_to_migrate.append({
                'source': f,
                'target': target_path,
                'date': date_part
            })
            
        except Exception as e:
            print(f"[WARN] 解析失败 {f.name}: {e}")
    
    if not files_to_migrate:
        print("[OK] 没有需要迁移的文件")
        return
    
    print(f"\n找到 {len(files_to_migrate)} 个文件需要迁移:\n")
    
    # 按日期分组显示
    dates = {}
    for item in files_to_migrate:
        date = item['date']
        if date not in dates:
            dates[date] = []
        dates[date].append(item)
    
    for date in sorted(dates.keys()):
        print(f"  [{date}]: {len(dates[date])} 个文件")
        for item in dates[date][:3]:  # 只显示前3个
            print(f"      {item['source'].name} -> {item['target'].name}")
        if len(dates[date]) > 3:
            print(f"      ... 还有 {len(dates[date]) - 3} 个文件")
    
    if dry_run:
        print("\n[DRY RUN] 这是试运行，不会实际移动文件")
        print("   使用 --execute 参数执行实际迁移")
        return
    
    # 执行迁移
    print("\n开始迁移...\n")
    
    success_count = 0
    error_count = 0
    
    for item in files_to_migrate:
        try:
            # 创建日期目录
            item['target'].parent.mkdir(parents=True, exist_ok=True)
            
            # 移动文件
            shutil.move(str(item['source']), str(item['target']))
            
            print(f"  [OK] {item['source'].name} -> {item['target']}")
            success_count += 1
            
        except Exception as e:
            print(f"  [ERROR] {item['source'].name}: {e}")
            error_count += 1
    
    print(f"\n迁移完成: 成功 {success_count}, 失败 {error_count}")


def main():
    # 确定对话目录
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # 默认路径
    conv_dir = project_root / "lifebook" / "conversations"
    
    # 检查命令行参数
    dry_run = True
    
    for arg in sys.argv[1:]:
        if arg == '--execute':
            dry_run = False
        elif arg == '--help' or arg == '-h':
            print(__doc__)
            print("\n用法: python migrate_conversations.py [选项]")
            print("\n选项:")
            print("  --execute   执行实际迁移（默认为试运行）")
            print("  --help      显示帮助信息")
            return
        elif not arg.startswith('-'):
            conv_dir = Path(arg)
    
    print(f"对话目录: {conv_dir}")
    print(f"模式: {'试运行' if dry_run else '执行迁移'}")
    
    migrate_conversations(conv_dir, dry_run)


if __name__ == '__main__':
    main()