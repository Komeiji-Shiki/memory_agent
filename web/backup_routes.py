"""
备份/恢复 API 路由
"""

import os
import re
import shutil
import zipfile
import tempfile
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from .core import (
    get_lifebook_path, get_backup_path, get_indexer, 
    MAX_UPLOAD_SIZE, MAX_ZIP_FILES, MAX_ZIP_RATIO
)

# 创建蓝图
backup_bp = Blueprint('backup_api', __name__)


def _validate_zip_file(file_path: str) -> tuple:
    """
    验证zip文件安全性
    
    检查：
    1. 文件数量不超过限制
    2. 解压后大小不超过原始大小的 MAX_ZIP_RATIO 倍（防止zip炸弹）
    3. 不包含路径遍历攻击（..）
    4. 只包含预期的目录结构
    
    Returns:
        (is_valid, error_message, file_count)
    """
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            # 检查文件数量
            file_list = zf.namelist()
            if len(file_list) > MAX_ZIP_FILES:
                return False, f"zip文件包含过多文件（{len(file_list)} > {MAX_ZIP_FILES}）", 0
            
            # 检查路径遍历
            for name in file_list:
                if '..' in name or name.startswith('/'):
                    return False, f"检测到危险路径: {name}", 0
            
            # 检查压缩比（防止zip炸弹）
            compressed_size = os.path.getsize(file_path)
            uncompressed_size = sum(info.file_size for info in zf.infolist())
            
            if compressed_size > 0:
                ratio = uncompressed_size / compressed_size
                if ratio > MAX_ZIP_RATIO:
                    return False, f"压缩比异常（{ratio:.1f}x），可能是zip炸弹", 0
            
            # 检查目录结构
            valid_prefixes = ('daily/', 'weekly/', 'monthly/', 'quarterly/', 'yearly/',
                            'nodes/', 'pending/', '.rag_index/', '.memory_index')
            has_valid_structure = any(
                any(name.startswith(prefix) for prefix in valid_prefixes)
                for name in file_list
            )
            
            if not has_valid_structure and file_list:
                has_md = any(name.endswith('.md') for name in file_list)
                if not has_md:
                    return False, "zip文件不包含有效的 lifebook 备份结构", 0
            
            return True, "", len(file_list)
            
    except zipfile.BadZipFile:
        return False, "无效的zip文件", 0
    except Exception as e:
        return False, f"验证失败: {str(e)}", 0


@backup_bp.route('/backup', methods=['POST'])
def create_backup():
    """创建备份"""
    lifebook_path = get_lifebook_path()
    backup_path = get_backup_path()
    
    try:
        from .backup import create_backup as do_backup
        result = do_backup(lifebook_path, backup_path)
        return jsonify(result)
    except ImportError:
        os.makedirs(backup_path, exist_ok=True)
        backup_name = f"lifebook_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        backup_file = os.path.join(backup_path, backup_name)
        
        shutil.make_archive(
            backup_file.replace('.zip', ''),
            'zip',
            lifebook_path
        )
        
        return jsonify({
            "success": True,
            "backup_file": backup_file,
            "created_at": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@backup_bp.route('/backups', methods=['GET'])
def list_backups():
    """列出备份"""
    backup_path = get_backup_path()
    
    if not backup_path or not os.path.exists(backup_path):
        return jsonify({"backups": []})
    
    backups = []
    for f in os.listdir(backup_path):
        if f.endswith('.zip'):
            file_path = os.path.join(backup_path, f)
            stat = os.stat(file_path)
            backups.append({
                "name": f,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
    
    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify({"backups": backups})


@backup_bp.route('/restore', methods=['POST'])
def restore_backup():
    """恢复备份"""
    lifebook_path = get_lifebook_path()
    backup_path = get_backup_path()
    indexer = get_indexer()
    
    try:
        data = request.get_json()
        backup_name = data.get('backup_name')
        
        if not backup_name:
            return jsonify({"error": "缺少 backup_name 参数"}), 400
        
        backup_file = os.path.join(backup_path, backup_name)
        
        if not os.path.exists(backup_file):
            return jsonify({"error": f"备份文件 {backup_name} 不存在"}), 404
        
        try:
            from .backup import restore_backup as do_restore
            
            result = do_restore(backup_file, lifebook_path, overwrite=True)
            
            if result.get('success'):
                if indexer:
                    indexer.rebuild_index()
                
                return jsonify({
                    "success": True,
                    "message": f"备份 {backup_name} 恢复成功",
                    "restored_path": result.get('target_path'),
                    "file_count": result.get('file_count', 0)
                })
            else:
                return jsonify({"error": result.get('error', '恢复失败')}), 500
                
        except ImportError:
            # 回退：使用 zipfile 手动解压
            for item in os.listdir(lifebook_path):
                item_path = os.path.join(lifebook_path, item)
                if item.startswith('.'):
                    continue
                if os.path.isfile(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            
            with zipfile.ZipFile(backup_file, 'r') as zf:
                zf.extractall(lifebook_path)
            
            if indexer:
                indexer.rebuild_index()
            
            return jsonify({
                "success": True,
                "message": f"备份 {backup_name} 恢复成功",
                "restored_path": lifebook_path
            })
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@backup_bp.route('/backup/<name>', methods=['DELETE'])
def delete_backup(name: str):
    """删除指定备份"""
    backup_path = get_backup_path()
    
    try:
        backup_file = os.path.join(backup_path, name)
        
        if not os.path.exists(backup_file):
            return jsonify({"error": f"备份文件 {name} 不存在"}), 404
        
        os.remove(backup_file)
        
        return jsonify({
            "success": True,
            "message": f"备份 {name} 已删除"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@backup_bp.route('/backup/<name>/download', methods=['GET'])
def download_backup(name: str):
    """下载备份文件"""
    backup_path = get_backup_path()
    
    try:
        # 安全检查
        if '..' in name or '/' in name or '\\' in name:
            return jsonify({"error": "无效的文件名"}), 400
        
        backup_file = os.path.join(backup_path, name)
        
        if not os.path.exists(backup_file):
            return jsonify({"error": f"备份文件 {name} 不存在"}), 404
        
        return send_file(
            backup_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=name
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@backup_bp.route('/backup/upload', methods=['POST'])
def upload_and_restore_backup():
    """上传备份文件并恢复"""
    lifebook_path = get_lifebook_path()
    backup_path = get_backup_path()
    indexer = get_indexer()
    
    try:
        if 'file' not in request.files:
            return jsonify({"error": "未上传文件"}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({"error": "未选择文件"}), 400
        
        if not file.filename.endswith('.zip'):
            return jsonify({"error": "仅支持 .zip 格式的备份文件"}), 400
        
        # 安全检查：文件大小限制
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_UPLOAD_SIZE:
            return jsonify({
                "error": f"文件过大（{file_size / 1024 / 1024:.1f}MB > {MAX_UPLOAD_SIZE / 1024 / 1024}MB）"
            }), 400
        
        do_restore = request.form.get('restore', 'true').lower() == 'true'
        
        os.makedirs(backup_path, exist_ok=True)
        
        # 先保存到临时文件进行验证
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
            file.save(tmp.name)
            temp_path = tmp.name
        
        try:
            # 验证zip文件安全性
            is_valid, error_msg, file_count = _validate_zip_file(temp_path)
            if not is_valid:
                os.unlink(temp_path)
                return jsonify({"error": f"安全检查失败: {error_msg}"}), 400
            
            # 生成唯一文件名
            safe_name = re.sub(r'[^\w\-\.]', '_', file.filename)
            base_name = safe_name if safe_name.endswith('.zip') else safe_name + '.zip'
            save_path = os.path.join(backup_path, base_name)
            counter = 1
            while os.path.exists(save_path):
                name_part = base_name.rsplit('.', 1)[0]
                save_path = os.path.join(backup_path, f"{name_part}_{counter}.zip")
                counter += 1
            
            shutil.move(temp_path, save_path)
            saved_name = os.path.basename(save_path)
            
            if do_restore:
                # 清空目标目录（保留隐藏文件）
                for item in os.listdir(lifebook_path):
                    item_path = os.path.join(lifebook_path, item)
                    if item.startswith('.'):
                        continue
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                
                # 安全解压
                with zipfile.ZipFile(save_path, 'r') as zf:
                    zf.extractall(lifebook_path)
                
                if indexer:
                    indexer.rebuild_index()
                
                return jsonify({
                    "success": True,
                    "message": f"备份 {saved_name} 已上传并恢复成功（{file_count} 个文件）",
                    "backup_file": saved_name,
                    "restored": True,
                    "file_count": file_count
                })
            else:
                return jsonify({
                    "success": True,
                    "message": f"备份 {saved_name} 已上传（{file_count} 个文件）",
                    "backup_file": saved_name,
                    "restored": False,
                    "file_count": file_count
                })
                
        except Exception as e:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500