# 设计：裁剪成功后「删除源文件」选项

日期：2026-08-22
状态：已获用户批准（2026-08-22）

## 需求

裁剪完成窗口（`ui_finish` 成功路径）的「关闭」按钮右侧新增一个复选框「删除源文件」。用户勾选后点击「关闭」，源视频文件被移入回收站（非永久删除）。

## 约束

- 复选框**仅裁剪成功时显示**；失败/中止路径不显示（避免误删源文件）。
- 默认**不勾选**。
- 放入回收站失败时（文件被占用、权限不足等）：弹错误提示，**窗口保持打开**，用户可取消勾选后重新点击关闭。
- 不引入新的第三方依赖（项目为便携式脚本，用 bat 启动）。

## UI 布局

- 位置：进度窗口底部按钮行 `btn_frame`（`cut_video()` 内，video_cutter.py:623-626），关闭按钮右侧。
- 控件：`ttk.Checkbutton`，文本「删除源文件」，默认 `False`。
- 勾选变量在 `ui_finish` 成功路径创建（`tk.BooleanVar(value=False)`），失败/中止路径不创建。

## 行为流程（点击「关闭」时）

`on_close`（成功路径的 `close_cmd`，video_cutter.py:674-677）改造：

1. 保存 `self.video_path` 到局部变量。
2. 调用 `self._close_video()` —— 必须**先释放** OpenCV/ffmpeg 持有的文件句柄，否则删除会因文件被占用而失败。
3. 若勾选了复选框：
   - 调用 `self._send_to_recycle_bin(保存的路径)`。
   - 返回 True → 销毁窗口，主窗口状态栏设「源文件已移入回收站」。
   - 返回 False → `messagebox.showerror` 提示错误，**不销毁窗口**（保持打开）。注意：此时主窗口视频已复位（`_close_video()` 已执行），再次点击关闭会重入 `on_close`（`_close_video()` 幂等）并正常销毁窗口。
4. 未勾选 → 原逻辑不变（`_close_video()` 后 `pw.destroy()`）。

注意：`_close_video()` 会把 `self.video_path` 置为 `None`，所以必须在调用前保存路径。

## 回收站实现

`_send_to_recycle_bin(path) -> bool`：用 ctypes 调用 Windows Shell API `SHFileOperationW`。

- 结构体 `SHFILEOPSTRUCTW`（ctypes.Structure）：
  - `hwnd`: HWND
  - `wFunc`: UINT（`FO_DELETE = 3`）
  - `pFrom`: c_wchar_p（**双 null 结尾**，用 `ctypes.create_unicode_buffer(path + '\0')`）
  - `pTo`: c_wchar_p（None）
  - `fFlags`: c_ushort（WORD，`FOF_ALLOWUNDO = 0x40 | FOF_SILENT = 0x04 | FOF_NOCONFIRMATION = 0x10 | FOF_NOERRORUI = 0x0400`）
  - `fAnyOperationsAborted`: c_int
  - `hNameMappings`: c_void_p
  - `lpszProgressTitle`: c_wchar_p
- `FOF_ALLOWUNDO` 使删除进入回收站；`FOF_SILENT/FOF_NOCONFIRMATION/FOF_NOERRORUI` 避免系统弹窗干扰 UI 线程。
- 函数返回 `shell32.SHFileOperationW(byref(fop)) == 0`；任何异常返回 False。

与项目现有 ctypes 用法一致（拖放部分，video_cutter.py:772-819）。

## 错误处理

- SHFileOperationW 返回非 0 → 失败 → `messagebox.showerror`，窗口保持打开。
- 删除成功后窗口销毁，无法回滚（与需求一致：进回收站，可手动还原）。

## 测试

- 单元级：生成测试视频 → 调用 `_send_to_recycle_bin` 验证回收站出现文件、返回值 True；对不存在路径验证返回 False。
- 手动：GUI 中裁剪 → 勾选 → 关闭 → 源文件消失且回收站中出现；不勾选时行为不变。
- 失败场景：将源文件设为只读/占用后手动验证弹窗且窗口不关闭。
