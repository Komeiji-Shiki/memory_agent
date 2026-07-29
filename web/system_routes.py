"""
系统运维 API 路由

提供服务自身的运维操作（当前仅重启）。
修改后端 Python 代码后无需手动到控制台重启，面板/命令面板一键完成。
"""

import os
import sys
import logging
import threading
import subprocess

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

# 创建蓝图
system_bp = Blueprint('system_api', __name__)


def _do_restart():
    """执行进程自重启

    Windows：以新控制台启动 detached 子进程，延迟约 2 秒等待当前进程
    退出并释放端口后再拉起服务（execv 在 Windows 上对含空格的解释器路径
    有参数拼接缺陷，且继承旧控制台会随窗口关闭被终止，故不采用）。
    其他平台：直接 execv 原地替换进程。
    """
    argv = [sys.executable] + sys.argv
    logger.info(f"[系统] 服务重启: {argv}")

    if os.name == 'nt':
        quoted = ' '.join(f'"{a}"' for a in argv)
        # ping -n 3 约等待 2 秒，确保旧进程已退出、端口已释放
        subprocess.Popen(
            f'ping 127.0.0.1 -n 3 >nul && {quoted}',
            shell=True,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=os.getcwd(),
        )
        os._exit(0)
    else:
        os.execv(sys.executable, argv)


@system_bp.route('/system/restart', methods=['POST'])
def restart_service():
    """重启代理服务（先返回响应，随后自重启）"""
    # 延迟执行，保证本次 HTTP 响应先送达客户端
    threading.Timer(0.8, _do_restart).start()
    return jsonify({
        "success": True,
        "message": "服务即将重启，约 5 秒后恢复"
    })
