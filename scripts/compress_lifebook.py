"""
LifeBook 记忆压缩工作流
=======================
功能：
1. 完整备份 lifebook 到 backups 目录（压缩包）
2. 删除可重建的索引/缓存文件
3. 可选：LLM 压缩 daily/weekly/monthly 文本
4. 可选：清理 conversations 中的图片附件
5. 生成压缩报告

用法：
  python scripts/compress_lifebook.py              # 完整流程（交互式确认）
  python scripts/compress_lifebook.py --dry-run    # 预览模式，不实际修改
  python scripts/compress_lifebook.py --no-llm     # 跳过 LLM 压缩
  python scripts/compress_lifebook.py --no-images  # 同时清理图片
"""

import os
import sys
import shutil
import json
import zipfile
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIFEBOOK_PATH = PROJECT_ROOT / "lifebook"
BACKUPS_PATH = PROJECT_ROOT / "backups"

# 可安全删除的索引/缓存文件（可通过重建恢复）
RECONSTRUCTABLE_PATTERNS = [
    ".rag_index",           # RAG 向量索引
    ".graphiti.kuzu",       # Graphiti 图数据库
    ".graphiti.kuzu.wal",   # Graphiti WAL 日志
    ".memory_index.db",     # SQLite 记忆索引
    ".memory_index.json",   # JSON 记忆索引
    ".memory_index.json.backup_*",  # 索引备份
    "debug_logs",           # 调试日志
]

# 需要 LLM 压缩的目录
TEXT_DIRS_TO_COMPRESS = ["daily", "weekly", "monthly", "quarterly", "yearly"]


def get_dir_size(path: Path) -> tuple:
    """获取目录大小和文件数"""
    total_size = 0
    file_count = 0
    if path.is_file():
        return path.stat().st_size, 1
    for f in path.rglob("*"):
        if f.is_file():
            total_size += f.stat().st_size
            file_count += 1
    return total_size, file_count


def format_size(size_bytes: int) -> str:
    """人性化显示大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def backup_lifebook(dry_run: bool = False) -> Optional[Path]:
    """
    将整个 lifebook 目录打包备份到 backups/lifebook_full_YYYYMMDD_HHMMSS.zip
    返回备份文件路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"lifebook_full_{timestamp}.zip"
    backup_path = BACKUPS_PATH / backup_name

    if dry_run:
        total_size, file_count = get_dir_size(LIFEBOOK_PATH)
        print(f"  [预览] 将备份 {file_count} 个文件 ({format_size(total_size)})")
        print(f"  [预览] 备份到: {backup_path}")
        return backup_path

    print(f"📦 正在备份 lifebook → {backup_name} ...")
    BACKUPS_PATH.mkdir(parents=True, exist_ok=True)

    total_size, file_count = get_dir_size(LIFEBOOK_PATH)
    print(f"   源目录: {file_count} 个文件, {format_size(total_size)}")

    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in LIFEBOOK_PATH.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(LIFEBOOK_PATH.parent)
                zf.write(file_path, arcname)

    backup_size = backup_path.stat().st_size
    print(f"   ✅ 备份完成: {format_size(backup_size)} (压缩率 {backup_size/total_size*100:.1f}%)")
    return backup_path


def clean_reconstructable(dry_run: bool = False) -> dict:
    """清理可重建的索引和缓存文件"""
    results = {}
    for pattern in RECONSTRUCTABLE_PATTERNS:
        if "*" in pattern:
            # 通配符匹配
            matched = list(LIFEBOOK_PATH.glob(pattern))
            for p in matched:
                size = get_dir_size(p)[0] if p.exists() else 0
                results[str(p.relative_to(LIFEBOOK_PATH))] = size
                if not dry_run and p.exists():
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                    print(f"   🗑️  已删除: {p.relative_to(LIFEBOOK_PATH)} ({format_size(size)})")
                elif dry_run:
                    print(f"   [预览] 将删除: {p.relative_to(LIFEBOOK_PATH)} ({format_size(size)})")
        else:
            p = LIFEBOOK_PATH / pattern
            if p.exists():
                size = get_dir_size(p)[0]
                results[str(p.relative_to(LIFEBOOK_PATH))] = size
                if not dry_run:
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                    print(f"   🗑️  已删除: {pattern} ({format_size(size)})")
                else:
                    print(f"   [预览] 将删除: {pattern} ({format_size(size)})")
    return results


def compress_text_with_llm(file_path: Path, model_config: dict, dry_run: bool = False) -> bool:
    """
    使用 LLM 压缩单个文本文件（保留关键信息）
    当前为占位实现，需要配合 proxy_server 的 API
    """
    if dry_run:
        print(f"   [预览] 将压缩: {file_path.relative_to(LIFEBOOK_PATH)}")
        return True

    # TODO: 实际 LLM 压缩逻辑
    # 1. 读取文件内容
    # 2. 调用 LLM API 进行摘要压缩
    # 3. 写回压缩后的内容
    print(f"   ⏭️  跳过 LLM 压缩（功能开发中）: {file_path.name}")
    return False


def clean_conversation_images(dry_run: bool = False) -> dict:
    """清理 conversations 中的图片附件（保留 JSONL 对话记录）"""
    removed_size = 0
    removed_count = 0
    conv_path = LIFEBOOK_PATH / "conversations"

    if not conv_path.exists():
        return {"size": 0, "count": 0}

    for date_dir in conv_path.iterdir():
        if not date_dir.is_dir():
            continue
        images_dir = date_dir / "images"
        if images_dir.exists():
            size, count = get_dir_size(images_dir)
            removed_size += size
            removed_count += count
            if not dry_run:
                shutil.rmtree(images_dir)
                print(f"   🗑️  已删除图片: {date_dir.name}/images ({format_size(size)}, {count} 文件)")
            else:
                print(f"   [预览] 将删除图片: {date_dir.name}/images ({format_size(size)}, {count} 文件)")

    return {"size": removed_size, "count": removed_count}


def generate_report(before_size: int, after_size: int, operations: list) -> str:
    """生成压缩报告"""
    saved = before_size - after_size
    pct = (saved / before_size * 100) if before_size > 0 else 0

    report = f"""
╔══════════════════════════════════════════════════╗
║        LifeBook 记忆压缩报告                    ║
╠══════════════════════════════════════════════════╣
║  压缩前大小:  {format_size(before_size):>18}      ║
║  压缩后大小:  {format_size(after_size):>18}      ║
║  节省空间:    {format_size(saved):>18} ({pct:.1f}%) ║
╠══════════════════════════════════════════════════╣
║  执行操作:                                       ║
"""
    for op in operations:
        report += f"║    • {op:<44} ║\n"

    report += """╚══════════════════════════════════════════════════╝
"""
    return report


def main():
    parser = argparse.ArgumentParser(description="LifeBook 记忆压缩工作流")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 文本压缩")
    parser.add_argument("--no-images", action="store_true", help="清理 conversations 中的图片")
    parser.add_argument("--skip-backup", action="store_true", help="跳过备份步骤（危险！）")
    args = parser.parse_args()

    if not LIFEBOOK_PATH.exists():
        print(f"❌ lifebook 目录不存在: {LIFEBOOK_PATH}")
        sys.exit(1)

    print("=" * 60)
    print("  LifeBook 记忆压缩工作流")
    print("=" * 60)

    # 记录压缩前大小
    before_size, before_count = get_dir_size(LIFEBOOK_PATH)
    print(f"\n📊 当前状态: {before_count} 个文件, {format_size(before_size)}")

    operations_log = []

    # === 步骤 1：备份 ===
    print(f"\n{'='*40}")
    print("  步骤 1/4: 备份原文")
    print(f"{'='*40}")
    if not args.skip_backup:
        backup_path = backup_lifebook(dry_run=args.dry_run)
        if backup_path:
            operations_log.append(f"备份到 {backup_path.name}")
    else:
        print("   ⚠️  已跳过备份！（--skip-backup）")

    # === 步骤 2：清理索引/缓存 ===
    print(f"\n{'='*40}")
    print("  步骤 2/4: 清理可重建的索引和缓存")
    print(f"{'='*40}")
    cleaned = clean_reconstructable(dry_run=args.dry_run)
    total_cleaned = sum(cleaned.values())
    if total_cleaned > 0:
        operations_log.append(f"清理索引/缓存: {format_size(total_cleaned)}")
    else:
        print("   (无可清理项)")

    # === 步骤 3：可选的图片清理 ===
    if args.no_images:
        print(f"\n{'='*40}")
        print("  步骤 3/4: 清理 conversations 图片")
        print(f"{'='*40}")
        img_result = clean_conversation_images(dry_run=args.dry_run)
        if img_result["size"] > 0:
            operations_log.append(f"清理图片: {format_size(img_result['size'])} ({img_result['count']} 文件)")

    # === 步骤 4：LLM 文本压缩 ===
    if not args.no_llm:
        print(f"\n{'='*40}")
        print("  步骤 4/4: LLM 文本压缩")
        print(f"{'='*40}")
        print("   ⚠️  LLM 压缩功能尚未实现，此步骤跳过")
        print("   提示: 可手动将 daily/ 目录下的日记用 LLM 做摘要压缩")
    else:
        print(f"\n   ⏭️  已跳过 LLM 压缩（--no-llm）")

    # === 最终报告 ===
    if not args.dry_run:
        after_size, after_count = get_dir_size(LIFEBOOK_PATH)
    else:
        # 预览模式估算
        estimate_saved = sum(cleaned.values())
        after_size = before_size - estimate_saved
        after_count = before_count

    print(generate_report(before_size, after_size, operations_log))

    if args.dry_run:
        print("💡 这是预览模式。去掉 --dry-run 以实际执行。")

    # 保存压缩日志
    log_path = BACKUPS_PATH / f"compress_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    if not args.dry_run:
        BACKUPS_PATH.mkdir(parents=True, exist_ok=True)
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "before_size": before_size,
            "after_size": after_size,
            "operations": operations_log,
        }
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
        print(f"📝 压缩日志已保存: {log_path}")


if __name__ == "__main__":
    main()
