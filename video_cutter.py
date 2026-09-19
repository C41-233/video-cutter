#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简易视频切割器
支持：播放/暂停、拖拽进度条、标记起止点、裁剪
依赖：opencv-python, pillow, tkinter (内置)
"""

import cv2
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw
import subprocess
import os
import re
import shutil
import ctypes
import ctypes.wintypes
import threading

def _find_ffmpeg():
    """定位 ffmpeg.exe（优先上级目录，兜底脚本目录和PATH）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(script_dir), "ffmpeg.exe"),
        os.path.join(script_dir, "ffmpeg.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    found = shutil.which("ffmpeg.exe")
    return found if found else "ffmpeg.exe"


FFMPEG_PATH = _find_ffmpeg()


class CancelError(Exception):
    pass


class VideoCutter:
    def __init__(self):
        # 必须在创建任何窗口之前设置 AppUserModelID，
        # 否则任务栏仍显示 pythonw.exe 的图标
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VideoCutter.App")
        except Exception:
            pass

        self.root = tk.Tk()
        self.root.title("简易视频切割器")
        self.root.geometry("960x640")

        # 设置窗口图标（Tk 原生 iconphoto，蓝底白三角）
        try:
            icon = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(icon)
            d.rounded_rectangle([4, 4, 60, 60], radius=14, fill=(74, 144, 217, 255))
            d.polygon([(22, 16), (22, 48), (46, 32)], fill=(255, 255, 255, 255))
            self._icon_img = ImageTk.PhotoImage(icon)
            self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

        self.root.minsize(640, 480)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 禁用输入法，防止快捷键被 IME 拦截
        try:
            imm32 = ctypes.windll.imm32
            hwnd = self.root.winfo_id()
            imm32.ImmAssociateContext(ctypes.wintypes.HWND(hwnd), None)
        except Exception:
            pass

        # 活跃子进程追踪（用于退出时清理）
        self._running_procs = []
        self._running = True

        # 视频状态
        self.cap = None
        self.video_path = None
        self.total_frames = 0
        self.fps = 30.0
        self.duration = 0.0
        self.current_frame = 0
        self.is_playing = False
        self.is_seeking = False
        self.was_playing_before_seek = False

        # 标记点（帧号）
        self.mark_in_frame = None
        self.mark_out_frame = None

        # 当前显示的图像
        self.photo = None

        # 关键帧吸附后的实际裁剪时间
        self.mark_in_time = None
        self.mark_out_time = None

        # 裁剪完成窗口的「删除源文件」勾选状态（同一进程内跨裁剪保持）
        self.delete_source_var = tk.BooleanVar(value=False)

        self.setup_ui()
        self._enable_drag_drop()

    def _on_close(self):
        """关闭窗口时清理所有子进程"""
        self._running = False
        for p in self._running_procs:
            try:
                p.kill()
            except Exception:
                pass
        self.root.destroy()

    # ── 界面搭建 ──────────────────────────────────────────────

    def setup_ui(self):
        # 自定义按钮样式（大图标）
        style = ttk.Style()
        style.configure('Play.TButton', font=('Segoe UI', 14))

        # 顶部工具栏（只有打开文件和裁剪按钮）
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 0))

        ttk.Button(toolbar, text="📂 打开文件", command=self.open_video, takefocus=False).pack(side=tk.LEFT, padx=2)
        self.close_file_btn = ttk.Button(toolbar, text="✕ 关闭文件", command=self._close_video,
                                         takefocus=False)
        self.close_file_btn.pack(side=tk.LEFT, padx=2)
        self.close_file_btn.pack_forget()  # 初始隐藏

        # 视频显示区域
        video_frame = ttk.Frame(self.root, relief=tk.SUNKEN, borderwidth=2)
        video_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)
        video_frame.pack_propagate(False)

        self.video_label = ttk.Label(video_frame, text="打开视频文件开始使用\n\n快捷键：\n  空格 = 播放/暂停\n  ←/→ = 后退/快进 5 秒\n  A/D  = 逐秒进退\n  Ctrl+A/D = 逐帧进退\n  Z    = 标记起点\n  X    = 标记终点\n\n或将视频文件拖入窗口",
                                     anchor=tk.CENTER, justify=tk.CENTER)
        self.video_label.pack(fill=tk.BOTH, expand=True)

        # 进度条 + 标记 + 时间
        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0, 2))

        self.time_label = ttk.Label(progress_frame, text="0:00:00.00 / 0:00:00.00", width=24)
        self.time_label.pack(side=tk.RIGHT)

        # 自定义进度条（Canvas 绘制：轨道 + 滑块 + 标记竖线）
        self.progress_canvas = tk.Canvas(progress_frame, height=28, highlightthickness=0, bd=0,
                                          cursor='hand2')
        self.progress_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.progress_canvas.bind('<Configure>', lambda e: self._update_progress_canvas())
        self.progress_canvas.bind('<ButtonPress-1>', self._on_progress_press)
        self.progress_canvas.bind('<B1-Motion>', self._on_overlay_motion)
        self.progress_canvas.bind('<ButtonRelease-1>', self._on_progress_release)
        self.progress_canvas.bind('<Button-3>', lambda e: 'break')

        # 播放控制行
        ctrl = ttk.Frame(self.root)
        ctrl.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(4, 4))

        left_info = ttk.Frame(ctrl)
        left_info.pack(side=tk.LEFT)
        self.mark_in_lbl = ttk.Label(left_info, text="起点: ─", width=16)
        self.mark_in_lbl.pack()

        center = ttk.Frame(ctrl)
        center.pack(side=tk.LEFT, expand=True)
        self.mark_in_btn = ttk.Button(center, text="⏮ 标记起点",
                                      command=self.mark_in, state=tk.DISABLED, takefocus=False)
        self.mark_in_btn.pack(side=tk.LEFT, padx=2)

        self.step_back_btn = ttk.Button(center, text="|◀", style='Play.TButton',
                                        command=lambda: self.frame_step(-1), state=tk.DISABLED,
                                        width=3, takefocus=False)
        self.step_back_btn.pack(side=tk.LEFT, padx=2)

        self.seek_back_btn = ttk.Button(center, text="⏪", command=lambda: self.seek_seconds(-1),
                                        state=tk.DISABLED, style='Play.TButton', width=3, takefocus=False)
        self.seek_back_btn.pack(side=tk.LEFT, padx=2)

        self.play_btn = ttk.Button(center, text="▶", command=self.toggle_play,
                                   state=tk.DISABLED, style='Play.TButton', width=3, takefocus=False)
        self.play_btn.pack(side=tk.LEFT, padx=2)

        self.seek_fwd_btn = ttk.Button(center, text="⏩", command=lambda: self.seek_seconds(1),
                                       state=tk.DISABLED, style='Play.TButton', width=3, takefocus=False)
        self.seek_fwd_btn.pack(side=tk.LEFT, padx=2)

        self.step_fwd_btn = ttk.Button(center, text="▶|", style='Play.TButton',
                                       command=lambda: self.frame_step(1), state=tk.DISABLED,
                                       width=3, takefocus=False)
        self.step_fwd_btn.pack(side=tk.LEFT, padx=2)

        self.mark_out_btn = ttk.Button(center, text="标记终点 ⏭",
                                       command=self.mark_out, state=tk.DISABLED, takefocus=False)
        self.mark_out_btn.pack(side=tk.LEFT, padx=2)

        right_info = ttk.Frame(ctrl)
        right_info.pack(side=tk.RIGHT)
        self.mark_out_lbl = ttk.Label(right_info, text="终点: ─", width=14)
        self.mark_out_lbl.pack()

        # 裁剪按钮行
        cut_row = ttk.Frame(self.root)
        cut_row.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0, 4))
        self.cut_btn = tk.Button(cut_row, text="✂ 裁剪", command=self.cut_video,
                                 width=20, font=('', 10),
                                 relief=tk.RAISED, bd=1, cursor='hand2', takefocus=False)
        self.cut_btn.pack()

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        status = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status.pack(side=tk.BOTTOM, fill=tk.X)

        # 键盘快捷键
        self.root.bind("<space>", lambda e: self.toggle_play())
        self.root.bind("a", lambda e: self.seek_seconds(-1))
        self.root.bind("A", lambda e: self.seek_seconds(-1))
        self.root.bind("d", lambda e: self.seek_seconds(1))
        self.root.bind("D", lambda e: self.seek_seconds(1))
        self.root.bind("<Control-a>", lambda e: self.frame_step(-1))
        self.root.bind("<Control-d>", lambda e: self.frame_step(1))
        self.root.bind("z", lambda e: self.mark_in())
        self.root.bind("Z", lambda e: self.mark_in())
        self.root.bind("x", lambda e: self.mark_out())
        self.root.bind("X", lambda e: self.mark_out())
        self.root.bind("<Left>", lambda e: self.seek_seconds(-5))
        self.root.bind("<Right>", lambda e: self.seek_seconds(5))

        # 启动帧更新轮询
        self.running = True
        self._poll()

    # ── 打开视频 ──────────────────────────────────────────────

    def open_video(self):
        path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[("视频文件", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.ts *.m2ts *.mts"),
                       ("所有文件", "*.*")]
        )
        if path:
            self._load_video(path)

    # ── 帧显示 ────────────────────────────────────────────────

    def _show_frame(self, frame):
        if frame is None:
            return
        h, w = frame.shape[:2]

        # 适配 video_label 尺寸
        lw = max(self.video_label.winfo_width(), 200)
        lh = max(self.video_label.winfo_height(), 150)

        scale = min(lw / w, lh / h, 1.0)
        if scale < 1.0:
            new_w, new_h = int(w * scale), int(h * scale)
        else:
            new_w, new_h = w, h

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb).resize((new_w, new_h), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(img)
        self.video_label.configure(image=self.photo, text="")

    def _update_time(self):
        cur = self.current_frame / self.fps
        self.time_label.configure(text=f"{self._fmt(cur)} / {self._fmt(self.duration)}")

    @staticmethod
    def _fmt(sec):
        h = int(sec / 3600)
        r = sec - h * 3600
        m = int(r / 60)
        s = r - m * 60
        return f"{h}:{m:02d}:{s:05.2f}"

    @staticmethod
    def _fmt_dur(sec):
        """秒数格式化为 HH:MM:SS"""
        h = int(sec // 3600)
        m = int(sec % 3600 // 60)
        s = int(sec % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def _fmt_size(n):
        """字节数格式化为 B/KB/MB/GB，小数末尾 0 不显示"""
        size = float(n)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024 or unit == 'GB':
                s = f"{size:.3f}".rstrip('0').rstrip('.')
                return f"{s} {unit}"
            size /= 1024

    def _close_video(self):
        """关闭当前视频，恢复初始状态"""
        if self.cap:
            self.is_playing = False
            self.cap.release()
            self.cap = None
        self.video_path = None
        self.total_frames = 0
        self.duration = 0.0
        self.current_frame = 0
        self.mark_in_frame = None
        self.mark_out_frame = None
        self.video_label.configure(image='', text="打开视频文件开始使用\n\n快捷键：\n  空格 = 播放/暂停\n  ←/→ = 后退/快进 5 秒\n  A/D  = 逐秒进退\n  Ctrl+A/D = 逐帧进退\n  Z    = 标记起点\n  X    = 标记终点\n\n或将视频文件拖入窗口")
        self.photo = None
        self.progress_canvas.delete('all')
        self.time_label.configure(text="0:00:00.00 / 0:00:00.00")
        self.mark_in_lbl.configure(text="起点: ─")
        self.mark_out_lbl.configure(text="终点: ─")
        self.play_btn.configure(state=tk.DISABLED, text="▶")
        self.step_back_btn.configure(state=tk.DISABLED)
        self.seek_back_btn.configure(state=tk.DISABLED)
        self.seek_fwd_btn.configure(state=tk.DISABLED)
        self.step_fwd_btn.configure(state=tk.DISABLED)
        self.mark_in_btn.configure(state=tk.DISABLED)
        self.mark_out_btn.configure(state=tk.DISABLED)
        self.mark_in_time = None
        self.mark_out_time = None
        self.close_file_btn.pack_forget()
        self.status_var.set("就绪")

    # ── 播放控制 ──────────────────────────────────────────────

    def toggle_play(self):
        if self.cap is None:
            return
        self.is_playing = not self.is_playing
        self.play_btn.configure(text="⏸" if self.is_playing else "▶")
        self.status_var.set("播放中" if self.is_playing else "已暂停")

    def frame_step(self, delta):
        """逐帧进退"""
        if self.cap is None:
            return
        new_frame = self.current_frame + delta
        new_frame = max(0, min(new_frame, self.total_frames - 1))
        if new_frame == self.current_frame:
            return
        self.is_playing = False
        self.play_btn.configure(text="▶")
        self.current_frame = new_frame
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, new_frame)
        ret, frame = self.cap.read()
        if ret:
            self._show_frame(frame)
        self._update_progress_canvas()
        self._update_time()

    def seek_seconds(self, seconds):
        """快进/后退指定秒数"""
        if self.cap is None:
            return
        delta = int(seconds * self.fps)
        new_frame = max(0, min(self.current_frame + delta, self.total_frames - 1))
        if new_frame == self.current_frame:
            return
        self.is_playing = False
        self.play_btn.configure(text="▶")
        self.current_frame = new_frame
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, new_frame)
        ret, frame = self.cap.read()
        if ret:
            self._show_frame(frame)
        self._update_progress_canvas()
        self._update_time()

    def _seek_to_frame(self, frame_no):
        """跳转到指定帧并更新显示"""
        if self.cap is None:
            return
        frame_no = max(0, min(frame_no, self.total_frames - 1))
        self.current_frame = frame_no
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ret, frame = self.cap.read()
        if ret:
            self._show_frame(frame)
        self._update_progress_canvas()
        self._update_time()

    # ── 进度条拖拽 ────────────────────────────────────────────

    # ── 进度条绘制（Canvas 自绘） ──────────────────────────────

    def _update_progress_canvas(self, *_):
        """在 Canvas 上绘制轨道、已播进度、滑块、标记竖线"""
        c = self.progress_canvas
        c.delete('all')
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10 or self.total_frames < 2:
            return

        m = 8          # 左右边距
        ty = h // 2     # 轨道 y 坐标
        l, r = m, w - m
        max_frame = max(self.total_frames - 1, 1)

        ratio = self.current_frame / max_frame
        sx = l + int(ratio * (r - l))

        # 已选区高亮
        if self.mark_in_frame is not None and self.mark_out_frame is not None:
            if self.mark_in_frame < self.mark_out_frame:
                x1 = l + int((r - l) * self.mark_in_frame / max_frame)
                x2 = l + int((r - l) * self.mark_out_frame / max_frame)
                c.create_rectangle(x1, 0, x2, h, fill='#d4f0e0', outline='')

        # 轨道底色
        c.create_line(l, ty, r, ty, fill='#ccc', width=4, capstyle=tk.ROUND)

        # 已播放部分
        if sx > l:
            c.create_line(l, ty, sx, ty, fill='#4a90d9', width=4, capstyle=tk.ROUND)

        # 标记竖线
        if self.mark_in_frame is not None:
            x = l + int((r - l) * self.mark_in_frame / max_frame)
            c.create_line(x, 0, x, h, fill='#2ecc71', width=2)

        if self.mark_out_frame is not None:
            x = l + int((r - l) * self.mark_out_frame / max_frame)
            c.create_line(x, 0, x, h, fill='#e74c3c', width=2)

        # 滑块
        rad = 6
        c.create_oval(sx - rad, ty - rad, sx + rad, ty + rad,
                      fill='#4a90d9', outline='#3a7bc8', width=1)

    def _on_progress_press(self, event):
        """用户点击或拖拽进度条"""
        if self.cap is None:
            return
        self.is_seeking = True
        self.was_playing_before_seek = self.is_playing
        if self.is_playing:
            self.is_playing = False
        # 点击位置跳转
        self._seek_to_click(event)

    def _on_progress_release(self, event):
        """用户释放进度条"""
        if self.cap is None:
            return
        self.is_seeking = False
        if self.was_playing_before_seek:
            self.is_playing = True
            self.play_btn.configure(text="⏸")
            self.status_var.set("播放中")

    def _on_overlay_motion(self, event):
        """覆盖层拖拽移动"""
        if self.cap is None or not self.is_seeking:
            return
        self._seek_to_click(event)

    def _seek_to_click(self, event):
        """根据点击/拖拽位置计算对应帧并跳转"""
        try:
            widget_width = event.widget.winfo_width()
            if widget_width < 2:
                return
            ratio = max(0, min(event.x / widget_width, 1.0))
            frame_no = int(ratio * (self.total_frames - 1))
            self.current_frame = frame_no
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            ret, frame = self.cap.read()
            if ret:
                self._show_frame(frame)
            self._update_progress_canvas()
            self._update_time()
        except Exception:
            pass

    # ── 标记 ──────────────────────────────────────────────────

    def mark_in(self):
        if self.cap is None:
            return
        raw_t = self.current_frame / self.fps
        snapped = self._snap_keyframe(raw_t, 'backward')
        self.mark_in_time = snapped
        self.mark_in_frame = int(snapped * self.fps)
        self._seek_to_frame(self.mark_in_frame)
        self.mark_in_lbl.configure(text=f"起点: {self._fmt(snapped)}")
        self.status_var.set(f"标记起点: {self._fmt(snapped)} (帧 {self.mark_in_frame})")
        self._update_progress_canvas()
        self._show_cut_ready()

    def mark_out(self):
        if self.cap is None:
            return
        raw_t = self.current_frame / self.fps
        snapped = self._snap_keyframe(raw_t, 'forward')
        self.mark_out_time = snapped
        self.mark_out_frame = int(snapped * self.fps)
        self._seek_to_frame(self.mark_out_frame)
        self.mark_out_lbl.configure(text=f"终点: {self._fmt(snapped)}")
        self.status_var.set(f"标记终点: {self._fmt(snapped)} (帧 {self.mark_out_frame})")
        self._update_progress_canvas()
        self._show_cut_ready()

    def _show_cut_ready(self):
        if self.mark_in_frame is not None and self.mark_out_frame is not None:
            if self.mark_in_frame < self.mark_out_frame:
                self.status_var.set(f"✅ 已设范围，点击「✂ 裁剪」执行（{self.mark_in_frame}→{self.mark_out_frame}）")
            else:
                self.status_var.set(f"⚠ 起点（帧{self.mark_in_frame}）在终点之后")
        elif self.mark_in_frame is not None or self.mark_out_frame is not None:
            self.status_var.set("只设了单个标记，未设端将自动取视频头/尾")

    # ── 关键帧吸附 ──────────────────────────────────────────

    def _snap_keyframe(self, target_sec, direction):
        """在目标时间附近搜索最近关键帧，direction: 'backward' | 'forward'
        返回 snapped 后的时间（秒），搜索失败则返回原始值"""
        margin = 30.0  # 搜索窗口 ±30 秒
        if direction == 'backward':
            seek_start = max(0, target_sec - margin)
            search_dur = min(margin, target_sec) + 1
        else:
            seek_start = max(0, target_sec - 2)  # 略早开始，确保能搜到之后的
            search_dur = margin + 2

        try:
            cmd = [FFMPEG_PATH, "-y", "-ss", f"{seek_start:.3f}",
                   "-i", self.video_path, "-t", f"{search_dur:.3f}",
                   "-skip_frame", "nokey", "-vf", "showinfo", "-f", "null", "-"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW,
                                   universal_newlines=True, errors='replace')
            self._running_procs.append(proc)
            kfs = []
            for line in proc.stderr:
                if 'pts_time:' in line:
                    m = re.search(r'pts_time:([\d.]+)', line)
                    if m:
                        kfs.append(round(float(m.group(1)), 3))
            proc.wait()
            self._running_procs.remove(proc)

            # pts_time 相对于 seek 起点，绝对时间 = seek_start + pts_time
            abs_kfs = [seek_start + t for t in kfs]
            if not abs_kfs:
                return target_sec

            if direction == 'backward':
                candidates = [t for t in abs_kfs if t <= target_sec]
                return max(candidates) if candidates else abs_kfs[0]
            else:
                candidates = [t for t in abs_kfs if t >= target_sec]
                return min(candidates) if candidates else abs_kfs[-1]
        except Exception:
            return target_sec

    # ── 裁剪 ──────────────────────────────────────────────────

    def cut_video(self):
        """验证输入、弹出进度窗口、启动后台裁剪线程"""
        if not self.video_path:
            messagebox.showwarning("提示", "请先打开一个视频文件")
            return
        if self.mark_in_frame is not None and self.mark_out_frame is not None:
            if self.mark_in_frame >= self.mark_out_frame:
                messagebox.showerror("错误", "起点必须在终点之前")
                return

        self.is_playing = False
        self.play_btn.configure(text="▶")

        in_sec = self.mark_in_time if self.mark_in_time is not None else 0.0
        out_sec = self.mark_out_time if self.mark_out_time is not None else self.duration
        dur = out_sec - in_sec

        base, _ = os.path.splitext(self.video_path)
        out_path = f"{base}.clip.mp4"

        cmd = [FFMPEG_PATH, "-y", "-ss", f"{in_sec:.3f}", "-i", self.video_path,
               "-t", f"{dur:.3f}", "-c", "copy", "-map", "0", out_path]

        # ── 弹出进度窗口 ──
        pw = tk.Toplevel(self.root)
        pw.title("裁剪进度")
        w, h = 520, 300
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        pw.geometry(f"{w}x{h}+{x}+{y}")
        pw.resizable(False, False)
        pw.transient(self.root)
        pw.grab_set()
        pw.protocol("WM_DELETE_WINDOW", lambda: None)

        ttk.Label(pw, text=f"裁剪: {self._fmt(in_sec)} → {self._fmt(out_sec)}  ({dur:.1f}s)",
                  font=('', 10)).pack(pady=(12, 0))

        status_lbl = ttk.Label(pw, text="", font=('', 9))
        status_lbl.pack()

        bar_frame = ttk.Frame(pw)
        bar_frame.pack(pady=(2, 6), padx=12, fill=tk.X)

        pbar = ttk.Progressbar(bar_frame, mode='determinate', length=440)
        pbar.pack(side=tk.LEFT)

        pct_lbl = ttk.Label(bar_frame, text="0%", width=5, anchor=tk.E)
        pct_lbl.pack(side=tk.RIGHT)

        log_area = tk.Text(pw, height=10, wrap=tk.WORD, state=tk.DISABLED,
                           font=('Consolas', 9), bg='#1e1e1e', fg='#d4d4d4')
        log_area.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))

        scroll = ttk.Scrollbar(log_area, orient=tk.VERTICAL, command=log_area.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        log_area.configure(yscrollcommand=scroll.set)

        btn_frame = ttk.Frame(pw)
        btn_frame.pack(pady=(0, 8))
        btn_row = ttk.Frame(btn_frame)
        btn_row.pack()
        cancel_btn = ttk.Button(btn_row, text="中止", width=12)
        cancel_btn.pack(side=tk.LEFT)
        pw.update()

        # ── 主线程 UI 更新函数 ──
        _log_has_live = [False]  # 追踪最后一行是否为实时进度

        def ui_log(msg, color='#d4d4d4'):
            _log_has_live[0] = False
            log_area.configure(state=tk.NORMAL)
            log_area.insert(tk.END, msg + '\n', ('msg',))
            log_area.tag_configure('msg', foreground=color)
            log_area.see(tk.END)
            log_area.configure(state=tk.DISABLED)

        def ui_log_live(text):
            """更新日志最后一行为 ffmpeg 实时状态（原地替换）"""
            log_area.configure(state=tk.NORMAL)
            if _log_has_live[0]:
                log_area.delete('end-2l', 'end-1l')
            _log_has_live[0] = True
            log_area.insert(tk.END, '  > ' + text + '\n', ('live',))
            log_area.tag_configure('live', foreground='#888888')
            log_area.see(tk.END)
            log_area.configure(state=tk.DISABLED)

        def ui_status(text):
            status_lbl.configure(text=text)

        def ui_progress(val, msg=''):
            pbar['value'] = val
            pct_lbl.configure(text=f"{val}%")
            if msg:
                ui_log(msg)

        def ui_finish(size=None, cancelled=False, error=None):
            pbar['value'] = 100
            close_cmd = pw.destroy
            if error:
                ui_log(f"\n❌ 错误:\n{error}", '#f44747')
            elif cancelled:
                ui_log("\n⏹ 已中止", '#ffa500')
            else:
                ui_log(f"\n✅ 裁剪完成!", '#4ec9b0')
                ui_log(f"   输出: {os.path.basename(out_path)}")
                ui_log(f"   范围: {self._fmt(in_sec)} → {self._fmt(out_sec)}  ({dur:.1f}s)")
                ui_log(f"   时长: {self._fmt_dur(dur)}")
                ui_log(f"   大小: {self._fmt_size(size)}")
                self.status_var.set(f"裁剪完成: {os.path.basename(out_path)} ({size // 1024} KB)")
                ttk.Checkbutton(btn_row, text="删除源文件", variable=self.delete_source_var
                                ).pack(side=tk.LEFT, padx=(8, 0))
                def on_close():
                    path = self.video_path  # _close_video() 会清空 self.video_path，先保存
                    self._close_video()     # 释放 OpenCV/ffmpeg 句柄，否则删除会因占用失败
                    if self.delete_source_var.get():
                        if not self._send_to_recycle_bin(path):
                            pw.grab_release()  # grab 会拦截弹窗交互，先释放
                            messagebox.showerror("错误",
                                                 f"无法将源文件移入回收站:\n{path}\n\n文件可能被其他程序占用。",
                                                 parent=pw)
                            pw.grab_set()
                            return  # 保持窗口打开，用户可取消勾选后重试
                        self.status_var.set("源文件已移入回收站")
                    pw.destroy()
                close_cmd = on_close
            pw.grab_release()
            pw.protocol("WM_DELETE_WINDOW", pw.destroy)
            cancel_btn.configure(text="关闭", command=close_cmd)

        # ── 启动后台线程 ──
        self._cancel_requested = False

        def on_cancel():
            self._cancel_requested = True
            cancel_btn.configure(state=tk.DISABLED, text="正在中止...")

        cancel_btn.configure(command=on_cancel)

        t = threading.Thread(target=self._cut_worker, args=(
            cmd, dur, in_sec, out_sec, out_path,
            ui_log, ui_log_live, ui_status, ui_progress, ui_finish,
        ), daemon=True)
        t.start()

    def _cut_worker(self, cmd, dur, in_sec, out_sec, out_path,
                    ui_log, ui_log_live, ui_status, ui_progress, ui_finish):
        """后台线程：单条 ffmpeg -c copy 命令"""
        def schedule(fn, *args):
            self.root.after(0, fn, *args)

        def log(msg, color=None):
            schedule(ui_log, msg, color) if color else schedule(ui_log, msg)

        def log_live(text):
            schedule(ui_log_live, text)

        def status(text):
            schedule(ui_status, text)

        def progress(val, msg=''):
            schedule(ui_progress, val, msg)

        try:
            try:
                src_size = os.path.getsize(self.video_path)
                progress(0, f"源视频大小: {self._fmt_size(src_size)}")
                progress(0, f"源视频时长: {self._fmt_dur(self.duration)}")
            except Exception:
                pass
            progress(0, "开始流复制…")

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW,
                                   universal_newlines=True, errors='replace')
            self._running_procs.append(proc)
            err_tail = []
            try:
                for line in iter(proc.stderr.readline, ''):
                    if self._cancel_requested:
                        proc.kill()
                        proc.wait()
                        break
                    # ffmpeg 进度行 → 日志原地刷新
                    if line.startswith('frame=') or line.startswith('size='):
                        log_live(line.strip())
                    if 'time=' in line:
                        err_tail.append(line)
                        if len(err_tail) > 3:
                            err_tail.pop(0)
                        m = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line)
                        if m:
                            elapsed = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                            ratio = min(elapsed / dur, 0.99) if dur > 0 else 0
                            progress(int(ratio * 100))
                    elif line.strip():
                        err_tail.append(line)
                        if len(err_tail) > 80:
                            err_tail.pop(0)
                proc.wait()
            finally:
                self._running_procs.remove(proc)

            if self._cancel_requested:
                raise CancelError()
            if proc.returncode != 0:
                raise RuntimeError(''.join(err_tail[-20:])[-400:])

            size = os.path.getsize(out_path)
            schedule(ui_finish, size, False, None)

        except CancelError:
            schedule(ui_finish, None, True, None)
        except RuntimeError as e:
            schedule(ui_finish, None, False, str(e))
        except Exception as e:
            schedule(ui_finish, None, False, str(e))

    # ── 回收站 ──────────────────────────────────────────────

    def _send_to_recycle_bin(self, path):
        """将文件移入回收站，成功返回 True"""
        try:
            if not os.path.exists(path):
                return False

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", ctypes.wintypes.HWND),
                    ("wFunc", ctypes.c_uint),
                    ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p),
                    ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", ctypes.c_wchar_p),
                ]

            FO_DELETE = 3
            FOF_ALLOWUNDO = 0x40          # 删除进入回收站
            FOF_SILENT = 0x04             # 不显示进度对话框
            FOF_NOCONFIRMATION = 0x10     # 不弹确认框
            FOF_NOERRORUI = 0x0400        # 错误由本函数返回值体现

            fop = SHFILEOPSTRUCTW()
            fop.hwnd = None
            fop.wFunc = FO_DELETE
            # pFrom 必须双 null 结尾（ctypes 自动转为 UTF-16 缓冲并持有引用）
            fop.pFrom = path + '\0\0'
            fop.pTo = None
            fop.fFlags = FOF_ALLOWUNDO | FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI
            fop.fAnyOperationsAborted = 0
            fop.hNameMappings = None
            fop.lpszProgressTitle = None

            shell32 = ctypes.windll.shell32
            result = shell32.SHFileOperationW(ctypes.byref(fop))
            return result == 0
        except Exception:
            return False

    # ── 拖放支持（Windows Shell API） ────────────────────────

    def _enable_drag_drop(self):
        """注册窗口为 Windows 文件拖放目标"""
        try:
            hwnd = self.root.winfo_id()
            shell32 = ctypes.windll.shell32
            user32 = ctypes.windll.user32

            shell32.DragAcceptFiles(hwnd, True)

            # 声明参数类型，确保 64 位下指针传递正确
            user32.GetWindowLongPtrW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_void_p
            user32.SetWindowLongPtrW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.wintypes.HWND,
                                                ctypes.wintypes.UINT, ctypes.wintypes.WPARAM,
                                                ctypes.wintypes.LPARAM]
            user32.CallWindowProcW.restype = ctypes.c_void_p

            GWL_WNDPROC = -4
            WM_DROPFILES = 0x0233

            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_void_p,
                ctypes.wintypes.HWND,
                ctypes.wintypes.UINT,
                ctypes.wintypes.WPARAM,
                ctypes.wintypes.LPARAM,
            )

            orig_proc = user32.GetWindowLongPtrW(ctypes.wintypes.HWND(hwnd), GWL_WNDPROC)

            def proc(hwnd, msg, wparam, lparam):
                if msg == WM_DROPFILES:
                    buf = ctypes.create_unicode_buffer(260)
                    shell32.DragQueryFileW(ctypes.wintypes.WPARAM(wparam), 0, buf, 260)
                    if buf.value:
                        self.root.after(10, self._on_file_dropped, buf.value)
                    shell32.DragFinish(ctypes.wintypes.WPARAM(wparam))
                    return 0
                return user32.CallWindowProcW(orig_proc, hwnd, msg, wparam, lparam)

            proc_obj = WNDPROC(proc)
            user32.SetWindowLongPtrW(ctypes.wintypes.HWND(hwnd), GWL_WNDPROC,
                                     ctypes.cast(proc_obj, ctypes.c_void_p))
            self.root._drop_proc = proc_obj  # 防止被 GC
        except Exception as e:
            self.status_var.set(f"拖放支持加载失败: {e}")

    def _is_video_file(self, path):
        """通过文件头 magic bytes 识别视频文件（不依赖扩展名）"""
        try:
            with open(path, 'rb') as f:
                head = f.read(4096)
        except Exception:
            return False
        if not head:
            return False
        # MP4 / MOV / 3GP / M4V（ISO BMFF，偏移 4 处 "ftyp"）
        if len(head) >= 8 and head[4:8] == b'ftyp':
            return True
        # AVI: "RIFF" .... "AVI "
        if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'AVI ':
            return True
        # MKV / WebM（EBML 头）
        if head[:4] == b'\x1a\x45\xdf\xa3':
            return True
        # FLV
        if head[:3] == b'FLV':
            return True
        # WMV / ASF
        if head[:16] == b'\x30\x26\xb2\x75\x8e\x66\xcf\x11\xa6\xd9\x00\xaa\x00\x62\xce\x6c':
            return True
        # MPEG-TS：连续若干 188 字节包均以 0x47 同步字节开头
        if head[0] == 0x47:
            step = 188
            n = min(len(head) // step, 5)
            if n >= 2 and all(head[i * step] == 0x47 for i in range(1, n)):
                return True
        # M2TS（蓝光）：4 字节时间戳 + 188 字节 TS 包（192 字节/包）
        if len(head) >= 5 and head[4] == 0x47:
            step = 192
            n = min(len(head) // step, 5)
            if n >= 2 and all(head[i * step + 4] == 0x47 for i in range(1, n)):
                return True
        # MPEG-PS / VOB：00 00 01 BA
        if head[:4] == b'\x00\x00\x01\xba':
            return True
        # Ogg（含 .ogv/.ogg）
        if head[:4] == b'OggS':
            return True
        return False

    def _on_file_dropped(self, path):
        """处理拖入的文件（通过文件头识别，不依赖扩展名）"""
        if self._is_video_file(path):
            self._load_video(path)
        else:
            ext = os.path.splitext(path)[1].lower() or "(无扩展名)"
            self.status_var.set(f"不支持的文件格式: {ext}")

    def _load_video(self, path):
        """加载视频（与 open_video 共享逻辑）"""
        if self.cap:
            self.is_playing = False
            self.cap.release()

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            messagebox.showerror("错误", f"无法打开文件:\n{path}")
            return

        self.cap = cap
        self.video_path = path
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = cap.get(cv2.CAP_PROP_FPS)
        if self.fps < 1:
            self.fps = 30.0
        self.duration = self.total_frames / self.fps
        self.current_frame = 0
        self.mark_in_frame = None
        self.mark_out_frame = None

        self.progress_canvas.delete('all')
        self._update_progress_canvas()
        self.close_file_btn.pack(side=tk.LEFT, padx=2)
        self.play_btn.configure(state=tk.NORMAL, text="▶")
        self.step_back_btn.configure(state=tk.NORMAL)
        self.seek_back_btn.configure(state=tk.NORMAL)
        self.seek_fwd_btn.configure(state=tk.NORMAL)
        self.step_fwd_btn.configure(state=tk.NORMAL)
        self.mark_in_btn.configure(state=tk.NORMAL)
        self.mark_out_btn.configure(state=tk.NORMAL)
        self.mark_in_lbl.configure(text="起点: ─")
        self.mark_out_lbl.configure(text="终点: ─")
        self.status_var.set(f"已打开: {os.path.basename(path)}  ({self.total_frames} 帧, {self._fmt(self.duration)})")
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ret, frame = cap.read()
        if ret:
            self._show_frame(frame)
        self._update_time()
    # ── 轮询（主循环帧更新） ──────────────────────────────────

    def _poll(self):
        if not self.running:
            return

        if self.is_playing and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                self.current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                if self.current_frame < 0:
                    self.current_frame = 0
                self._show_frame(frame)
                if not self.is_seeking:
                    self._update_progress_canvas()
                self._update_time()

                if self.current_frame >= self.total_frames - 1:
                    self.is_playing = False
                    self.play_btn.configure(text="▶")
                    self.status_var.set("播放结束")

        delay = int(1000 / self.fps * 0.95) if self.is_playing else 100
        self.root.after(delay, self._poll)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    VideoCutter().run()
