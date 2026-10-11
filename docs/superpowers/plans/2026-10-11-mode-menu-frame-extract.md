# 功能切换菜单 ＋ 逐帧截图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 主按钮变分体按钮（＋▾ 菜单切「裁剪/逐帧截图」两种模式），截图按标记范围（双端包含、吸附后帧号）逐帧导出 PNG/JPG 到视频同目录。

**Architecture:** 单文件 `video_cutter.py` 内扩展：纯函数（范围解析/命令构造）静态方法化以便 unittest；UI 在 `setup_ui` 的 `cut_row` 改复合 frame；截图流程仿照 `cut_video` 的「模态进度窗＋后台线程＋stderr 解析」模式简化实现。

**Tech Stack:** tkinter、subprocess（ffmpeg image2）、unittest。

**仓库约定：** 索引 LF 无 BOM（`core.autocrlf=false`），每轮编辑后须字节级归一化；**代码改动不做中间提交**——沿用本仓库惯例，待用户手动实测通过后由用户提交（设计/计划文档除外）。

**Spec:** `docs/superpowers/specs/2026-10-11-mode-menu-frame-extract-design.md`

---

### Task 1: 纯函数——范围解析与命令构造（TDD）

**Files:**
- Create: `tests/test_extract_frames.py`
- Modify: `video_cutter.py`（`VideoCutter` 类内新增两个静态方法）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_extract_frames.py`（完整内容）：

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from video_cutter import VideoCutter


class TestResolveFrameRange(unittest.TestCase):
    def test_no_marks_full_video(self):
        self.assertEqual(VideoCutter._resolve_frame_range(None, None, 2700), (0, 2699))

    def test_in_only_defaults_out_to_last(self):
        self.assertEqual(VideoCutter._resolve_frame_range(100, None, 2700), (100, 2699))

    def test_out_only_defaults_in_to_zero(self):
        self.assertEqual(VideoCutter._resolve_frame_range(None, 500, 2700), (0, 500))

    def test_both_ends_inclusive(self):
        self.assertEqual(VideoCutter._resolve_frame_range(4820, 5400, 10000), (4820, 5400))

    def test_equal_marks_valid_single_frame(self):
        self.assertEqual(VideoCutter._resolve_frame_range(4820, 4820, 10000), (4820, 4820))

    def test_out_before_in_invalid(self):
        self.assertIsNone(VideoCutter._resolve_frame_range(5400, 4820, 10000))


class TestBuildExtractCmd(unittest.TestCase):
    def test_png_command(self):
        cmd, count, pattern = VideoCutter._build_extract_cmd(
            "ffmpeg.exe", r"D:\a\EP01.mkv", 4820, 5400, 30.0, 27000)
        self.assertEqual(count, 581)
        # 总帧 27000 → 末帧 26999 共 5 位 → %05d
        self.assertEqual(pattern, r"D:\a\EP01_%05d.png")
        self.assertIn("-y", cmd)
        self.assertEqual(cmd[cmd.index("-frames:v") + 1], "581")
        self.assertEqual(cmd[cmd.index("-start_number") + 1], "4820")
        self.assertNotIn("-q:v", cmd)
        self.assertEqual(cmd[-1], pattern)

    def test_jpg_command_quality(self):
        cmd, count, pattern = VideoCutter._build_extract_cmd(
            "ffmpeg.exe", r"D:\a\EP01.mkv", 0, 99, 30.0, 27000, ext='jpg')
        self.assertEqual(pattern, r"D:\a\EP01_%05d.jpg")
        self.assertEqual(cmd[cmd.index("-q:v") + 1], "2")

    def test_width_from_total_frames(self):
        _, _, pattern = VideoCutter._build_extract_cmd(
            "ffmpeg.exe", "v.mkv", 0, 9, 30.0, 2700)
        self.assertEqual(pattern, "v_%04d.png")

    def test_width_fallback_when_total_unknown(self):
        _, _, pattern = VideoCutter._build_extract_cmd(
            "ffmpeg.exe", "v.mkv", 0, 9, 30.0, 1)
        self.assertEqual(pattern, "v_%06d.png")


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_extract_frames -v`
Expected: FAIL / ERROR——`AttributeError: type object 'VideoCutter' has no attribute '_resolve_frame_range'`

- [ ] **Step 3: 实现两个静态方法**

在 `video_cutter.py` 的 `# ── 回收站 ──` 小节之前插入（完整代码）：

```python
    # ── 逐帧截图（纯函数） ────────────────────────────────────

    @staticmethod
    def _resolve_frame_range(mark_in_frame, mark_out_frame, total_frames):
        """解析截图帧范围（双端包含）。未标记的端默认取视频首/末帧；
        终点帧在起点帧之前返回 None，两端相等合法（单帧）"""
        in_f = mark_in_frame if mark_in_frame is not None else 0
        out_f = mark_out_frame if mark_out_frame is not None else total_frames - 1
        if out_f < in_f:
            return None
        return in_f, out_f

    @staticmethod
    def _build_extract_cmd(ffmpeg_path, video_path, in_frame, out_frame,
                           fps, total_frames, ext='png'):
        """构造逐帧截图 ffmpeg 命令，返回 (cmd, count, pattern)
        文件名编号＝帧号，位宽＝总帧数的位数（全序列等长）"""
        count = out_frame - in_frame + 1
        width = len(str(total_frames - 1)) if total_frames >= 2 else 6
        in_sec = in_frame / fps
        base, _ = os.path.splitext(video_path)
        pattern = f"{base}_%0{width}d.{ext}"
        cmd = [ffmpeg_path, "-y", "-ss", f"{in_sec:.6f}", "-i", video_path,
               "-frames:v", str(count), "-start_number", str(in_frame)]
        if ext.lower() in ('jpg', 'jpeg'):
            cmd += ["-q:v", "2"]
        cmd.append(pattern)
        return cmd, count, pattern
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_extract_frames -v`
Expected: 10 tests PASS

### Task 2: UI——分体按钮＋模式菜单＋格式 radio

**Files:**
- Modify: `video_cutter.py`（`setup_ui` 的裁剪按钮行，及其后新增两个方法）

- [ ] **Step 1: 替换 cut_row 搭建代码**

`setup_ui` 中原「裁剪按钮行」整块替换为（完整代码）：

```python
        # 主操作按钮行（分体按钮：主按钮 + ▾ 模式菜单）
        cut_row = ttk.Frame(self.root)
        cut_row.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0, 4))

        self.action_mode = 'cut'
        self.mode_var = tk.StringVar(value='cut')
        self.fmt_var = tk.StringVar(value='png')

        action_area = ttk.Frame(cut_row)
        action_area.pack()
        btn_group = ttk.Frame(action_area)
        btn_group.pack()
        self.cut_btn = tk.Button(btn_group, text="✂ 裁剪", command=self.cut_video,
                                 width=20, font=('', 10),
                                 relief=tk.RAISED, bd=1, cursor='hand2', takefocus=False)
        self.cut_btn.pack(side=tk.LEFT)
        self.mode_arrow_btn = tk.Button(btn_group, text="▾", width=2, font=('', 10),
                                        relief=tk.RAISED, bd=1, cursor='hand2',
                                        takefocus=False, command=self._show_mode_menu)
        self.mode_arrow_btn.pack(side=tk.LEFT)

        # 截图格式选择行（仅截图模式显示）
        self.fmt_row = ttk.Frame(action_area)
        ttk.Radiobutton(self.fmt_row, text="PNG", variable=self.fmt_var,
                        value='png', takefocus=False).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(self.fmt_row, text="JPG（质量 95）", variable=self.fmt_var,
                        value='jpg', takefocus=False).pack(side=tk.LEFT, padx=2)

        # 模式切换菜单
        self.mode_menu = tk.Menu(self.root, tearoff=0)
        self.mode_menu.add_radiobutton(label="✂ 裁剪", variable=self.mode_var,
                                       value='cut', command=lambda: self._switch_mode('cut'))
        self.mode_menu.add_radiobutton(label="📷 逐帧截图", variable=self.mode_var,
                                       value='frames', command=lambda: self._switch_mode('frames'))
```

- [ ] **Step 2: 新增 `_show_mode_menu` / `_switch_mode` 方法**

放在 `# ── 裁剪 ──` 小节标题之前（完整代码）：

```python
    def _show_mode_menu(self):
        """在 ▾ 箭头下方弹出模式菜单"""
        x = self.mode_arrow_btn.winfo_rootx()
        y = self.mode_arrow_btn.winfo_rooty() + self.mode_arrow_btn.winfo_height()
        try:
            self.mode_menu.tk_popup(x, y)
        finally:
            self.mode_menu.grab_release()

    def _switch_mode(self, mode):
        """切换主按钮功能：'cut' 裁剪 / 'frames' 逐帧截图"""
        self.action_mode = mode
        if mode == 'cut':
            self.cut_btn.configure(text="✂ 裁剪", command=self.cut_video)
            self.fmt_row.pack_forget()
        else:
            self.cut_btn.configure(text="📷 逐帧截图", command=self.extract_frames)
            self.fmt_row.pack()
```

- [ ] **Step 3: 烟雾验证 UI 可构建**

Run: `python -c "import video_cutter as v; app = v.VideoCutter(); app.root.after(1200, app.root.destroy); app.run(); print('SMOKE OK')"`
Expected: 窗口正常出现后自动退出，打印 `SMOKE OK`，无 traceback。

### Task 3: 截图流程——入口、进度窗、后台线程

**Files:**
- Modify: `video_cutter.py`（`# ── 裁剪 ──` 小节之后、`# ── 回收站 ──` 小节之前新增）

- [ ] **Step 1: 新增 `extract_frames` 与 `_extract_worker`**

（完整代码；`_show_cut_ready` 不改动，截图入口自行校验）

```python
    # ── 逐帧截图 ──────────────────────────────────────────────

    def extract_frames(self):
        """验证输入并启动逐帧截图：解析范围 → 模态进度窗 → 后台线程"""
        if not self.video_path:
            messagebox.showwarning("提示", "请先打开一个视频文件")
            return
        rng = self._resolve_frame_range(self.mark_in_frame, self.mark_out_frame,
                                        self.total_frames)
        if rng is None:
            messagebox.showerror("错误", "起点必须在终点之前")
            return
        in_frame, out_frame = rng

        # 位宽依据的总帧数：OpenCV 读不到时按时长×fps 估算
        total_for_width = self.total_frames
        if total_for_width < 2:
            total_for_width = int(self.duration * self.fps) + 1

        ext = self.fmt_var.get()
        cmd, count, pattern = self._build_extract_cmd(
            FFMPEG_PATH, self.video_path, in_frame, out_frame,
            self.fps, total_for_width, ext=ext)

        if self.is_playing:
            self.is_playing = False
            self.play_btn.configure(text="▶")

        in_sec = in_frame / self.fps
        out_sec = (out_frame + 1) / self.fps
        out_dir = os.path.dirname(self.video_path)

        # ── 弹出简化进度窗 ──
        pw = tk.Toplevel(self.root)
        pw.title("截图进度")
        w, h = 460, 160
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        pw.geometry(f"{w}x{h}+{x}+{y}")
        pw.resizable(False, False)
        pw.transient(self.root)
        pw.grab_set()
        pw.protocol("WM_DELETE_WINDOW", lambda: None)

        ttk.Label(pw, text=f"{self._fmt(in_sec)} → {self._fmt(out_sec)} · {count} 张",
                  font=('', 10)).pack(pady=(12, 4))

        bar_frame = ttk.Frame(pw)
        bar_frame.pack(fill=tk.X, padx=12)
        pbar = ttk.Progressbar(bar_frame, mode='determinate', length=400)
        pbar.pack(side=tk.LEFT)
        pct_lbl = ttk.Label(bar_frame, text="0%", width=5, anchor=tk.E)
        pct_lbl.pack(side=tk.RIGHT)

        live_lbl = ttk.Label(pw, text="", font=('', 9))
        live_lbl.pack(pady=(4, 2))

        btn_row = ttk.Frame(pw)
        btn_row.pack(pady=(2, 8))
        cancel_btn = ttk.Button(btn_row, text="中止", width=12)
        cancel_btn.pack()
        pw.update()

        def ui_progress(done):
            pct = min(done * 100 / count, 100.0) if count > 0 else 100.0
            pbar['value'] = pct
            pct_lbl.configure(text=f"{int(pct)}%")
            if done > 0:
                name = os.path.basename(pattern % (in_frame + done - 1))
                live_lbl.configure(text=f"已输出 {done}/{count} 张（{name}）",
                                   foreground='#666666')

        def ui_finish(done=None, cancelled=False, error=None):
            if error:
                live_lbl.configure(text="❌ 截图失败", foreground='#f44747')
                messagebox.showerror("截图失败", error, parent=pw)
            elif cancelled:
                live_lbl.configure(text=f"⏹ 已中止，保留已输出 {done} 张",
                                   foreground='#ffa500')
            else:
                live_lbl.configure(text=f"✅ 完成：{done} 张 → {out_dir}",
                                   foreground='#2e8b57')
                self.status_var.set(f"截图完成: {done} 张 → {out_dir}")
            pw.grab_release()
            pw.protocol("WM_DELETE_WINDOW", pw.destroy)
            cancel_btn.configure(state=tk.NORMAL, text="关闭", command=pw.destroy)

        self._cancel_requested = False

        def on_cancel():
            self._cancel_requested = True
            cancel_btn.configure(state=tk.DISABLED, text="正在中止...")

        cancel_btn.configure(command=on_cancel)

        t = threading.Thread(target=self._extract_worker, args=(
            cmd, count, ui_progress, ui_finish), daemon=True)
        t.start()

    def _extract_worker(self, cmd, count, ui_progress, ui_finish):
        """后台线程：ffmpeg image2 逐帧截图，stderr frame= 行驱动进度"""
        def schedule(fn, *args):
            self.root.after(0, fn, *args)

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=subprocess.CREATE_NO_WINDOW,
                                    universal_newlines=True, errors='replace')
            self._running_procs.append(proc)
            err_tail = []
            last_done = 0
            try:
                for line in iter(proc.stderr.readline, ''):
                    if self._cancel_requested:
                        proc.kill()
                        proc.wait()
                        break
                    if line.startswith('frame='):
                        m = re.search(r'frame=\s*(\d+)', line)
                        if m:
                            last_done = int(m.group(1))
                            schedule(ui_progress, last_done)
                    elif line.strip():
                        err_tail.append(line)
                        if len(err_tail) > 80:
                            err_tail.pop(0)
                proc.wait()
            finally:
                self._running_procs.remove(proc)

            if self._cancel_requested:
                schedule(ui_finish, last_done, True, None)
            elif proc.returncode != 0:
                schedule(ui_finish, None, False, ''.join(err_tail[-20:])[-400:])
            else:
                schedule(ui_finish, last_done, False, None)
        except Exception as e:
            schedule(ui_finish, None, False, str(e))
```

- [ ] **Step 2: 烟雾验证（含新方法绑定）**

Run: `python -c "import video_cutter as v; app = v.VideoCutter(); app._switch_mode('frames'); app._switch_mode('cut'); app.root.after(1200, app.root.destroy); app.run(); print('SMOKE OK')"`
Expected: `SMOKE OK`，无 traceback（模式切换不报错即命令/控件绑定完整）。

### Task 4: 全量验证与收尾

**Files:**
- 无新改动；验证 + 归一化。

- [ ] **Step 1: 全量测试**

Run: `python -m unittest discover -s tests -v`
Expected: 全部 PASS（含既有 test_format_detect_rmvb、test_recycle_bin）。

- [ ] **Step 2: 编码归一化与 diff 收敛检查**

Run（Python 字节级归一化 `video_cutter.py` 与 `tests/test_extract_frames.py`：去 BOM、CRLF→LF）后 `git diff --stat`。
Expected: diff 仅覆盖本次改动行（约 +170 行），无全文件重写。

- [ ] **Step 3: 手动清单交用户实测**

模式切换与 radio 显隐、首末帧张数核对、同范围重跑覆盖、中止保留已生成、整片默认、RM 源截图、长/短视频位宽、未打开视频点击提示。实测通过后由用户提交代码。
