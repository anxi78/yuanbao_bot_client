#!/usr/bin/env python3
"""
元宝 Bot 增强发送器 - 完整可视化界面
集成所有命令行功能，支持电脑端+手机端
文件数量：5个以内
"""

import sys
import os
import json
import asyncio
import threading
import traceback
import uuid
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Callable
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

# 导入原发送器核心
from sender import (
    SpamSender, SimpleProtobufCodec, encode_conn_msg, decode_conn_msg,
    CMD_TYPE_REQUEST, CMD_TYPE_RESPONSE, CMD_TYPE_PUSH,
    BIZ_CMD_SEND_GROUP, BIZ_CMD_GET_MEMBERS, MODULE_CONN_ACCESS,
    BIZ_MODULE, CMD_AUTH_BIND, CMD_PING, BIZ_CMD_SEND_C2C
)

# 从config.json加载配置
try:
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
        APP_KEY = config.get('APP_KEY', '')
        APP_SECRET = config.get('APP_SECRET', '')
        API_DOMAIN = config.get('API_DOMAIN', '')
        WS_URL = config.get('WS_URL', '')
        DEFAULT_GROUP_CODE = config.get('DEFAULT_GROUP_CODE', '')
        AUTO_REPLY_GROUP_TEXT = config.get('AUTO_REPLY_GROUP_TEXT', '')
        AUTO_REPLY_C2C_TEXT = config.get('AUTO_REPLY_C2C_TEXT', '')
        AUTO_REPLY_RULES = config.get('AUTO_REPLY_RULES', [])
        DEFAULT_REPLY = config.get('DEFAULT_REPLY', '')
except Exception as e:
    print(f"加载配置失败: {e}")
    APP_KEY = APP_SECRET = API_DOMAIN = WS_URL = DEFAULT_GROUP_CODE = ""
    AUTO_REPLY_GROUP_TEXT = AUTO_REPLY_C2C_TEXT = DEFAULT_REPLY = ""
    AUTO_REPLY_RULES = []


class AsyncBridge(QObject):
    """异步任务桥接器，在UI线程中运行异步代码"""
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, coro):
        super().__init__()
        self.coro = coro
    
    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.coro)
            loop.close()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    # 定义信号
    async_result = Signal(object)
    async_error = Signal(str)
    
    def send_image(self):
        """发送图片（统一方法）"""
        if self.is_mobile:
            self.send_image_mobile()
        else:
            self.send_image_message()

    def __init__(self):
        super().__init__()
        self.sender = None
        self.current_group = DEFAULT_GROUP_CODE
        self.message_history = []
        self.user_list = []  # [(user_id, nickname), ...]
        self.sticker_buttons = []
        self.is_connected = False
        self.auto_reply_enabled = False
        self.spam_interval = 1.0
        self._pending_callbacks = {}  # 保存临时回调
        
        # 响应式设计：检测屏幕尺寸
        screen = QApplication.primaryScreen()
        self.screen_width = screen.size().width()
        self.is_mobile = self.screen_width < 768  # 小于768px视为手机
        
        # 连接信号
        self.async_result.connect(self.on_async_result)
        self.async_error.connect(self.on_async_error)
        
        self.init_ui()
        self.init_async_loop()
    
    def init_async_loop(self):
        """初始化异步事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.async_thread = threading.Thread(target=self.run_async_loop, daemon=True)
        self.async_thread.start()
    
    def run_async_loop(self):
        """运行异步事件循环"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    
    def run_async(self, coro, callback=None, error_callback=None):
        """在异步线程中运行协程"""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if callback or error_callback:
            # 生成一个唯一的ID来追踪回调
            cb_id = id(future)
            self._pending_callbacks[cb_id] = (callback, error_callback)
            future.add_done_callback(
                lambda f: self.handle_async_result(f, cb_id)
            )
        return future
    
    def handle_async_result(self, future, callback_id):
        """处理异步结果"""
        try:
            result = future.result()
            callback, _ = self._pending_callbacks.get(callback_id, (None, None))
            if callback:
                self.async_result.emit((callback, result))
        except Exception as e:
            _, error_callback = self._pending_callbacks.get(callback_id, (None, None))
            if error_callback:
                self.async_error.emit((error_callback, str(e)))
        finally:
            # 清理
            self._pending_callbacks.pop(callback_id, None)
    
    def on_async_result(self, data):
        """异步成功回调"""
        callback, result = data
        if callable(callback):
            try:
                callback(result)
            except Exception as e:
                print(f"回调执行错误: {e}")
    
    def on_async_error(self, data):
        """异步错误回调"""
        callback, error_msg = data
        if callable(callback):
            try:
                callback(error_msg)
            except Exception as e:
                print(f"错误回调执行错误: {e}")
    
    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("元宝 Bot 增强发送器")
        
        # 设置窗口大小
        if self.is_mobile:
            self.setGeometry(0, 0, 400, 800)
            self.setStyleSheet("""
                QMainWindow { background-color: #f5f5f5; }
                QWidget { font-size: 16px; }
                QPushButton { 
                    background-color: #4CAF50; 
                    color: white; 
                    border: none; 
                    padding: 12px; 
                    border-radius: 6px;
                    font-size: 18px;
                    margin: 2px;
                }
                QPushButton:hover { background-color: #45a049; }
                QLineEdit, QTextEdit { 
                    border: 1px solid #ddd; 
                    padding: 10px; 
                    border-radius: 6px; 
                    font-size: 18px;
                }
                QListWidget { 
                    font-size: 16px; 
                    border: 1px solid #ddd; 
                    border-radius: 6px;
                }
                QGroupBox { 
                    font-weight: bold; 
                    border: 2px solid #4CAF50; 
                    border-radius: 8px; 
                    margin-top: 10px;
                }
                QGroupBox::title { 
                    subcontrol-origin: margin; 
                    left: 10px; 
                    padding: 0 5px 0 5px; 
                }
            """)
        else:
            self.setGeometry(100, 100, 1200, 800)
            self.setStyleSheet("""
                QMainWindow { background-color: #f0f0f0; }
                QPushButton { 
                    background-color: #2196F3; 
                    color: white; 
                    border: none; 
                    padding: 8px 16px; 
                    border-radius: 4px;
                }
                QPushButton:hover { background-color: #1976D2; }
                QPushButton:disabled { background-color: #ccc; }
                QLineEdit, QTextEdit { 
                    border: 1px solid #ccc; 
                    padding: 6px; 
                    border-radius: 4px; 
                }
                QGroupBox { 
                    font-weight: bold; 
                    border: 1px solid #ccc; 
                    border-radius: 4px; 
                    margin-top: 10px;
                }
                QGroupBox::title { 
                    subcontrol-origin: margin; 
                    left: 10px; 
                    padding: 0 5px 0 5px; 
                }
            """)
        
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        if self.is_mobile:
            self.init_mobile_ui(central_widget)
        else:
            self.init_desktop_ui(central_widget)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("未连接")
        self.status_bar.addWidget(self.status_label)
        
        # 连接按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.connect_bot)
        self.status_bar.addPermanentWidget(self.connect_btn)
    
    def init_mobile_ui(self, parent):
        """初始化手机端UI"""
        layout = QVBoxLayout(parent)
        
        # 顶部连接信息
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        
        self.group_edit = QLineEdit(self.current_group)
        self.group_edit.setPlaceholderText("群号")
        self.connect_status = QLabel("🔴 离线")
        self.connect_status.setStyleSheet("font-weight: bold; font-size: 18px;")
        
        top_layout.addWidget(QLabel("群号:"))
        top_layout.addWidget(self.group_edit, 1)
        top_layout.addWidget(self.connect_status)
        
        layout.addWidget(top_widget)
        
        # 标签页
        self.tab_widget = QTabWidget()
        self.init_mobile_tabs()
        layout.addWidget(self.tab_widget, 1)
    
    def init_mobile_tabs(self):
        """初始化手机端标签页"""
        # 标签1: 消息中心
        self.init_mobile_tab1()
        
        # 标签2: 发送消息
        self.init_mobile_tab2()
        
        # 标签3: 贴纸
        self.init_mobile_tab3()
        
        # 标签4: 群成员
        self.init_mobile_tab4()
        
        # 标签5: 文件管理
        self.init_mobile_tab5()
        
        # 标签6: 高级功能
        self.init_mobile_tab6()
        
        # 标签7: 设置
        self.init_mobile_tab7()
    
    def init_mobile_tab1(self):
        """手机端标签1: 消息中心"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 消息记录
        msg_group = QGroupBox("消息记录")
        msg_layout = QVBoxLayout()
        
        self.message_list_mobile = QListWidget()
        self.message_list_mobile.itemDoubleClicked.connect(self.show_message_detail)
        msg_layout.addWidget(self.message_list_mobile)
        
        # 控制按钮
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        
        clear_btn = QPushButton("清空记录")
        clear_btn.clicked.connect(self.message_list_mobile.clear)
        
        recent_btn = QPushButton("最近消息")
        recent_btn.clicked.connect(self.show_recent_messages_mobile)
        
        btn_layout.addWidget(clear_btn)
        btn_layout.addWidget(recent_btn)
        btn_layout.addStretch()
        
        msg_layout.addWidget(btn_widget)
        msg_group.setLayout(msg_layout)
        layout.addWidget(msg_group, 1)
        
        # 快捷操作
        quick_group = QGroupBox("快捷操作")
        quick_layout = QGridLayout()
        
        quick_buttons = [
            ("发送普通消息", self.send_normal_message_mobile),
            ("发送艾特消息", self.send_at_message_mobile),
            ("发送刷屏消息", self.send_spam_message_mobile),
            ("发送贴纸", lambda: self.tab_widget.setCurrentIndex(2)),
            ("发送图片", lambda: self.tab_widget.setCurrentIndex(4)),
            ("查看成员", lambda: self.tab_widget.setCurrentIndex(3)),
        ]
        
        row, col = 0, 0
        for text, func in quick_buttons:
            btn = QPushButton(text)
            btn.clicked.connect(func)
            quick_layout.addWidget(btn, row, col)
            col += 1
            if col > 1:
                col = 0
                row += 1
        
        quick_group.setLayout(quick_layout)
        layout.addWidget(quick_group)
        
        self.tab_widget.addTab(tab, "💬 消息中心")
    
    def init_mobile_tab2(self):
        """手机端标签2: 发送消息"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 发送模式选择
        mode_group = QGroupBox("发送模式")
        mode_layout = QVBoxLayout()
        
        self.mode_normal_m = QRadioButton("普通消息")
        self.mode_normal_m.setChecked(True)
        self.mode_at_m = QRadioButton("艾特消息")
        self.mode_spam_m = QRadioButton("刷屏消息")
        self.mode_multi_at_m = QRadioButton("批量艾特")
        self.mode_image_m = QRadioButton("图片消息")
        self.mode_dm_m = QRadioButton("私聊消息")
        
        mode_layout.addWidget(self.mode_normal_m)
        mode_layout.addWidget(self.mode_at_m)
        mode_layout.addWidget(self.mode_spam_m)
        mode_layout.addWidget(self.mode_multi_at_m)
        mode_layout.addWidget(self.mode_image_m)
        mode_layout.addWidget(self.mode_dm_m)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
        
        # 消息输入
        msg_group = QGroupBox("消息内容")
        msg_layout = QVBoxLayout()
        
        self.message_input_m = QTextEdit()
        self.message_input_m.setMaximumHeight(100)
        self.message_input_m.setPlaceholderText("输入消息内容...")
        msg_layout.addWidget(self.message_input_m)
        msg_group.setLayout(msg_layout)
        layout.addWidget(msg_group)
        
        # 目标用户输入
        target_group = QGroupBox("目标用户")
        target_layout = QVBoxLayout()
        
        self.target_input_m = QLineEdit()
        self.target_input_m.setPlaceholderText("用户ID (多个用逗号分隔)")
        self.target_input_m.setVisible(False)
        
        self.at_all_check_m = QCheckBox("艾特全体成员")
        self.at_all_check_m.setVisible(False)
        
        target_layout.addWidget(self.target_input_m)
        target_layout.addWidget(self.at_all_check_m)
        target_group.setLayout(target_layout)
        layout.addWidget(target_group)
        
        # 刷屏设置
        spam_group = QGroupBox("刷屏设置")
        spam_layout = QHBoxLayout()
        
        self.spam_count_m = QSpinBox()
        self.spam_count_m.setRange(1, 100)
        self.spam_count_m.setValue(5)
        self.spam_count_m.setVisible(False)
        
        self.spam_interval_m = QDoubleSpinBox()
        self.spam_interval_m.setRange(0.1, 10.0)
        self.spam_interval_m.setValue(1.0)
        self.spam_interval_m.setVisible(False)
        
        spam_layout.addWidget(QLabel("次数:"))
        spam_layout.addWidget(self.spam_count_m)
        spam_layout.addWidget(QLabel("间隔:"))
        spam_layout.addWidget(self.spam_interval_m)
        spam_layout.addStretch()
        spam_group.setLayout(spam_layout)
        spam_group.setVisible(False)
        layout.addWidget(spam_group)
        
        # 发送按钮
        send_btn = QPushButton("发送消息")
        send_btn.clicked.connect(self.send_message_mobile)
        layout.addWidget(send_btn)
        
        # 连接信号
        self.mode_normal_m.toggled.connect(lambda: self.update_mobile_mode('normal'))
        self.mode_at_m.toggled.connect(lambda: self.update_mobile_mode('at'))
        self.mode_spam_m.toggled.connect(lambda: self.update_mobile_mode('spam'))
        self.mode_multi_at_m.toggled.connect(lambda: self.update_mobile_mode('multi_at'))
        self.mode_image_m.toggled.connect(lambda: self.update_mobile_mode('image'))
        self.mode_dm_m.toggled.connect(lambda: self.update_mobile_mode('dm'))
        
        layout.addStretch()
        self.tab_widget.addTab(tab, "📤 发送消息")
    
    def init_mobile_tab3(self):
        """手机端标签3: 贴纸"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 贴纸搜索
        search_group = QGroupBox("贴纸搜索")
        search_layout = QHBoxLayout()
        
        self.sticker_search_m = QLineEdit()
        self.sticker_search_m.setPlaceholderText("搜索贴纸...")
        self.sticker_search_m.textChanged.connect(self.filter_stickers_mobile)
        
        search_layout.addWidget(self.sticker_search_m)
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)
        
        # 贴纸网格
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.sticker_grid_m = QGridLayout(container)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)
        
        # 贴纸功能按钮
        func_group = QGroupBox("贴纸功能")
        func_layout = QHBoxLayout()
        
        sticker_list_btn = QPushButton("贴纸列表")
        sticker_list_btn.clicked.connect(self.show_sticker_list_mobile)
        
        sticker_spam_btn = QPushButton("贴纸刷屏")
        sticker_spam_btn.clicked.connect(self.sticker_spam_mobile)
        
        func_layout.addWidget(sticker_list_btn)
        func_layout.addWidget(sticker_spam_btn)
        func_layout.addStretch()
        func_group.setLayout(func_layout)
        layout.addWidget(func_group)
        
        # 加载贴纸
        self.load_stickers_mobile()
        
        self.tab_widget.addTab(tab, "😀 贴纸")
    
    def init_mobile_tab4(self):
        """手机端标签4: 群成员"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 成员列表
        member_group = QGroupBox("群成员列表")
        member_layout = QVBoxLayout()
        
        self.member_list_m = QListWidget()
        self.member_list_m.itemClicked.connect(self.member_clicked_mobile)
        member_layout.addWidget(self.member_list_m)
        member_group.setLayout(member_layout)
        layout.addWidget(member_group, 1)
        
        # 成员搜索
        search_group = QGroupBox("成员搜索")
        search_layout = QHBoxLayout()
        
        self.member_search_m = QLineEdit()
        self.member_search_m.setPlaceholderText("搜索成员昵称或ID...")
        self.member_search_m.textChanged.connect(self.search_members_mobile)
        
        myid_btn = QPushButton("找自己")
        myid_btn.clicked.connect(self.find_my_id_mobile)
        
        search_layout.addWidget(self.member_search_m, 1)
        search_layout.addWidget(myid_btn)
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)
        
        # 成员管理
        manage_group = QGroupBox("成员管理")
        manage_layout = QGridLayout()
        
        refresh_btn = QPushButton("刷新成员")
        refresh_btn.clicked.connect(self.refresh_members)
        
        add_user_btn = QPushButton("添加用户")
        add_user_btn.clicked.connect(self.add_user_mobile)
        
        del_user_btn = QPushButton("删除用户")
        del_user_btn.clicked.connect(self.delete_user_mobile)
        
        manage_layout.addWidget(refresh_btn, 0, 0)
        manage_layout.addWidget(add_user_btn, 0, 1)
        manage_layout.addWidget(del_user_btn, 0, 2)
        manage_group.setLayout(manage_layout)
        layout.addWidget(manage_group)
        
        self.tab_widget.addTab(tab, "👥 群成员")
    
    def init_mobile_tab5(self):
        """手机端标签5: 文件管理"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 图片发送
        image_group = QGroupBox("发送图片")
        image_layout = QVBoxLayout()
        
        self.file_path_m = QLineEdit()
        self.file_path_m.setPlaceholderText("图片文件路径")
        
        browse_btn = QPushButton("选择图片")
        browse_btn.clicked.connect(self.browse_image)
        
        send_img_btn = QPushButton("发送图片")
        send_img_btn.clicked.connect(self.send_image_mobile)
        
        image_layout.addWidget(self.file_path_m)
        image_layout.addWidget(browse_btn)
        image_layout.addWidget(send_img_btn)
        image_group.setLayout(image_layout)
        layout.addWidget(image_group)
        
        layout.addStretch()
        self.tab_widget.addTab(tab, "📁 文件管理")
    
    def init_mobile_tab6(self):
        """手机端标签6: 高级功能"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 引用回复
        reply_group = QGroupBox("引用回复")
        reply_layout = QVBoxLayout()
        
        self.reply_index_m = QSpinBox()
        self.reply_index_m.setRange(1, 100)
        self.reply_index_m.setValue(1)
        
        self.reply_message_m = QLineEdit()
        self.reply_message_m.setPlaceholderText("回复内容")
        
        reply_btn = QPushButton("引用回复")
        reply_btn.clicked.connect(self.send_reply_mobile)
        
        reply_spam_btn = QPushButton("引用刷屏")
        reply_spam_btn.clicked.connect(self.send_reply_spam_mobile)
        
        reply_layout.addWidget(QLabel("消息序号:"))
        reply_layout.addWidget(self.reply_index_m)
        reply_layout.addWidget(QLabel("回复内容:"))
        reply_layout.addWidget(self.reply_message_m)
        reply_layout.addWidget(reply_btn)
        reply_layout.addWidget(reply_spam_btn)
        reply_group.setLayout(reply_layout)
        layout.addWidget(reply_group)
        
        # 批量操作
        batch_group = QGroupBox("批量操作")
        batch_layout = QVBoxLayout()
        
        batch_at_all_btn = QPushButton("艾特全体")
        batch_at_all_btn.clicked.connect(self.at_all_members_mobile)
        
        batch_multi_at_btn = QPushButton("批量艾特")
        batch_multi_at_btn.clicked.connect(self.multi_at_mobile)
        
        batch_layout.addWidget(batch_at_all_btn)
        batch_layout.addWidget(batch_multi_at_btn)
        batch_group.setLayout(batch_layout)
        layout.addWidget(batch_group)
        
        # 私聊功能
        dm_group = QGroupBox("私聊功能")
        dm_layout = QVBoxLayout()
        
        self.dm_target_m = QLineEdit()
        self.dm_target_m.setPlaceholderText("私聊目标用户ID")
        
        self.dm_message_m = QLineEdit()
        self.dm_message_m.setPlaceholderText("私聊内容")
        
        dm_send_btn = QPushButton("发送私聊")
        dm_send_btn.clicked.connect(self.send_dm_mobile)
        
        dm_spam_btn = QPushButton("私聊刷屏")
        dm_spam_btn.clicked.connect(self.send_dm_spam_mobile)
        
        dm_layout.addWidget(self.dm_target_m)
        dm_layout.addWidget(self.dm_message_m)
        dm_layout.addWidget(dm_send_btn)
        dm_layout.addWidget(dm_spam_btn)
        dm_group.setLayout(dm_layout)
        layout.addWidget(dm_group)
        
        layout.addStretch()
        self.tab_widget.addTab(tab, "⚡ 高级功能")
    
    def init_mobile_tab7(self):
        """手机端标签7: 设置"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 连接设置
        connect_group = QGroupBox("连接设置")
        connect_layout = QVBoxLayout()
        
        self.group_edit_settings = QLineEdit(self.current_group)
        self.group_edit_settings.setPlaceholderText("群号")
        
        interval_widget = QWidget()
        interval_layout = QHBoxLayout(interval_widget)
        interval_layout.addWidget(QLabel("刷屏间隔:"))
        self.interval_spin_m = QDoubleSpinBox()
        self.interval_spin_m.setRange(0.1, 10.0)
        self.interval_spin_m.setValue(self.spam_interval)
        self.interval_spin_m.valueChanged.connect(self.set_interval_mobile)
        interval_layout.addWidget(self.interval_spin_m)
        interval_layout.addStretch()
        
        connect_layout.addWidget(QLabel("默认群号:"))
        connect_layout.addWidget(self.group_edit_settings)
        connect_layout.addWidget(interval_widget)
        connect_group.setLayout(connect_layout)
        layout.addWidget(connect_group)
        
        # 自动回复设置
        auto_reply_group = QGroupBox("自动回复设置")
        auto_layout = QVBoxLayout()
        
        self.auto_reply_check = QCheckBox("启用自动回复")
        self.auto_reply_check.stateChanged.connect(self.toggle_auto_reply)
        
        auto_layout.addWidget(self.auto_reply_check)
        
        # 群聊回复
        group_widget = QWidget()
        group_layout = QHBoxLayout(group_widget)
        group_layout.addWidget(QLabel("群聊回复:"))
        self.group_reply_edit = QLineEdit(AUTO_REPLY_GROUP_TEXT)
        group_layout.addWidget(self.group_reply_edit, 1)
        auto_layout.addWidget(group_widget)
        
        # 私聊回复
        c2c_widget = QWidget()
        c2c_layout = QHBoxLayout(c2c_widget)
        c2c_layout.addWidget(QLabel("私聊回复:"))
        self.c2c_reply_edit = QLineEdit(AUTO_REPLY_C2C_TEXT)
        c2c_layout.addWidget(self.c2c_reply_edit, 1)
        auto_layout.addWidget(c2c_widget)
        
        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self.save_settings)
        
        auto_layout.addWidget(save_btn)
        auto_reply_group.setLayout(auto_layout)
        layout.addWidget(auto_reply_group)
        
        # 帮助
        help_group = QGroupBox("帮助")
        help_layout = QVBoxLayout()
        
        help_btn = QPushButton("显示帮助")
        help_btn.clicked.connect(self.show_help_mobile)
        
        about_btn = QPushButton("关于")
        about_btn.clicked.connect(self.show_about)
        
        help_layout.addWidget(help_btn)
        help_layout.addWidget(about_btn)
        help_group.setLayout(help_layout)
        layout.addWidget(help_group)
        
        layout.addStretch()
        self.tab_widget.addTab(tab, "⚙️ 设置")
    
    def init_desktop_ui(self, parent):
        """初始化电脑端UI"""
        main_layout = QHBoxLayout(parent)
        
        # 左侧：消息显示区
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # 消息列表
        message_group = QGroupBox("消息记录")
        message_layout = QVBoxLayout()
        
        self.message_list = QListWidget()
        self.message_list.setAlternatingRowColors(True)
        self.message_list.itemDoubleClicked.connect(self.show_message_detail)
        
        # 消息右键菜单
        self.message_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.message_list.customContextMenuRequested.connect(self.show_message_context_menu)
        
        message_layout.addWidget(self.message_list)
        
        # 消息控制
        msg_control_widget = QWidget()
        msg_control_layout = QHBoxLayout(msg_control_widget)
        
        clear_btn = QPushButton("清空记录")
        clear_btn.clicked.connect(self.message_list.clear)
        
        recent_btn = QPushButton("最近消息")
        recent_btn.clicked.connect(self.show_recent_messages)
        
        msg_control_layout.addWidget(clear_btn)
        msg_control_layout.addWidget(recent_btn)
        msg_control_layout.addStretch()
        
        message_layout.addWidget(msg_control_widget)
        message_group.setLayout(message_layout)
        left_layout.addWidget(message_group, 2)
        
        # 连接状态
        status_group = QGroupBox("连接状态")
        status_layout = QVBoxLayout()
        
        self.status_text = QLabel("状态: 未连接")
        self.group_label = QLabel(f"当前群: {self.current_group}")
        
        status_layout.addWidget(self.status_text)
        status_layout.addWidget(self.group_label)
        
        status_group.setLayout(status_layout)
        left_layout.addWidget(status_group)
        
        main_layout.addWidget(left_widget, 2)
        
        # 中间：功能面板
        center_widget = QTabWidget()
        self.init_desktop_tabs(center_widget)
        main_layout.addWidget(center_widget, 2)
        
        # 右侧：快速功能
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # 快速发送
        quick_group = QGroupBox("快速发送")
        quick_layout = QVBoxLayout()
        
        quick_buttons = [
            ("发送普通消息", self.send_normal_message),
            ("发送艾特消息", self.send_at_message),
            ("发送刷屏消息", self.send_spam_message),
            ("发送贴纸", lambda: center_widget.setCurrentIndex(1)),
            ("发送图片", lambda: center_widget.setCurrentIndex(3)),
        ]
        
        for text, func in quick_buttons:
            btn = QPushButton(text)
            btn.clicked.connect(func)
            quick_layout.addWidget(btn)
        
        quick_group.setLayout(quick_layout)
        right_layout.addWidget(quick_group)
        
        # 自动回复设置
        auto_group = QGroupBox("自动回复")
        auto_layout = QVBoxLayout()
        
        self.auto_reply_check_d = QCheckBox("启用自动回复")
        self.auto_reply_check_d.stateChanged.connect(self.toggle_auto_reply)
        
        auto_layout.addWidget(self.auto_reply_check_d)
        
        # 回复规则
        rule_widget = QWidget()
        rule_layout = QVBoxLayout(rule_widget)
        rule_layout.addWidget(QLabel("群聊回复:"))
        self.group_reply_edit_d = QTextEdit(AUTO_REPLY_GROUP_TEXT)
        self.group_reply_edit_d.setMaximumHeight(60)
        rule_layout.addWidget(self.group_reply_edit_d)
        
        rule_layout.addWidget(QLabel("私聊回复:"))
        self.c2c_reply_edit_d = QTextEdit(AUTO_REPLY_C2C_TEXT)
        self.c2c_reply_edit_d.setMaximumHeight(60)
        rule_layout.addWidget(self.c2c_reply_edit_d)
        
        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self.save_settings)
        
        auto_layout.addWidget(rule_widget)
        auto_layout.addWidget(save_btn)
        auto_group.setLayout(auto_layout)
        right_layout.addWidget(auto_group)
        
        right_layout.addStretch()
        main_layout.addWidget(right_widget, 1)
    
    def init_desktop_tabs(self, tab_widget):
        """初始化电脑端标签页"""
        # 标签1: 发送消息
        self.init_desktop_tab1(tab_widget)
        
        # 标签2: 贴纸
        self.init_desktop_tab2(tab_widget)
        
        # 标签3: 群成员
        self.init_desktop_tab3(tab_widget)
        
        # 标签4: 文件管理
        self.init_desktop_tab4(tab_widget)
        
        # 标签5: 高级功能
        self.init_desktop_tab5(tab_widget)
        
        # 标签6: 用户管理
        self.init_desktop_tab6(tab_widget)
        
        # 标签7: 设置
        self.init_desktop_tab7(tab_widget)
    
    def init_desktop_tab1(self, tab_widget):
        """电脑端标签1: 发送消息"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 发送模式
        mode_group = QGroupBox("发送模式")
        mode_layout = QHBoxLayout()
        
        self.mode_normal = QRadioButton("普通")
        self.mode_normal.setChecked(True)
        self.mode_at = QRadioButton("艾特")
        self.mode_spam = QRadioButton("刷屏")
        self.mode_multi_at = QRadioButton("批量艾特")
        self.mode_sticker = QRadioButton("贴纸")
        self.mode_image = QRadioButton("图片")
        self.mode_dm = QRadioButton("私聊")
        
        mode_layout.addWidget(self.mode_normal)
        mode_layout.addWidget(self.mode_at)
        mode_layout.addWidget(self.mode_spam)
        mode_layout.addWidget(self.mode_multi_at)
        mode_layout.addWidget(self.mode_sticker)
        mode_layout.addWidget(self.mode_image)
        mode_layout.addWidget(self.mode_dm)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
        
        # 目标选择（艾特模式）
        at_widget = QWidget()
        at_layout = QHBoxLayout(at_widget)
        at_layout.addWidget(QLabel("艾特用户:"))
        self.at_combo = QComboBox()
        self.at_combo.setEditable(True)
        at_layout.addWidget(self.at_combo, 1)
        self.at_widget = at_widget
        self.at_widget.setVisible(False)
        layout.addWidget(self.at_widget)
        
        # 批量艾特
        multi_at_widget = QWidget()
        multi_at_layout = QHBoxLayout(multi_at_widget)
        multi_at_layout.addWidget(QLabel("批量艾特:"))
        self.multi_at_input = QLineEdit()
        self.multi_at_input.setPlaceholderText("用户ID,用逗号分隔")
        multi_at_layout.addWidget(self.multi_at_input, 1)
        self.multi_at_widget = multi_at_widget
        self.multi_at_widget.setVisible(False)
        layout.addWidget(self.multi_at_widget)
        
        # 刷屏设置
        spam_widget = QWidget()
        spam_layout = QHBoxLayout(spam_widget)
        spam_layout.addWidget(QLabel("次数:"))
        self.spam_count = QSpinBox()
        self.spam_count.setRange(1, 100)
        self.spam_count.setValue(5)
        spam_layout.addWidget(self.spam_count)
        spam_layout.addWidget(QLabel("间隔(秒):"))
        self.spam_interval_spin = QDoubleSpinBox()
        self.spam_interval_spin.setRange(0.1, 10.0)
        self.spam_interval_spin.setValue(self.spam_interval)
        self.spam_interval_spin.valueChanged.connect(self.set_interval)
        spam_layout.addWidget(self.spam_interval_spin)
        self.spam_widget = spam_widget
        self.spam_widget.setVisible(False)
        layout.addWidget(self.spam_widget)
        
        # 私聊目标
        dm_widget = QWidget()
        dm_layout = QHBoxLayout(dm_widget)
        dm_layout.addWidget(QLabel("私聊目标:"))
        self.dm_target = QLineEdit()
        self.dm_target.setPlaceholderText("用户ID")
        dm_layout.addWidget(self.dm_target, 1)
        self.dm_widget = dm_widget
        self.dm_widget.setVisible(False)
        layout.addWidget(self.dm_widget)
        
        # 消息输入
        msg_group = QGroupBox("消息内容")
        msg_layout = QVBoxLayout()
        self.message_edit = QTextEdit()
        self.message_edit.setPlaceholderText("输入消息内容...")
        msg_layout.addWidget(self.message_edit)
        msg_group.setLayout(msg_layout)
        layout.addWidget(msg_group, 1)
        
        # 发送按钮
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.send_message_desktop)
        layout.addWidget(self.send_button)
        
        # 连接信号
        self.mode_normal.toggled.connect(lambda: self.update_desktop_mode('normal'))
        self.mode_at.toggled.connect(lambda: self.update_desktop_mode('at'))
        self.mode_spam.toggled.connect(lambda: self.update_desktop_mode('spam'))
        self.mode_multi_at.toggled.connect(lambda: self.update_desktop_mode('multi_at'))
        self.mode_sticker.toggled.connect(lambda: self.update_desktop_mode('sticker'))
        self.mode_image.toggled.connect(lambda: self.update_desktop_mode('image'))
        self.mode_dm.toggled.connect(lambda: self.update_desktop_mode('dm'))
        
        tab_widget.addTab(tab, "发送消息")
    
    def init_desktop_tab2(self, tab_widget):
        """电脑端标签2: 贴纸"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 贴纸搜索
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        self.sticker_search = QLineEdit()
        self.sticker_search.setPlaceholderText("搜索贴纸...")
        self.sticker_search.textChanged.connect(self.filter_stickers)
        search_layout.addWidget(self.sticker_search)
        layout.addWidget(search_widget)
        
        # 贴纸网格
        self.sticker_scroll = QScrollArea()
        self.sticker_scroll.setWidgetResizable(True)
        container = QWidget()
        self.sticker_grid = QGridLayout(container)
        self.sticker_scroll.setWidget(container)
        layout.addWidget(self.sticker_scroll, 1)
        
        # 贴纸功能
        func_widget = QWidget()
        func_layout = QHBoxLayout(func_widget)
        
        sticker_list_btn = QPushButton("贴纸列表")
        sticker_list_btn.clicked.connect(self.show_sticker_list)
        
        sticker_spam_btn = QPushButton("贴纸刷屏")
        sticker_spam_btn.clicked.connect(self.sticker_spam)
        
        func_layout.addWidget(sticker_list_btn)
        func_layout.addWidget(sticker_spam_btn)
        func_layout.addStretch()
        layout.addWidget(func_widget)
        
        # 加载贴纸
        self.load_stickers()
        
        tab_widget.addTab(tab, "贴纸")
    
    def init_desktop_tab3(self, tab_widget):
        """电脑端标签3: 群成员"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 成员搜索
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        search_layout.addWidget(QLabel("搜索:"))
        self.member_search = QLineEdit()
        self.member_search.setPlaceholderText("搜索成员昵称或ID...")
        self.member_search.textChanged.connect(self.search_members)
        search_layout.addWidget(self.member_search, 1)
        
        myid_btn = QPushButton("找自己")
        myid_btn.clicked.connect(self.find_my_id)
        search_layout.addWidget(myid_btn)
        
        layout.addWidget(search_widget)
        
        # 成员列表
        self.member_list = QListWidget()
        self.member_list.itemClicked.connect(self.member_clicked)
        layout.addWidget(self.member_list, 1)
        
        # 成员管理
        manage_widget = QWidget()
        manage_layout = QHBoxLayout(manage_widget)
        
        refresh_btn = QPushButton("刷新成员")
        refresh_btn.clicked.connect(self.refresh_members)
        
        at_all_btn = QPushButton("艾特全体")
        at_all_btn.clicked.connect(self.at_all_members)
        
        manage_layout.addWidget(refresh_btn)
        manage_layout.addWidget(at_all_btn)
        manage_layout.addStretch()
        layout.addWidget(manage_widget)
        
        tab_widget.addTab(tab, "群成员")
    
    def init_desktop_tab4(self, tab_widget):
        """电脑端标签4: 文件管理"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 图片发送
        image_group = QGroupBox("发送图片")
        image_layout = QVBoxLayout()
        
        file_widget = QWidget()
        file_layout = QHBoxLayout(file_widget)
        file_layout.addWidget(QLabel("图片文件:"))
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("选择图片文件...")
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self.browse_image)
        file_layout.addWidget(self.file_path, 1)
        file_layout.addWidget(browse_btn)
        image_layout.addWidget(file_widget)
        
        preview_widget = QWidget()
        preview_layout = QHBoxLayout(preview_widget)
        self.image_preview = QLabel("图片预览")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setStyleSheet("border: 1px solid #ccc; padding: 20px; min-height: 100px;")
        preview_layout.addWidget(self.image_preview)
        image_layout.addWidget(preview_widget)
        
        send_btn = QPushButton("发送图片")
        send_btn.clicked.connect(self.send_image)
        image_layout.addWidget(send_btn)
        
        image_group.setLayout(image_layout)
        layout.addWidget(image_group)
        
        layout.addStretch()
        tab_widget.addTab(tab, "文件管理")
    
    def init_desktop_tab5(self, tab_widget):
        """电脑端标签5: 高级功能"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 引用回复
        reply_group = QGroupBox("引用回复")
        reply_layout = QGridLayout()
        
        reply_layout.addWidget(QLabel("消息序号:"), 0, 0)
        self.reply_index = QSpinBox()
        self.reply_index.setRange(1, 100)
        self.reply_index.setValue(1)
        reply_layout.addWidget(self.reply_index, 0, 1)
        
        reply_layout.addWidget(QLabel("回复内容:"), 1, 0)
        self.reply_message = QLineEdit()
        self.reply_message.setPlaceholderText("回复内容")
        reply_layout.addWidget(self.reply_message, 1, 1, 1, 2)
        
        reply_btn = QPushButton("引用回复")
        reply_btn.clicked.connect(self.send_reply)
        reply_layout.addWidget(reply_btn, 2, 0)
        
        reply_spam_btn = QPushButton("引用刷屏")
        reply_spam_btn.clicked.connect(self.send_reply_spam)
        reply_layout.addWidget(reply_spam_btn, 2, 1)
        
        reply_group.setLayout(reply_layout)
        layout.addWidget(reply_group)
        
        # 批量艾特
        multi_at_group = QGroupBox("批量艾特")
        multi_at_layout = QVBoxLayout()
        
        multi_at_input_widget = QWidget()
        multi_at_input_layout = QHBoxLayout(multi_at_input_widget)
        multi_at_input_layout.addWidget(QLabel("用户ID:"))
        self.multi_at_users = QLineEdit()
        self.multi_at_users.setPlaceholderText("用户ID1,用户ID2,用户ID3...")
        multi_at_input_layout.addWidget(self.multi_at_users, 1)
        multi_at_layout.addWidget(multi_at_input_widget)
        
        multi_at_msg_widget = QWidget()
        multi_at_msg_layout = QHBoxLayout(multi_at_msg_widget)
        multi_at_msg_layout.addWidget(QLabel("消息:"))
        self.multi_at_msg = QLineEdit()
        self.multi_at_msg.setPlaceholderText("消息内容")
        multi_at_msg_layout.addWidget(self.multi_at_msg, 1)
        multi_at_layout.addWidget(multi_at_msg_widget)
        
        multi_at_send_btn = QPushButton("批量艾特发送")
        multi_at_send_btn.clicked.connect(self.send_multi_at)
        multi_at_layout.addWidget(multi_at_send_btn)
        
        multi_at_group.setLayout(multi_at_layout)
        layout.addWidget(multi_at_group)
        
        # 私聊功能
        dm_group = QGroupBox("私聊功能")
        dm_layout = QGridLayout()
        
        dm_layout.addWidget(QLabel("目标用户:"), 0, 0)
        self.dm_target_input = QLineEdit()
        self.dm_target_input.setPlaceholderText("用户ID")
        dm_layout.addWidget(self.dm_target_input, 0, 1)
        
        dm_layout.addWidget(QLabel("消息:"), 1, 0)
        self.dm_message = QLineEdit()
        self.dm_message.setPlaceholderText("私聊内容")
        dm_layout.addWidget(self.dm_message, 1, 1)
        
        dm_send_btn = QPushButton("发送私聊")
        dm_send_btn.clicked.connect(self.send_dm)
        dm_layout.addWidget(dm_send_btn, 2, 0)
        
        dm_spam_btn = QPushButton("私聊刷屏")
        dm_spam_btn.clicked.connect(self.send_dm_spam)
        dm_layout.addWidget(dm_spam_btn, 2, 1)
        
        dm_group.setLayout(dm_layout)
        layout.addWidget(dm_group)
        
        layout.addStretch()
        tab_widget.addTab(tab, "高级功能")
    
    def init_desktop_tab6(self, tab_widget):
        """电脑端标签6: 用户管理"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 用户列表
        user_group = QGroupBox("已保存用户")
        user_layout = QVBoxLayout()
        
        self.user_list_widget = QListWidget()
        self.user_list_widget.itemDoubleClicked.connect(self.use_saved_user)
        user_layout.addWidget(self.user_list_widget)
        user_group.setLayout(user_layout)
        layout.addWidget(user_group, 1)
        
        # 用户管理
        manage_group = QGroupBox("用户管理")
        manage_layout = QGridLayout()
        
        manage_layout.addWidget(QLabel("用户ID:"), 0, 0)
        self.add_user_id = QLineEdit()
        self.add_user_id.setPlaceholderText("用户ID")
        manage_layout.addWidget(self.add_user_id, 0, 1)
        
        manage_layout.addWidget(QLabel("昵称:"), 1, 0)
        self.add_user_nick = QLineEdit()
        self.add_user_nick.setPlaceholderText("昵称")
        manage_layout.addWidget(self.add_user_nick, 1, 1)
        
        add_btn = QPushButton("添加用户")
        add_btn.clicked.connect(self.add_user)
        manage_layout.addWidget(add_btn, 2, 0)
        
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self.delete_user)
        manage_layout.addWidget(del_btn, 2, 1)
        
        manage_group.setLayout(manage_layout)
        layout.addWidget(manage_group)
        
        tab_widget.addTab(tab, "用户管理")
    
    def init_desktop_tab7(self, tab_widget):
        """电脑端标签7: 设置"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 连接设置
        connect_group = QGroupBox("连接设置")
        connect_layout = QVBoxLayout()
        
        group_widget = QWidget()
        group_layout = QHBoxLayout(group_widget)
        group_layout.addWidget(QLabel("默认群号:"))
        self.group_edit_setting = QLineEdit(self.current_group)
        self.group_edit_setting.setPlaceholderText("群号")
        group_layout.addWidget(self.group_edit_setting, 1)
        connect_layout.addWidget(group_widget)
        
        interval_widget = QWidget()
        interval_layout = QHBoxLayout(interval_widget)
        interval_layout.addWidget(QLabel("刷屏间隔:"))
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 10.0)
        self.interval_spin.setValue(self.spam_interval)
        self.interval_spin.valueChanged.connect(self.set_interval)
        interval_layout.addWidget(self.interval_spin)
        interval_layout.addStretch()
        connect_layout.addWidget(interval_widget)
        
        connect_group.setLayout(connect_layout)
        layout.addWidget(connect_group)
        
        # 帮助
        help_group = QGroupBox("帮助")
        help_layout = QVBoxLayout()
        
        help_btn = QPushButton("显示帮助")
        help_btn.clicked.connect(self.show_help)
        
        about_btn = QPushButton("关于")
        about_btn.clicked.connect(self.show_about)
        
        help_layout.addWidget(help_btn)
        help_layout.addWidget(about_btn)
        help_group.setLayout(help_layout)
        layout.addWidget(help_group)
        
        layout.addStretch()
        tab_widget.addTab(tab, "设置")
    
    def load_stickers(self):
        """加载贴纸按钮（电脑端）"""
        from sender import SpamSender
        stickers = list(SpamSender.STICKERS.keys())
        
        row, col = 0, 0
        for sticker in stickers:
            btn = QPushButton(sticker)
            btn.setMaximumWidth(100)
            btn.clicked.connect(lambda checked, s=sticker: self.select_sticker(s))
            self.sticker_grid.addWidget(btn, row, col)
            self.sticker_buttons.append(btn)
            col += 1
            if col > 3:  # 每行4个
                col = 0
                row += 1
    
    def load_stickers_mobile(self):
        """加载贴纸按钮（手机端）"""
        from sender import SpamSender
        stickers = list(SpamSender.STICKERS.keys())
        
        row, col = 0, 0
        for sticker in stickers:
            btn = QPushButton(sticker)
            btn.clicked.connect(lambda checked, s=sticker: self.select_sticker_mobile(s))
            self.sticker_grid_m.addWidget(btn, row, col)
            col += 1
            if col > 1:  # 手机每行2个
                col = 0
                row += 1
    
    def filter_stickers(self, text):
        """过滤贴纸显示（电脑端）"""
        for btn in self.sticker_buttons:
            if text.lower() in btn.text().lower():
                btn.show()
            else:
                btn.hide()
    
    def filter_stickers_mobile(self, text):
        """过滤贴纸显示（手机端）"""
        for i in range(self.sticker_grid_m.count()):
            widget = self.sticker_grid_m.itemAt(i).widget()
            if isinstance(widget, QPushButton):
                if text.lower() in widget.text().lower():
                    widget.show()
                else:
                    widget.hide()
    
    def update_desktop_mode(self, mode):
        """更新电脑端发送模式"""
        self.at_widget.setVisible(mode == 'at')
        self.spam_widget.setVisible(mode == 'spam')
        self.multi_at_widget.setVisible(mode == 'multi_at')
        self.dm_widget.setVisible(mode == 'dm')
        
        if mode == 'normal':
            self.send_button.setText("发送普通消息")
        elif mode == 'at':
            self.send_button.setText("发送艾特消息")
        elif mode == 'spam':
            self.send_button.setText("开始刷屏")
        elif mode == 'multi_at':
            self.send_button.setText("发送批量艾特")
        elif mode == 'sticker':
            self.send_button.setText("发送贴纸")
        elif mode == 'image':
            self.send_button.setText("发送图片")
        elif mode == 'dm':
            self.send_button.setText("发送私聊")
    
    def update_mobile_mode(self, mode):
        """更新手机端发送模式"""
        self.target_input_m.setVisible(mode in ['at', 'multi_at', 'dm'])
        self.at_all_check_m.setVisible(mode == 'at')
        self.spam_count_m.setVisible(mode in ['spam', 'dm'])
        self.spam_interval_m.setVisible(mode in ['spam', 'dm'])
        
        if mode == 'multi_at':
            self.target_input_m.setPlaceholderText("用户ID,用逗号分隔")
        elif mode == 'dm':
            self.target_input_m.setPlaceholderText("私聊目标用户ID")
        elif mode == 'at':
            self.target_input_m.setPlaceholderText("用户ID")
    
    # ================ 核心功能实现 ================
    
    def send_message_desktop(self):
        """电脑端发送消息"""
        if not self.is_connected:
            QMessageBox.warning(self, "提示", "请先连接")
            return
        
        if self.mode_normal.isChecked():
            self.send_normal_message()
        elif self.mode_at.isChecked():
            self.send_at_message()
        elif self.mode_spam.isChecked():
            self.send_spam_message()
        elif self.mode_multi_at.isChecked():
            self.send_multi_at_message()
        elif self.mode_sticker.isChecked():
            self.send_sticker_message()
        elif self.mode_image.isChecked():
            self.send_image_message()
        elif self.mode_dm.isChecked():
            self.send_dm_message()
    
    def send_message_mobile(self):
        """手机端发送消息"""
        if not self.is_connected:
            QMessageBox.warning(self, "提示", "请先连接")
            return
        
        if self.mode_normal_m.isChecked():
            self.send_normal_message_mobile()
        elif self.mode_at_m.isChecked():
            self.send_at_message_mobile()
        elif self.mode_spam_m.isChecked():
            self.send_spam_message_mobile()
        elif self.mode_multi_at_m.isChecked():
            self.send_multi_at_message_mobile()
        elif self.mode_image_m.isChecked():
            self.send_image_mobile()
        elif self.mode_dm_m.isChecked():
            self.send_dm_message_mobile()
    
    def send_normal_message(self):
        """发送普通消息（电脑端）"""
        message = self.message_edit.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        self.run_async(
            self.sender.send_group_message(message),
            lambda r: self.on_message_sent(f"普通: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_normal_message_mobile(self):
        """发送普通消息（手机端）"""
        message = self.message_input_m.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        self.run_async(
            self.sender.send_group_message(message),
            lambda r: self.on_message_sent_mobile(f"普通: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_at_message(self):
        """发送艾特消息（电脑端）"""
        message = self.message_edit.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        at_user = self.at_combo.currentText()
        if not at_user:
            QMessageBox.warning(self, "提示", "请选择要艾特的用户")
            return
        
        # 提取用户ID
        if '(' in at_user and ')' in at_user:
            at_user = at_user.split('(')[-1].rstrip(')')
        
        at_nick = self.sender.user_db.get(at_user, at_user) if self.sender else at_user
        
        self.run_async(
            self.sender.send_group_message(message, at_user, at_nick),
            lambda r: self.on_message_sent(f"艾特@{at_user}: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_at_message_mobile(self):
        """发送艾特消息（手机端）"""
        message = self.message_input_m.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        at_user = self.target_input_m.text().strip()
        if not at_user and not self.at_all_check_m.isChecked():
            QMessageBox.warning(self, "提示", "请输入用户ID或选择艾特全体")
            return
        
        if self.at_all_check_m.isChecked():
            # 艾特全体
            self.send_at_all_mobile(message)
        else:
            at_nick = self.sender.user_db.get(at_user, at_user) if self.sender else at_user
            self.run_async(
                self.sender.send_group_message(message, at_user, at_nick),
                lambda r: self.on_message_sent_mobile(f"艾特@{at_user}: {message[:30]}"),
                lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
            )
    
    def send_spam_message(self):
        """发送刷屏消息（电脑端）"""
        message = self.message_edit.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        at_user = self.at_combo.currentText()
        if not at_user:
            QMessageBox.warning(self, "提示", "请选择要艾特的用户")
            return
        
        # 提取用户ID
        if '(' in at_user and ')' in at_user:
            at_user = at_user.split('(')[-1].rstrip(')')
        
        count = self.spam_count.value()
        interval = self.spam_interval_spin.value()
        
        reply = QMessageBox.question(
            self, "确认刷屏",
            f"确认要向 @{at_user} 刷屏 {count} 次吗？\n"
            f"间隔: {interval}秒\n"
            f"内容: {message[:50]}...",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.run_spam(message, at_user, count, interval)
    
    def send_spam_message_mobile(self):
        """发送刷屏消息（手机端）"""
        message = self.message_input_m.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        at_user = self.target_input_m.text().strip()
        if not at_user:
            QMessageBox.warning(self, "提示", "请输入用户ID")
            return
        
        count = self.spam_count_m.value()
        interval = self.spam_interval_m.value()
        
        reply = QMessageBox.question(
            self, "确认刷屏",
            f"确认要向 @{at_user} 刷屏 {count} 次吗？\n"
            f"间隔: {interval}秒",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.run_spam_mobile(message, at_user, count, interval)
    
    def run_spam(self, message, at_user, count, interval):
        """运行刷屏任务（电脑端）"""
        self.send_button.setEnabled(False)
        self.send_button.setText("刷屏中...")
        
        async def spam_task():
            at_nick = self.sender.user_db.get(at_user, at_user) if self.sender else at_user
            success, fail = 0, 0
            
            for i in range(count):
                try:
                    ok = await self.sender.send_group_message(message, at_user, at_nick)
                    if ok:
                        success += 1
                    else:
                        fail += 1
                    self.log_message(f"[{i+1}/{count}] {'✓' if ok else '✗'}")
                except Exception as e:
                    fail += 1
                    self.log_message(f"[{i+1}/{count}] ✗ 错误: {str(e)[:50]}")
                
                if i < count - 1:
                    await asyncio.sleep(interval)
            
            return success, fail
        
        def on_finished(result):
            self.send_button.setEnabled(True)
            self.send_button.setText("开始刷屏")
            success, failed = result
            QMessageBox.information(
                self, "刷屏完成",
                f"刷屏完成!\n成功: {success}次\n失败: {failed}次"
            )
        
        def on_error(error):
            self.send_button.setEnabled(True)
            self.send_button.setText("开始刷屏")
            QMessageBox.critical(self, "刷屏错误", f"刷屏失败: {error}")
        
        self.run_async(spam_task(), on_finished, on_error)
    
    def run_spam_mobile(self, message, at_user, count, interval):
        """运行刷屏任务（手机端）"""
        async def spam_task():
            at_nick = self.sender.user_db.get(at_user, at_user) if self.sender else at_user
            success, fail = 0, 0
            
            for i in range(count):
                try:
                    ok = await self.sender.send_group_message(message, at_user, at_nick)
                    if ok:
                        success += 1
                    else:
                        fail += 1
                    self.log_message_mobile(f"[{i+1}/{count}] {'✓' if ok else '✗'}")
                except Exception as e:
                    fail += 1
                    self.log_message_mobile(f"[{i+1}/{count}] ✗ 错误: {str(e)[:50]}")
                
                if i < count - 1:
                    await asyncio.sleep(interval)
            
            return success, fail
        
        def on_finished(result):
            success, failed = result
            QMessageBox.information(
                self, "刷屏完成",
                f"刷屏完成!\n成功: {success}次\n失败: {failed}次"
            )
        
        def on_error(error):
            QMessageBox.critical(self, "刷屏错误", f"刷屏失败: {error}")
        
        self.run_async(spam_task(), on_finished, on_error)
    
    def send_multi_at_message(self):
        """发送批量艾特消息（电脑端）"""
        message = self.message_edit.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        users_text = self.multi_at_input.text().strip()
        if not users_text:
            QMessageBox.warning(self, "提示", "请输入用户ID，多个用逗号分隔")
            return
        
        users = [uid.strip() for uid in users_text.split(',') if uid.strip()]
        if not users:
            QMessageBox.warning(self, "提示", "请输入有效的用户ID")
            return
        
        # 获取用户昵称
        at_users = []
        for uid in users:
            nick = self.sender.user_db.get(uid, uid) if self.sender else uid
            at_users.append((uid, nick))
        
        self.run_async(
            self.sender.send_multi_at_message(message, at_users),
            lambda r: self.on_message_sent(f"批量艾特{len(users)}人: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_multi_at_message_mobile(self):
        """发送批量艾特消息（手机端）"""
        message = self.message_input_m.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        users_text = self.target_input_m.text().strip()
        if not users_text:
            QMessageBox.warning(self, "提示", "请输入用户ID，多个用逗号分隔")
            return
        
        users = [uid.strip() for uid in users_text.split(',') if uid.strip()]
        if not users:
            QMessageBox.warning(self, "提示", "请输入有效的用户ID")
            return
        
        # 获取用户昵称
        at_users = []
        for uid in users:
            nick = self.sender.user_db.get(uid, uid) if self.sender else uid
            at_users.append((uid, nick))
        
        self.run_async(
            self.sender.send_multi_at_message(message, at_users),
            lambda r: self.on_message_sent_mobile(f"批量艾特{len(users)}人: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def select_sticker(self, sticker_name):
        """选择贴纸（电脑端）"""
        self.message_edit.setPlainText(f"[贴纸:{sticker_name}]")
        self.mode_sticker.setChecked(True)
    
    def select_sticker_mobile(self, sticker_name):
        """选择贴纸（手机端）"""
        self.message_input_m.setPlainText(f"[贴纸:{sticker_name}]")
    
    def send_sticker_message(self):
        """发送贴纸消息（电脑端）"""
        message = self.message_edit.toPlainText().strip()
        if not message or not message.startswith("[贴纸:"):
            QMessageBox.warning(self, "提示", "请先选择贴纸")
            return
        
        # 提取贴纸名称
        if message.startswith("[贴纸:") and message.endswith("]"):
            sticker_name = message[4:-1]
        else:
            QMessageBox.warning(self, "提示", "贴纸格式错误")
            return
        
        self.run_async(
            self.sender.send_sticker_message(sticker_name),
            lambda r: self.on_message_sent(f"贴纸: {sticker_name}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def sticker_spam(self):
        """贴纸刷屏（电脑端）"""
        sticker_name, ok = QInputDialog.getText(
            self, "贴纸刷屏", "请输入贴纸名称:"
        )
        if not ok or not sticker_name:
            return
        
        if sticker_name not in SpamSender.STICKERS:
            QMessageBox.warning(self, "提示", f"贴纸'{sticker_name}'不存在")
            return
        
        count, ok1 = QInputDialog.getInt(
            self, "贴纸刷屏", "请输入刷屏次数:", 5, 1, 100, 1
        )
        
        if not ok1:
            return
        
        interval, ok2 = QInputDialog.getDouble(
            self, "贴纸刷屏", "请输入刷屏间隔(秒):", 1.0, 0.1, 10.0, 1
        )
        
        if not ok2:
            return
        
        reply = QMessageBox.question(
            self, "确认贴纸刷屏",
            f"确认要刷屏贴纸'{sticker_name}' {count} 次吗？\n"
            f"间隔: {interval}秒",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.run_sticker_spam(sticker_name, count, interval)
    
    def sticker_spam_mobile(self):
        """贴纸刷屏（手机端）"""
        QMessageBox.information(self, "提示", "请在贴纸页面选择贴纸后使用刷屏功能")
    
    def run_sticker_spam(self, sticker_name, count, interval):
        """运行贴纸刷屏任务"""
        async def sticker_spam_task():
            success, fail = 0, 0
            
            for i in range(count):
                try:
                    ok = await self.sender.send_sticker_message(sticker_name)
                    if ok:
                        success += 1
                    else:
                        fail += 1
                    self.log_message(f"[{i+1}/{count}] 贴纸刷屏 {'✓' if ok else '✗'}")
                except Exception as e:
                    fail += 1
                    self.log_message(f"[{i+1}/{count}] ✗ 错误: {str(e)[:50]}")
                
                if i < count - 1:
                    await asyncio.sleep(interval)
            
            return success, fail
        
        def on_finished(result):
            success, failed = result
            QMessageBox.information(
                self, "贴纸刷屏完成",
                f"贴纸刷屏完成!\n成功: {success}次\n失败: {failed}次"
            )
        
        def on_error(error):
            QMessageBox.critical(self, "贴纸刷屏错误", f"贴纸刷屏失败: {error}")
        
        self.run_async(sticker_spam_task(), on_finished, on_error)
    
    def send_image_message(self):
        """发送图片消息（电脑端）"""
        file_path = self.file_path.text().strip()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "提示", "请选择有效的图片文件")
            return
        
        self.run_async(
            self.sender.send_image(file_path),
            lambda r: self.on_message_sent(f"图片: {os.path.basename(file_path)}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_image_mobile(self):
        """发送图片消息（手机端）"""
        file_path = self.file_path_m.text().strip()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "提示", "请选择有效的图片文件")
            return
        
        self.run_async(
            self.sender.send_image(file_path),
            lambda r: self.on_message_sent_mobile(f"图片: {os.path.basename(file_path)}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_dm_message(self):
        """发送私聊消息（电脑端）"""
        message = self.message_edit.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        to_user = self.dm_target.text().strip()
        if not to_user:
            QMessageBox.warning(self, "提示", "请输入私聊目标用户ID")
            return
        
        self.run_async(
            self.sender.send_dm_message(to_user, message),
            lambda r: self.on_message_sent(f"私聊@{to_user}: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_dm_message_mobile(self):
        """发送私聊消息（手机端）"""
        message = self.message_input_m.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        to_user = self.target_input_m.text().strip()
        if not to_user:
            QMessageBox.warning(self, "提示", "请输入私聊目标用户ID")
            return
        
        self.run_async(
            self.sender.send_dm_message(to_user, message),
            lambda r: self.on_message_sent_mobile(f"私聊@{to_user}: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_dm(self):
        """发送私聊（独立功能）"""
        to_user = self.dm_target_input.text().strip()
        if not to_user:
            QMessageBox.warning(self, "提示", "请输入私聊目标用户ID")
            return
        
        message = self.dm_message.text().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入私聊内容")
            return
        
        self.run_async(
            self.sender.send_dm_message(to_user, message),
            lambda r: self.on_message_sent(f"私聊@{to_user}: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_dm_mobile(self):
        """发送私聊（手机端）"""
        to_user = self.dm_target_m.text().strip()
        if not to_user:
            QMessageBox.warning(self, "提示", "请输入私聊目标用户ID")
            return
        
        message = self.dm_message_m.text().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入私聊内容")
            return
        
        self.run_async(
            self.sender.send_dm_message(to_user, message),
            lambda r: self.on_message_sent_mobile(f"私聊@{to_user}: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def send_dm_spam(self):
        """发送私聊刷屏"""
        to_user = self.dm_target_input.text().strip()
        if not to_user:
            QMessageBox.warning(self, "提示", "请输入私聊目标用户ID")
            return
        
        message = self.dm_message.text().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入私聊内容")
            return
        
        count, ok1 = QInputDialog.getInt(
            self, "私聊刷屏", "请输入刷屏次数:", 5, 1, 100, 1
        )
        
        if not ok1:
            return
        
        interval, ok2 = QInputDialog.getDouble(
            self, "私聊刷屏", "请输入刷屏间隔(秒):", 1.0, 0.1, 10.0, 1
        )
        
        if not ok2:
            return
        
        reply = QMessageBox.question(
            self, "确认私聊刷屏",
            f"确认要向 @{to_user} 私聊刷屏 {count} 次吗？\n"
            f"间隔: {interval}秒",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.run_dm_spam(to_user, message, count, interval)
    
    def send_dm_spam_mobile(self):
        """发送私聊刷屏（手机端）"""
        to_user = self.dm_target_m.text().strip()
        if not to_user:
            QMessageBox.warning(self, "提示", "请输入私聊目标用户ID")
            return
        
        message = self.dm_message_m.text().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入私聊内容")
            return
        
        count, ok1 = QInputDialog.getInt(
            self, "私聊刷屏", "请输入刷屏次数:", 5, 1, 100, 1
        )
        
        if not ok1:
            return
        
        interval, ok2 = QInputDialog.getDouble(
            self, "私聊刷屏", "请输入刷屏间隔(秒):", 1.0, 0.1, 10.0, 1
        )
        
        if not ok2:
            return
        
        reply = QMessageBox.question(
            self, "确认私聊刷屏",
            f"确认要向 @{to_user} 私聊刷屏 {count} 次吗？\n"
            f"间隔: {interval}秒",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.run_dm_spam(to_user, message, count, interval)
    
    def run_dm_spam(self, to_user, message, count, interval):
        """运行私聊刷屏任务"""
        async def dm_spam_task():
            success, fail = 0, 0
            
            for i in range(count):
                try:
                    ok = await self.sender.send_dm_message(to_user, message)
                    if ok:
                        success += 1
                    else:
                        fail += 1
                    self.log_message(f"[{i+1}/{count}] 私聊 {'✓' if ok else '✗'}")
                except Exception as e:
                    fail += 1
                    self.log_message(f"[{i+1}/{count}] ✗ 错误: {str(e)[:50]}")
                
                if i < count - 1:
                    await asyncio.sleep(interval)
            
            return success, fail
        
        def on_finished(result):
            success, failed = result
            QMessageBox.information(
                self, "私聊刷屏完成",
                f"私聊刷屏完成!\n成功: {success}次\n失败: {failed}次"
            )
        
        def on_error(error):
            QMessageBox.critical(self, "私聊刷屏错误", f"私聊刷屏失败: {error}")
        
        self.run_async(dm_spam_task(), on_finished, on_error)
    
    def send_reply(self):
        """发送引用回复"""
        index = self.reply_index.value() - 1
        message = self.reply_message.text().strip()
        
        if not message:
            QMessageBox.warning(self, "提示", "请输入回复内容")
            return
        
        # 从消息记录中获取要引用的消息
        if index < 0 or index >= len(self.message_history):
            QMessageBox.warning(self, "提示", "消息序号无效")
            return
        
        ref_msg = self.message_history[index]
        ref_msg_id = ref_msg.get("msg_id", "")
        
        if not ref_msg_id:
            QMessageBox.warning(self, "提示", "无法获取引用消息ID")
            return
        
        at_user, ok = QInputDialog.getText(
            self, "引用回复", "输入要艾特的用户ID (留空则不艾特):"
        )
        
        if ok:
            at_nick = self.sender.user_db.get(at_user, at_user) if self.sender else at_user
            self.run_async(
                self.send_reply_message(message, ref_msg_id, at_user, at_nick),
                lambda r: self.on_message_sent(f"引用回复{index+1}: {message[:30]}"),
                lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
            )
    
    def send_reply_mobile(self):
        """发送引用回复（手机端）"""
        index = self.reply_index_m.value() - 1
        message = self.reply_message_m.text().strip()
        
        if not message:
            QMessageBox.warning(self, "提示", "请输入回复内容")
            return
        
        # 从消息记录中获取要引用的消息
        if index < 0 or index >= len(self.message_history):
            QMessageBox.warning(self, "提示", "消息序号无效")
            return
        
        ref_msg = self.message_history[index]
        ref_msg_id = ref_msg.get("msg_id", "")
        
        if not ref_msg_id:
            QMessageBox.warning(self, "提示", "无法获取引用消息ID")
            return
        
        at_user, ok = QInputDialog.getText(
            self, "引用回复", "输入要艾特的用户ID (留空则不艾特):"
        )
        
        if ok:
            at_nick = self.sender.user_db.get(at_user, at_user) if self.sender else at_user
            self.run_async(
                self.send_reply_message(message, ref_msg_id, at_user, at_nick),
                lambda r: self.on_message_sent_mobile(f"引用回复{index+1}: {message[:30]}"),
                lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
            )
    
    async def send_reply_message(self, message, ref_msg_id, at_user="", at_nick=""):
        """发送引用回复消息"""
        if not self.sender or not self.sender.connected:
            raise Exception("未连接")
        
        # 构建引用回复消息
        if at_user:
            # 引用+艾特
            return await self.sender.send_reply_with_at(message, ref_msg_id, at_user, at_nick)
        else:
            # 纯引用
            return await self.sender.send_reply(message, ref_msg_id)
    
    def send_reply_spam(self):
        """发送引用刷屏"""
        index = self.reply_index.value() - 1
        message = self.reply_message.text().strip()
        
        if not message:
            QMessageBox.warning(self, "提示", "请输入回复内容")
            return
        
        # 从消息记录中获取要引用的消息
        if index < 0 or index >= len(self.message_history):
            QMessageBox.warning(self, "提示", "消息序号无效")
            return
        
        ref_msg = self.message_history[index]
        ref_msg_id = ref_msg.get("msg_id", "")
        
        if not ref_msg_id:
            QMessageBox.warning(self, "提示", "无法获取引用消息ID")
            return
        
        at_user, ok1 = QInputDialog.getText(
            self, "引用刷屏", "输入要艾特的用户ID (留空则不艾特):"
        )
        
        if not ok1:
            return
        
        count, ok2 = QInputDialog.getInt(
            self, "引用刷屏", "请输入刷屏次数:", 5, 1, 100, 1
        )
        
        if not ok2:
            return
        
        interval, ok3 = QInputDialog.getDouble(
            self, "引用刷屏", "请输入刷屏间隔(秒):", 1.0, 0.1, 10.0, 1
        )
        
        if not ok3:
            return
        
        reply = QMessageBox.question(
            self, "确认引用刷屏",
            f"确认要引用刷屏 {count} 次吗？\n"
            f"间隔: {interval}秒",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.run_reply_spam(message, ref_msg_id, at_user, count, interval)
    
    def send_reply_spam_mobile(self):
        """发送引用刷屏（手机端）"""
        index = self.reply_index_m.value() - 1
        message = self.reply_message_m.text().strip()
        
        if not message:
            QMessageBox.warning(self, "提示", "请输入回复内容")
            return
        
        # 从消息记录中获取要引用的消息
        if index < 0 or index >= len(self.message_history):
            QMessageBox.warning(self, "提示", "消息序号无效")
            return
        
        ref_msg = self.message_history[index]
        ref_msg_id = ref_msg.get("msg_id", "")
        
        if not ref_msg_id:
            QMessageBox.warning(self, "提示", "无法获取引用消息ID")
            return
        
        at_user, ok1 = QInputDialog.getText(
            self, "引用刷屏", "输入要艾特的用户ID (留空则不艾特):"
        )
        
        if not ok1:
            return
        
        count, ok2 = QInputDialog.getInt(
            self, "引用刷屏", "请输入刷屏次数:", 5, 1, 100, 1
        )
        
        if not ok2:
            return
        
        interval, ok3 = QInputDialog.getDouble(
            self, "引用刷屏", "请输入刷屏间隔(秒):", 1.0, 0.1, 10.0, 1
        )
        
        if not ok3:
            return
        
        reply = QMessageBox.question(
            self, "确认引用刷屏",
            f"确认要引用刷屏 {count} 次吗？\n"
            f"间隔: {interval}秒",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.run_reply_spam_mobile(message, ref_msg_id, at_user, count, interval)
    
    def run_reply_spam(self, message, ref_msg_id, at_user, count, interval):
        """运行引用刷屏任务"""
        async def reply_spam_task():
            at_nick = self.sender.user_db.get(at_user, at_user) if self.sender else at_user
            success, fail = 0, 0
            
            for i in range(count):
                try:
                    if at_user:
                        ok = await self.sender.send_reply_with_at(message, ref_msg_id, at_user, at_nick)
                    else:
                        ok = await self.sender.send_reply(message, ref_msg_id)
                    
                    if ok:
                        success += 1
                    else:
                        fail += 1
                    self.log_message(f"[{i+1}/{count}] 引用刷屏 {'✓' if ok else '✗'}")
                except Exception as e:
                    fail += 1
                    self.log_message(f"[{i+1}/{count}] ✗ 错误: {str(e)[:50]}")
                
                if i < count - 1:
                    await asyncio.sleep(interval)
            
            return success, fail
        
        def on_finished(result):
            success, failed = result
            QMessageBox.information(
                self, "引用刷屏完成",
                f"引用刷屏完成!\n成功: {success}次\n失败: {failed}次"
            )
        
        def on_error(error):
            QMessageBox.critical(self, "引用刷屏错误", f"引用刷屏失败: {error}")
        
        self.run_async(reply_spam_task(), on_finished, on_error)
    
    def run_reply_spam_mobile(self, message, ref_msg_id, at_user, count, interval):
        """运行引用刷屏任务（手机端）"""
        async def reply_spam_task():
            at_nick = self.sender.user_db.get(at_user, at_user) if self.sender else at_user
            success, fail = 0, 0
            
            for i in range(count):
                try:
                    if at_user:
                        ok = await self.sender.send_reply_with_at(message, ref_msg_id, at_user, at_nick)
                    else:
                        ok = await self.sender.send_reply(message, ref_msg_id)
                    
                    if ok:
                        success += 1
                    else:
                        fail += 1
                    self.log_message_mobile(f"[{i+1}/{count}] 引用刷屏 {'✓' if ok else '✗'}")
                except Exception as e:
                    fail += 1
                    self.log_message_mobile(f"[{i+1}/{count}] ✗ 错误: {str(e)[:50]}")
                
                if i < count - 1:
                    await asyncio.sleep(interval)
            
            return success, fail
        
        def on_finished(result):
            success, failed = result
            QMessageBox.information(
                self, "引用刷屏完成",
                f"引用刷屏完成!\n成功: {success}次\n失败: {failed}次"
            )
        
        def on_error(error):
            QMessageBox.critical(self, "引用刷屏错误", f"引用刷屏失败: {error}")
        
        self.run_async(reply_spam_task(), on_finished, on_error)
    
    def send_multi_at(self):
        """发送批量艾特"""
        users_text = self.multi_at_users.text().strip()
        if not users_text:
            QMessageBox.warning(self, "提示", "请输入用户ID，多个用逗号分隔")
            return
        
        message = self.multi_at_msg.text().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        
        users = [uid.strip() for uid in users_text.split(',') if uid.strip()]
        if not users:
            QMessageBox.warning(self, "提示", "请输入有效的用户ID")
            return
        
        # 获取用户昵称
        at_users = []
        for uid in users:
            nick = self.sender.user_db.get(uid, uid) if self.sender else uid
            at_users.append((uid, nick))
        
        self.run_async(
            self.sender.send_multi_at_message(message, at_users),
            lambda r: self.on_message_sent(f"批量艾特{len(users)}人: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def multi_at_mobile(self):
        """批量艾特（手机端）"""
        users_text, ok1 = QInputDialog.getText(
            self, "批量艾特", "请输入用户ID，多个用逗号分隔:"
        )
        
        if not ok1 or not users_text:
            return
        
        message, ok2 = QInputDialog.getText(
            self, "批量艾特", "请输入消息内容:"
        )
        
        if not ok2 or not message:
            return
        
        users = [uid.strip() for uid in users_text.split(',') if uid.strip()]
        if not users:
            QMessageBox.warning(self, "提示", "请输入有效的用户ID")
            return
        
        # 获取用户昵称
        at_users = []
        for uid in users:
            nick = self.sender.user_db.get(uid, uid) if self.sender else uid
            at_users.append((uid, nick))
        
        self.run_async(
            self.sender.send_multi_at_message(message, at_users),
            lambda r: self.on_message_sent_mobile(f"批量艾特{len(users)}人: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def at_all_members(self):
        """艾特全体成员"""
        message, ok = QInputDialog.getText(
            self, "艾特全体", "请输入消息内容:"
        )
        
        if not ok or not message:
            return
        
        reply = QMessageBox.warning(
            self, "警告",
            "艾特全体成员可能会引起用户反感，确认要继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 获取所有成员
            if not self.user_list:
                QMessageBox.warning(self, "提示", "请先刷新成员列表")
                return
            
            at_users = [(uid, nick) for uid, nick in self.user_list]
            
            self.run_async(
                self.sender.send_multi_at_message(message, at_users),
                lambda r: self.on_message_sent(f"艾特全体{len(at_users)}人: {message[:30]}"),
                lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
            )
    
    def at_all_members_mobile(self):
        """艾特全体成员（手机端）"""
        message, ok = QInputDialog.getText(
            self, "艾特全体", "请输入消息内容:"
        )
        
        if not ok or not message:
            return
        
        reply = QMessageBox.warning(
            self, "警告",
            "艾特全体成员可能会引起用户反感，确认要继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 获取所有成员
            if not self.user_list:
                QMessageBox.warning(self, "提示", "请先刷新成员列表")
                return
            
            at_users = [(uid, nick) for uid, nick in self.user_list]
            
            self.run_async(
                self.sender.send_multi_at_message(message, at_users),
                lambda r: self.on_message_sent_mobile(f"艾特全体{len(at_users)}人: {message[:30]}"),
                lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
            )
    
    def send_at_all_mobile(self, message):
        """发送艾特全体消息（手机端）"""
        if not self.user_list:
            QMessageBox.warning(self, "提示", "请先刷新成员列表")
            return
        
        at_users = [(uid, nick) for uid, nick in self.user_list]
        
        self.run_async(
            self.sender.send_multi_at_message(message, at_users),
            lambda r: self.on_message_sent_mobile(f"艾特全体{len(at_users)}人: {message[:30]}"),
            lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
        )
    
    def browse_image(self):
        """浏览图片文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.gif *.bmp)"
        )
        
        if file_path:
            if self.is_mobile:
                self.file_path_m.setText(file_path)
            else:
                self.file_path.setText(file_path)
                
                # 预览图片
                pixmap = QPixmap(file_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio)
                    self.image_preview.setPixmap(scaled)
    
    def browse_upload_file(self):
        """浏览上传文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "",
            "所有文件 (*.*)"
        )
        
        if file_path:
            self.upload_path.setText(file_path)
    
    def upload_and_send(self):
        """上传并发送文件"""
        file_path = self.upload_path.text().strip()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "提示", "请选择有效的文件")
            return
        
        # 检查文件类型
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
            # 发送图片
            self.run_async(
                self.sender.send_image(file_path),
                lambda r: self.on_message_sent(f"图片: {os.path.basename(file_path)}"),
                lambda e: QMessageBox.critical(self, "错误", f"发送失败: {e}")
            )
        else:
            QMessageBox.warning(self, "提示", "目前只支持图片文件")
    
    def connect_bot(self):
        """连接机器人"""
        if self.is_connected:
            self.disconnect_bot()
            return
        
        if self.is_mobile:
            group_code = self.group_edit.text().strip()
        else:
            group_code = self.current_group
        
        if not group_code:
            QMessageBox.warning(self, "提示", "请输入群号")
            return
        
        self.current_group = group_code
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("连接中...")
        
        async def connect_task():
            self.sender = SpamSender()
            self.sender.group_code = group_code
            
            # 签票
            if not self.sender.sign_token():
                raise Exception("签票失败")
            
            # 连接WebSocket
            if not await self.sender.connect():
                raise Exception("WebSocket连接失败")
            
            # 启动接收循环
            asyncio.create_task(self.sender._receive_loop())
            
            return True
        
        def on_connected(result):
            self.is_connected = True
            self.connect_btn.setText("断开连接")
            self.connect_btn.setEnabled(True)
            self.status_label.setText(f"已连接到群 {self.current_group}")
            
            if self.is_mobile:
                self.connect_status.setText("🟢 在线")
                self.group_edit.setText(self.current_group)
                self.group_edit_settings.setText(self.current_group)
            else:
                self.status_text.setText(f"状态: 已连接")
                self.group_label.setText(f"当前群: {self.current_group}")
                self.group_edit_setting.setText(self.current_group)
            
            # 自动获取成员列表
            self.refresh_members()
            
            # 启用自动回复
            if self.auto_reply_enabled:
                self.enable_auto_reply()
        
        def on_error(error):
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("连接")
            QMessageBox.critical(self, "连接失败", f"连接失败: {error}")
            
            if self.is_mobile:
                self.connect_status.setText("🔴 离线")
        
        self.run_async(connect_task(), on_connected, on_error)
    
    def disconnect_bot(self):
        """断开连接"""
        async def disconnect_task():
            if self.sender:
                await self.sender.disconnect()
            return True
        
        def on_disconnected(result):
            self.is_connected = False
            self.connect_btn.setText("连接")
            self.status_label.setText("已断开连接")
            
            if self.is_mobile:
                self.connect_status.setText("🔴 离线")
            else:
                self.status_text.setText("状态: 未连接")
        
        self.run_async(disconnect_task(), on_disconnected, lambda e: on_disconnected(None))
    
    def refresh_members(self):
        """刷新成员列表"""
        if not self.is_connected:
            QMessageBox.warning(self, "提示", "请先连接")
            return
        
        self.run_async(
            self.sender.send_get_members_request(),
            self.on_members_refreshed,
            lambda e: QMessageBox.critical(self, "错误", f"获取成员失败: {e}")
        )
    
    def on_members_refreshed(self, result):
        """成员列表刷新回调"""
        if not result or result.get("code") != 0:
            QMessageBox.warning(self, "提示", f"获取成员失败: {result.get('message', '未知错误')}")
            return
        
        members = result.get("member_list", [])
        self.user_list = []
        
        # 更新用户数据库
        if self.sender:
            for member in members:
                uid = member.get("user_id", "")
                nick = member.get("nick_name", "")
                if uid:
                    self.sender.user_db[uid] = nick
        
        # 电脑端更新
        if not self.is_mobile:
            self.member_list.clear()
            self.at_combo.clear()
            
            for member in members:
                uid = member.get("user_id", "")
                nick = member.get("nick_name", "")
                utype = member.get("user_type", 0)
                
                if uid and uid != (self.sender.bot_id if self.sender else ""):
                    self.user_list.append((uid, nick))
                    
                    # 添加到成员列表
                    utype_str = {1: "成员", 2: "管理员", 3: "Bot"}.get(utype, "未知")
                    item_text = f"{nick} ({uid}) [{utype_str}]"
                    self.member_list.addItem(item_text)
                    
                    # 添加到艾特下拉框
                    self.at_combo.addItem(f"{nick} ({uid})")
        
        # 手机端更新
        else:
            self.member_list_m.clear()
            for member in members:
                uid = member.get("user_id", "")
                nick = member.get("nick_name", "")
                if uid and uid != (self.sender.bot_id if self.sender else ""):
                    self.user_list.append((uid, nick))
                    self.member_list_m.addItem(f"{nick} ({uid})")
        
        self.log_message(f"已更新成员列表: {len(members)} 人")
        
        # 更新用户列表显示
        self.update_user_list_display()
    
    def update_user_list_display(self):
        """更新用户列表显示"""
        if not self.is_mobile:
            self.user_list_widget.clear()
            for uid, nick in self.user_list:
                self.user_list_widget.addItem(f"{nick} ({uid})")
    
    def search_members(self, text):
        """搜索成员（电脑端）"""
        for i in range(self.member_list.count()):
            item = self.member_list.item(i)
            if text.lower() in item.text().lower():
                item.setHidden(False)
            else:
                item.setHidden(True)
    
    def search_members_mobile(self, text):
        """搜索成员（手机端）"""
        for i in range(self.member_list_m.count()):
            item = self.member_list_m.item(i)
            if text.lower() in item.text().lower():
                item.setHidden(False)
            else:
                item.setHidden(True)
    
    def find_my_id(self):
        """查找自己的ID（电脑端）"""
        nickname, ok = QInputDialog.getText(
            self, "查找自己", "请输入你的群昵称:"
        )
        
        if ok and nickname:
            found = False
            for uid, nick in self.user_list:
                if nickname.lower() in nick.lower():
                    QMessageBox.information(
                        self, "找到匹配用户",
                        f"昵称: {nick}\n用户ID: {uid}"
                    )
                    found = True
                    break
            
            if not found:
                QMessageBox.warning(self, "提示", f"未找到昵称包含'{nickname}'的用户")
    
    def find_my_id_mobile(self):
        """查找自己的ID（手机端）"""
        nickname, ok = QInputDialog.getText(
            self, "查找自己", "请输入你的群昵称:"
        )
        
        if ok and nickname:
            found = False
            for uid, nick in self.user_list:
                if nickname.lower() in nick.lower():
                    QMessageBox.information(
                        self, "找到匹配用户",
                        f"昵称: {nick}\n用户ID: {uid}"
                    )
                    found = True
                    break
            
            if not found:
                QMessageBox.warning(self, "提示", f"未找到昵称包含'{nickname}'的用户")
    
    def member_clicked(self, item):
        """电脑端成员点击事件"""
        text = item.text()
        if '(' in text and ')' in text:
            user_id = text.split('(')[-1].split(')')[0]
            self.message_edit.setPlainText(f"@{user_id} ")
            self.mode_at.setChecked(True)
    
    def member_clicked_mobile(self, item):
        """手机端成员点击事件"""
        text = item.text()
        if '(' in text and ')' in text:
            user_id = text.split('(')[-1].split(')')[0]
            self.message_input_m.setPlainText(f"@{user_id} ")
            self.mode_at_m.setChecked(True)
    
    def show_message_detail(self, item):
        """显示消息详情"""
        text = item.text()
        QMessageBox.information(self, "消息详情", text)
    
    def show_message_context_menu(self, position):
        """显示消息右键菜单"""
        menu = QMenu()
        
        copy_action = QAction("复制消息", self)
        copy_action.triggered.connect(self.copy_selected_message)
        
        reply_action = QAction("引用回复", self)
        reply_action.triggered.connect(self.reply_selected_message)
        
        menu.addAction(copy_action)
        menu.addAction(reply_action)
        menu.exec(self.message_list.mapToGlobal(position))
    
    def copy_selected_message(self):
        """复制选中的消息"""
        items = self.message_list.selectedItems()
        if items:
            QApplication.clipboard().setText(items[0].text())
    
    def reply_selected_message(self):
        """引用选中的消息"""
        items = self.message_list.selectedItems()
        if items:
            # 切换到发送消息标签页
            if not self.is_mobile:
                QMessageBox.information(self, "引用回复", "请在引用回复功能中使用此消息")
            else:
                QMessageBox.information(self, "引用回复", "请在高级功能中使用引用回复")
    
    def use_history_message(self, item):
        """使用历史消息"""
        text = item.text()
        if ':' in text:
            message = text.split(':', 1)[1].strip()
            if self.is_mobile:
                self.message_input_m.setPlainText(message)
            else:
                self.message_edit.setPlainText(message)
    
    def use_saved_user(self, item):
        """使用已保存的用户"""
        text = item.text()
        if '(' in text and ')' in text:
            user_id = text.split('(')[-1].split(')')[0]
            if self.is_mobile:
                self.target_input_m.setText(user_id)
                self.mode_at_m.setChecked(True)
            else:
                self.at_combo.setCurrentText(user_id)
                self.mode_at.setChecked(True)
    
    def on_message_sent(self, message):
        """消息发送成功（电脑端）"""
        self.log_message(f"[发送] {message}")
        self.message_edit.clear()
        
        # 添加到历史记录
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.history_list.addItem(f"{timestamp}: {message}")
        
        # 控制历史记录长度
        if self.history_list.count() > 100:
            self.history_list.takeItem(0)
    
    def on_message_sent_mobile(self, message):
        """消息发送成功（手机端）"""
        self.log_message_mobile(f"[发送] {message}")
        self.message_input_m.clear()
    
    def log_message(self, message):
        """记录消息到界面（电脑端）"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.message_list.addItem(log_entry)
        self.message_list.scrollToBottom()
        
        # 控制列表长度
        if self.message_list.count() > 1000:
            self.message_list.takeItem(0)
    
    def log_message_mobile(self, message):
        """记录消息到界面（手机端）"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.message_list_mobile.addItem(log_entry)
        self.message_list_mobile.scrollToBottom()
        
        # 控制列表长度
        if self.message_list_mobile.count() > 1000:
            self.message_list_mobile.takeItem(0)
    
    def show_recent_messages(self):
        """显示最近消息"""
        count, ok = QInputDialog.getInt(
            self, "最近消息", "显示最近多少条消息:", 10, 1, 100, 1
        )
        
        if ok:
            self.message_list.clear()
            recent_msgs = self.sender.msg_cache[-count:] if self.sender and hasattr(self.sender, 'msg_cache') else []
            for msg in recent_msgs:
                time = msg.get("time", "")
                sender = msg.get("sender_name", "")
                content = msg.get("content", "")
                self.message_list.addItem(f"[{time}] {sender}: {content}")
    
    def show_recent_messages_mobile(self):
        """显示最近消息（手机端）"""
        count, ok = QInputDialog.getInt(
            self, "最近消息", "显示最近多少条消息:", 10, 1, 100, 1
        )
        
        if ok:
            self.message_list_mobile.clear()
            recent_msgs = self.sender.msg_cache[-count:] if self.sender and hasattr(self.sender, 'msg_cache') else []
            for msg in recent_msgs:
                time = msg.get("time", "")
                sender = msg.get("sender_name", "")
                content = msg.get("content", "")
                self.message_list_mobile.addItem(f"[{time}] {sender}: {content}")
    
    def set_interval(self, value):
        """设置刷屏间隔"""
        self.spam_interval = value
    
    def set_interval_mobile(self, value):
        """设置刷屏间隔（手机端）"""
        self.spam_interval = value
    
    def toggle_auto_reply(self, state):
        """切换自动回复状态"""
        self.auto_reply_enabled = (state == Qt.CheckState.Checked.value)
        
        if self.auto_reply_enabled and self.is_connected:
            self.enable_auto_reply()
        elif not self.auto_reply_enabled and self.is_connected:
            self.disable_auto_reply()
    
    def enable_auto_reply(self):
        """启用自动回复"""
        # 这里可以设置自动回复的回调
        # 由于原sender.py已经有自动回复逻辑，我们只需要确保它被启用
        pass
    
    def disable_auto_reply(self):
        """禁用自动回复"""
        # 这里可以禁用自动回复
        pass
    
    def add_user(self):
        """添加用户"""
        user_id = self.add_user_id.text().strip()
        nick = self.add_user_nick.text().strip()
        
        if not user_id:
            QMessageBox.warning(self, "提示", "请输入用户ID")
            return
        
        if not nick:
            nick = user_id
        
        # 检查是否已存在
        for i in range(self.user_list_widget.count()):
            item = self.user_list_widget.item(i)
            if user_id in item.text():
                QMessageBox.warning(self, "提示", "用户已存在")
                return
        
        # 添加到用户列表
        self.user_list.append((user_id, nick))
        self.user_list_widget.addItem(f"{nick} ({user_id})")
        
        # 添加到艾特下拉框
        self.at_combo.addItem(f"{nick} ({user_id})")
        
        # 清空输入
        self.add_user_id.clear()
        self.add_user_nick.clear()
        
        QMessageBox.information(self, "提示", f"已添加用户: {nick} ({user_id})")
    
    def add_user_mobile(self):
        """添加用户（手机端）"""
        user_id, ok1 = QInputDialog.getText(
            self, "添加用户", "请输入用户ID:"
        )
        
        if not ok1 or not user_id:
            return
        
        nick, ok2 = QInputDialog.getText(
            self, "添加用户", "请输入用户昵称:"
        )
        
        if not ok2:
            return
        
        if not nick:
            nick = user_id
        
        # 检查是否已存在
        for uid, existing_nick in self.user_list:
            if user_id == uid:
                QMessageBox.warning(self, "提示", "用户已存在")
                return
        
        # 添加到用户列表
        self.user_list.append((user_id, nick))
        self.member_list_m.addItem(f"{nick} ({user_id})")
        
        QMessageBox.information(self, "提示", f"已添加用户: {nick} ({user_id})")
    
    def delete_user(self):
        """删除用户"""
        items = self.user_list_widget.selectedItems()
        if not items:
            QMessageBox.warning(self, "提示", "请选择要删除的用户")
            return
        
        item = items[0]
        text = item.text()
        
        if '(' in text and ')' in text:
            user_id = text.split('(')[-1].split(')')[0]
            
            reply = QMessageBox.question(
                self, "确认删除",
                f"确认要删除用户 '{text}' 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # 从用户列表中删除
                self.user_list = [(uid, nick) for uid, nick in self.user_list if uid != user_id]
                
                # 从列表控件中删除
                row = self.user_list_widget.row(item)
                self.user_list_widget.takeItem(row)
                
                # 从艾特下拉框中删除
                index = self.at_combo.findText(f"({user_id})", Qt.MatchFlag.MatchContains)
                if index >= 0:
                    self.at_combo.removeItem(index)
                
                QMessageBox.information(self, "提示", f"已删除用户: {text}")
    
    def delete_user_mobile(self):
        """删除用户（手机端）"""
        items = self.member_list_m.selectedItems()
        if not items:
            QMessageBox.warning(self, "提示", "请选择要删除的用户")
            return
        
        item = items[0]
        text = item.text()
        
        if '(' in text and ')' in text:
            user_id = text.split('(')[-1].split(')')[0]
            
            reply = QMessageBox.question(
                self, "确认删除",
                f"确认要删除用户 '{text}' 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # 从用户列表中删除
                self.user_list = [(uid, nick) for uid, nick in self.user_list if uid != user_id]
                
                # 从列表控件中删除
                row = self.member_list_m.row(item)
                self.member_list_m.takeItem(row)
                
                QMessageBox.information(self, "提示", f"已删除用户: {text}")
    
    def show_sticker_list(self):
        """显示贴纸列表"""
        from sender import SpamSender
        stickers = list(SpamSender.STICKERS.keys())
        
        sticker_text = "可用贴纸列表:\n"
        for i, sticker in enumerate(stickers, 1):
            sticker_text += f"{i:2d}. {sticker}\n"
            if i % 10 == 0:
                sticker_text += "\n"
        
        QMessageBox.information(self, "贴纸列表", sticker_text)
    
    def show_sticker_list_mobile(self):
        """显示贴纸列表（手机端）"""
        from sender import SpamSender
        stickers = list(SpamSender.STICKERS.keys())
        
        sticker_text = "可用贴纸列表:\n"
        for i, sticker in enumerate(stickers, 1):
            sticker_text += f"{i:2d}. {sticker}\n"
            if i % 10 == 0:
                sticker_text += "\n"
        
        QMessageBox.information(self, "贴纸列表", sticker_text)
    
    def show_help(self):
        """显示帮助"""
        help_text = """命令列表对应的GUI功能:

<文字>            - 发送普通消息: 在发送消息页面使用
/at 用户ID 内容   - 艾特指定用户发送: 选择艾特模式，选择用户
/spam 内容 次数   - 普通刷屏: 选择刷屏模式，设置次数
/sticker_spam 贴纸名 次数 - 贴纸刷屏: 在贴纸页面使用
/atspam 用户ID 内容 次数  - 艾特+刷屏: 选择艾特模式+刷屏模式
/multiat 用户ID1,ID2,... 内容 - 批量艾特多人: 选择批量艾特模式
/atall 内容      - 艾特全体成员: 在群成员页面使用
/image 图片路径  - 发送图片: 在文件管理页面使用
/spamat 同上     - 同上
/reply 序号 内容  - 引用回复: 在高级功能页面使用
/reply 序号 @用户ID 内容  - 引用+艾特回复: 在高级功能页面使用
/replyspam 序号 内容 次数 - 引用刷屏: 在高级功能页面使用
/group 群号       - 切换目标群: 在设置页面修改
/interval 秒      - 设置刷屏间隔: 在设置页面修改
/users            - 查看已保存的用户列表: 在用户管理页面查看
/adduser 用户ID 昵称 - 添加常用用户: 在用户管理页面添加
/deluser 用户ID   - 删除用户: 在用户管理页面删除
/sticker 贴纸名   - 发送贴纸: 在贴纸页面点击贴纸
/sticker 贴纸名 文字 - 发送贴纸+文字: 在贴纸页面点击贴纸后修改消息
/sticker 贴纸名 @用户ID 文字 - 发送贴纸+艾特+文字: 在贴纸页面点击贴纸后选择艾特
/stickerlist      - 查看所有可用贴纸: 在贴纸页面使用
/stickerfind 关键词 - 搜索贴纸: 在贴纸页面搜索
/dm 用户ID 内容   - 发送私聊消息: 在高级功能页面使用
/dmspam 用户ID 内容 次数 - 私聊刷屏: 在高级功能页面使用
/members          - 获取当前群成员列表: 在群成员页面刷新
/myid 昵称        - 在成员列表中搜索自己的ID: 在群成员页面使用
/recent [N]       - 查看最近 N 条消息: 在消息中心页面使用
/help             - 显示帮助: 当前页面
/exit             - 退出: 关闭窗口
"""
        QMessageBox.information(self, "帮助", help_text)
    
    def show_help_mobile(self):
        """显示帮助（手机端）"""
        self.show_help()
    
    def show_about(self):
        """显示关于"""
        about_text = """元宝 Bot 增强发送器
版本: 2.0.0
功能: 完整可视化界面，支持所有命令行功能
作者: 腾讯
"""
        QMessageBox.about(self, "关于", about_text)
    
    def save_settings(self):
        """保存设置"""
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if self.is_mobile:
                config['AUTO_REPLY_GROUP_TEXT'] = self.group_reply_edit.text()
                config['AUTO_REPLY_C2C_TEXT'] = self.c2c_reply_edit.text()
            else:
                config['AUTO_REPLY_GROUP_TEXT'] = self.group_reply_edit_d.toPlainText()
                config['AUTO_REPLY_C2C_TEXT'] = self.c2c_reply_edit_d.toPlainText()
            
            # 保存当前群号
            if self.is_mobile:
                config['DEFAULT_GROUP_CODE'] = self.group_edit_settings.text()
            else:
                config['DEFAULT_GROUP_CODE'] = self.group_edit_setting.text()
            
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            QMessageBox.information(self, "提示", "设置保存成功")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
    
    def closeEvent(self, event):
        """关闭窗口事件"""
        if self.is_connected:
            self.disconnect_bot()
        
        # 停止异步循环
        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        
        event.accept()


def main():
    app = QApplication(sys.argv)
    
    # 设置应用信息
    app.setApplicationName("元宝 Bot 增强发送器")
    app.setOrganizationName("腾讯")
    
    # 设置字体
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()