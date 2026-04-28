"""
Backup Tool - 备份和恢复工具

支持：
- 创建备份（zip格式）
- 恢复备份
- 自动清理旧备份
- 增量备份（可选）
"""

import os
import shutil
import zipfile
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path


def create_backup(
    source_path: str,
    backup_path: str,
    backup_name: Optional[str] = None,
    include_index: bool = True
) -> Dict[str, Any]:
    """
    创建备份
    
    Args:
        source_path: 源目录（LifeBook路径）
        backup_path: 备份目录
        backup_name: 备份文件名（不含扩展名），默认自动生成
        include_index: 是否包含索引文件
        
    Returns:
        备份结果信息
    """
    source = Path(source_path)
    backup_dir = Path(backup_path)
    
    if not source.exists():
        return {"success": False, "error": "源目录不存在"}
    
    # 确保备份目录存在
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成备份文件名
    if not backup_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"lifebook_backup_{timestamp}"
    
    backup_file = backup_dir / f"{backup_name}.zip"
    
    try:
        # 统计文件
        file_count = 0
        total_size = 0
        
        with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(source):
                # 跳过隐藏目录（如 .git）
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    # 跳过隐藏文件
                    if file.startswith('.') and not include_index:
                        continue
                    
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(source)
                    
                    zf.write(file_path, arcname)
                    file_count += 1
                    total_size += file_path.stat().st_size
        
        return {
            "success": True,
            "backup_file": str(backup_file),
            "file_count": file_count,
            "total_size": total_size,
            "compressed_size": backup_file.stat().st_size,
            "created_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> int:
    """
    安全解压 zip 文件，防止路径遍历攻击（Zip Slip）
    
    Args:
        zf: ZipFile 对象
        target: 目标目录
        
    Returns:
        解压的文件数量
        
    Raises:
        ValueError: 如果检测到恶意路径
    """
    file_count = 0
    target_abs = target.resolve()
    
    for member in zf.namelist():
        # 规范化路径
        member_path = os.path.normpath(member)
        
        # 检查绝对路径
        if os.path.isabs(member_path):
            raise ValueError(f"拒绝绝对路径: {member}")
        
        # 检查路径遍历
        if member_path.startswith('..') or '/../' in member_path:
            raise ValueError(f"检测到路径遍历攻击: {member}")
        
        # 计算目标路径并验证
        dest = target_abs / member_path
        dest_abs = dest.resolve()
        
        # 确保解压目标在目标目录内
        try:
            dest_abs.relative_to(target_abs)
        except ValueError:
            raise ValueError(f"路径逃逸目标目录: {member}")
        
        # 安全解压单个文件
        zf.extract(member, target)
        file_count += 1
    
    return file_count


def restore_backup(
    backup_file: str,
    target_path: str,
    overwrite: bool = False
) -> Dict[str, Any]:
    """
    恢复备份
    
    Args:
        backup_file: 备份文件路径
        target_path: 恢复目标目录
        overwrite: 是否覆盖已存在的文件
        
    Returns:
        恢复结果信息
        
    Security:
        使用 _safe_extract 防止 Zip Slip 路径遍历攻击
    """
    backup = Path(backup_file)
    target = Path(target_path)
    
    if not backup.exists():
        return {"success": False, "error": "备份文件不存在"}
    
    if not backup.suffix == '.zip':
        return {"success": False, "error": "不是有效的备份文件"}
    
    try:
        # 如果目标目录存在且不覆盖
        if target.exists() and not overwrite:
            # 创建备份目录的子目录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = target / f"restored_{timestamp}"
        
        target.mkdir(parents=True, exist_ok=True)
        
        file_count = 0
        with zipfile.ZipFile(backup, 'r') as zf:
            # 使用安全解压代替 extractall
            file_count = _safe_extract(zf, target)
        
        return {
            "success": True,
            "target_path": str(target),
            "file_count": file_count,
            "restored_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_backups(backup_path: str) -> List[Dict[str, Any]]:
    """
    列出所有备份
    
    Args:
        backup_path: 备份目录
        
    Returns:
        备份列表
    """
    backup_dir = Path(backup_path)
    
    if not backup_dir.exists():
        return []
    
    backups = []
    for f in backup_dir.glob("*.zip"):
        stat = f.stat()
        backups.append({
            "name": f.name,
            "path": str(f),
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    
    # 按创建时间降序排序
    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return backups


def cleanup_old_backups(
    backup_path: str,
    keep_count: int = 30,
    keep_days: Optional[int] = None
) -> Dict[str, Any]:
    """
    清理旧备份
    
    Args:
        backup_path: 备份目录
        keep_count: 保留最近N个备份
        keep_days: 保留最近N天的备份（与keep_count取并集）
        
    Returns:
        清理结果
    """
    backups = list_backups(backup_path)
    
    if not backups:
        return {"deleted": 0, "kept": 0}
    
    # 确定要保留的备份
    keep_set = set()
    
    # 按数量保留
    for backup in backups[:keep_count]:
        keep_set.add(backup['name'])
    
    # 按天数保留
    if keep_days:
        cutoff = datetime.now() - timedelta(days=keep_days)
        for backup in backups:
            backup_time = datetime.fromisoformat(backup['created_at'])
            if backup_time > cutoff:
                keep_set.add(backup['name'])
    
    # 删除不需要保留的
    deleted = 0
    for backup in backups:
        if backup['name'] not in keep_set:
            try:
                os.remove(backup['path'])
                deleted += 1
            except Exception:
                pass
    
    return {
        "deleted": deleted,
        "kept": len(keep_set),
        "total_before": len(backups)
    }


def get_backup_info(backup_file: str) -> Dict[str, Any]:
    """
    获取备份文件信息
    
    Args:
        backup_file: 备份文件路径
        
    Returns:
        备份信息
    """
    backup = Path(backup_file)
    
    if not backup.exists():
        return {"error": "文件不存在"}
    
    try:
        with zipfile.ZipFile(backup, 'r') as zf:
            files = zf.namelist()
            
            # 统计各类文件
            file_types = {
                "daily": 0,
                "weekly": 0,
                "monthly": 0,
                "nodes": 0,
                "other": 0
            }
            
            for f in files:
                if f.startswith("daily/"):
                    file_types["daily"] += 1
                elif f.startswith("weekly/"):
                    file_types["weekly"] += 1
                elif f.startswith("monthly/"):
                    file_types["monthly"] += 1
                elif f.startswith("nodes/"):
                    file_types["nodes"] += 1
                else:
                    file_types["other"] += 1
            
            return {
                "name": backup.name,
                "size": backup.stat().st_size,
                "file_count": len(files),
                "file_types": file_types,
                "created_at": datetime.fromtimestamp(backup.stat().st_mtime).isoformat()
            }
            
    except Exception as e:
        return {"error": str(e)}


# CLI接口
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="LifeBook 备份工具")
    subparsers = parser.add_subparsers(dest='command')
    
    # 备份命令
    backup_parser = subparsers.add_parser('backup', help='创建备份')
    backup_parser.add_argument('source', help='LifeBook目录')
    backup_parser.add_argument('-o', '--output', default='./backups', help='备份输出目录')
    backup_parser.add_argument('-n', '--name', help='备份文件名')
    
    # 恢复命令
    restore_parser = subparsers.add_parser('restore', help='恢复备份')
    restore_parser.add_argument('backup_file', help='备份文件')
    restore_parser.add_argument('target', help='恢复目标目录')
    restore_parser.add_argument('--overwrite', action='store_true', help='覆盖已存在的文件')
    
    # 列表命令
    list_parser = subparsers.add_parser('list', help='列出备份')
    list_parser.add_argument('backup_dir', help='备份目录')
    
    # 清理命令
    clean_parser = subparsers.add_parser('clean', help='清理旧备份')
    clean_parser.add_argument('backup_dir', help='备份目录')
    clean_parser.add_argument('-k', '--keep', type=int, default=30, help='保留数量')
    
    args = parser.parse_args()
    
    if args.command == 'backup':
        result = create_backup(args.source, args.output, args.name)
        if result['success']:
            print(f"✓ 备份成功: {result['backup_file']}")
            print(f"  文件数: {result['file_count']}")
            print(f"  压缩后大小: {result['compressed_size'] / 1024:.1f} KB")
        else:
            print(f"✗ 备份失败: {result['error']}")
    
    elif args.command == 'restore':
        result = restore_backup(args.backup_file, args.target, args.overwrite)
        if result['success']:
            print(f"✓ 恢复成功: {result['target_path']}")
            print(f"  文件数: {result['file_count']}")
        else:
            print(f"✗ 恢复失败: {result['error']}")
    
    elif args.command == 'list':
        backups = list_backups(args.backup_dir)
        if backups:
            print(f"找到 {len(backups)} 个备份:")
            for b in backups:
                size_kb = b['size'] / 1024
                print(f"  - {b['name']} ({size_kb:.1f} KB) - {b['created_at']}")
        else:
            print("没有找到备份")
    
    elif args.command == 'clean':
        result = cleanup_old_backups(args.backup_dir, args.keep)
        print(f"清理完成: 删除 {result['deleted']} 个, 保留 {result['kept']} 个")
    
    else:
        parser.print_help()