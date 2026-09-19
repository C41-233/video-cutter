# 裁剪完成后「删除源文件」选项 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在裁剪成功窗口的关闭按钮右侧添加「删除源文件」复选框，勾选后点击关闭将源视频文件移入回收站。

**Architecture:** 单文件修改 `video_cutter.py`。新增实例方法 `_send_to_recycle_bin(path)` 用 ctypes 调用 Windows Shell API `SHFileOperationW`（FO_DELETE + FOF_ALLOWUNDO）实现移入回收站；`ui_finish` 成功路径在按钮行创建复选框，`on_close` 在释放文件句柄后按勾选状态决定是否删除。

**Tech Stack:** Python 3 + tkinter + ctypes（零新依赖）。

规格文档：`docs/superpowers/specs/2026-08-22-delete-source-recycle-bin-design.md`

---

### Task 1: 为 `_send_to_recycle_bin` 编写失败测试

**Files:**
- Create: `tests/test_recycle_bin.py`

- [ ] **Step 1: 创建测试文件**

```python
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from video_cutter import VideoCutter


class TestSendToRecycleBin(unittest.TestCase):
    def test_existing_file_moved_to_recycle_bin(self):
        fd, path = tempfile.mkstemp(suffix='.txt', prefix='avdb_cutter_test_')
        os.close(fd)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('test')
        self.assertTrue(os.path.exists(path))
        ok = VideoCutter._send_to_recycle_bin(None, path)
        self.assertTrue(ok)
        # 文件已从原路径移走（进入回收站；测试文件会残留在回收站，可手动清空）
        self.assertFalse(os.path.exists(path))

    def test_nonexistent_path_returns_false(self):
        missing = os.path.join(tempfile.gettempdir(), 'avdb_cutter_missing_file.txt')
        if os.path.exists(missing):
            os.remove(missing)
        self.assertFalse(VideoCutter._send_to_recycle_bin(None, missing))


if __name__ == '__main__':
    unittest.main()
```

说明：`VideoCutter._send_to_recycle_bin(None, path)` 是未绑定调用——方法体不依赖实例状态，`__init__` 会创建 Tk 窗口，测试中不能实例化。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "<仓库根目录>" && python tests/test_recycle_bin.py`
Expected: `AttributeError: type object 'VideoCutter' has no attribute '_send_to_recycle_bin'`（方法不存在）

### Task 2: 实现 `_send_to_recycle_bin` 并验证

**Files:**
- Modify: `video_cutter.py`（在 `_cut_worker` 方法之后、`_enable_drag_drop` 之前，新增方法）

- [ ] **Step 1: 实现方法**

```python
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

            # SHFileOperationW 要求 pFrom 指向双 null 结尾的路径字符串
            p_from = ctypes.create_unicode_buffer(path + '\0')
            fop = SHFILEOPSTRUCTW()
            fop.hwnd = None
            fop.wFunc = FO_DELETE
            fop.pFrom = p_from
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
```

- [ ] **Step 2: 运行测试确认通过**

Run: `cd "<仓库根目录>" && python tests/test_recycle_bin.py`
Expected: `Ran 2 tests ... OK`（第一个测试会把临时文件移入回收站）

- [ ] **Step 3: 提交**

```bash
git add video_cutter.py tests/test_recycle_bin.py
git commit -m "feat: 新增源文件移入回收站的 SHFileOperationW 封装"
```

### Task 3: GUI 改造——复选框与关闭流程

**Files:**
- Modify: `video_cutter.py:623-626`（btn_frame 改为水平按钮行）
- Modify: `video_cutter.py:660-680`（ui_finish 成功路径添加复选框、改造 on_close）

- [ ] **Step 1: btn_frame 改为水平按钮行**

将 `cut_video` 中的按钮行（约 623-626 行）：

```python
        btn_frame = ttk.Frame(pw)
        btn_frame.pack(pady=(0, 8))
        cancel_btn = ttk.Button(btn_frame, text="中止", width=12)
        cancel_btn.pack()
```

改为：

```python
        btn_frame = ttk.Frame(pw)
        btn_frame.pack(pady=(0, 8))
        btn_row = ttk.Frame(btn_frame)
        btn_row.pack()
        cancel_btn = ttk.Button(btn_row, text="中止", width=12)
        cancel_btn.pack(side=tk.LEFT)
```

- [ ] **Step 2: ui_finish 成功路径添加复选框并改造 on_close**

将成功路径末尾（约 673-677 行）：

```python
                self.status_var.set(f"裁剪完成: {os.path.basename(out_path)} ({size // 1024} KB)")
                def on_close():
                    self._close_video()
                    pw.destroy()
                close_cmd = on_close
```

改为：

```python
                self.status_var.set(f"裁剪完成: {os.path.basename(out_path)} ({size // 1024} KB)")
                del_var = tk.BooleanVar(value=False)
                ttk.Checkbutton(btn_row, text="删除源文件", variable=del_var
                                ).pack(side=tk.LEFT, padx=(8, 0))
                def on_close():
                    path = self.video_path  # _close_video() 会清空 self.video_path，先保存
                    self._close_video()     # 释放 OpenCV/ffmpeg 句柄，否则删除会因占用失败
                    if del_var.get():
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
```

- [ ] **Step 3: 语法检查**

Run: `cd "<仓库根目录>" && python -m py_compile video_cutter.py && python tests/test_recycle_bin.py`
Expected: 无输出错误，`Ran 2 tests ... OK`（回归确认）

- [ ] **Step 4: 手动验证 GUI 全流程**

1. 生成测试视频：`ffmpeg -y -f lavfi -i testsrc=duration=30:size=320x240:rate=30 -f lavfi -i sine=frequency=440:duration=30 -c:v libx264 -g 30 -c:a aac "%TEMP%\avdb_cut_test.mp4"`
2. 启动：`cd "<仓库根目录>" && python video_cutter.py`（或双击 启动视频切割器.bat），打开测试视频
3. 标记起点（Z）→ 标记终点（X）→ 点「✂ 裁剪」→ 等待成功
4. **断言 A**：成功窗口底部按钮右侧出现「删除源文件」复选框，默认未勾选
5. 不勾选 → 点「关闭」→ 窗口关闭，`%TEMP%\avdb_cut_test.mp4` 仍存在
6. 再次裁剪 → 勾选「删除源文件」→ 点「关闭」→ 源文件从原路径消失，回收站中出现
7. **断言 B**（失败场景）：再生成一次测试视频并裁剪成功，点击关闭前用记事本打开源文件占用它 → 勾选 → 点「关闭」→ 弹出错误提示且窗口不关闭 → 关闭记事本 → 取消勾选 → 点「关闭」→ 窗口正常关闭
8. 清理：删除 `%TEMP%\avdb_cut_test.mp4*`（裁剪输出与源文件；已进回收站的测试文件可手动清空回收站）

- [ ] **Step 5: 提交**

```bash
git add video_cutter.py
git commit -m "feat: 裁剪成功后可勾选将源文件移入回收站"
```

---

## 自审记录

- **规格覆盖**：仅成功显示 ✓（Task 3 Step 2，del_var 只在成功路径创建）、默认不勾选 ✓（value=False）、先释放句柄 ✓（on_close 先 _close_video）、失败保持窗口 ✓（grab_release → showerror → grab_set → return）、零依赖 ✓（ctypes）、SHFileOperationW ✓（Task 2）。
- **占位符**：无。
- **命名一致性**：`_send_to_recycle_bin`、`del_var`、`on_close`、`btn_row` 在各任务中一致。
