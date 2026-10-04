# -*- coding: utf-8 -*-
"""验证 _is_video_file 对 RM/RMVB 及既有格式的识别"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from video_cutter import VideoCutter

check = VideoCutter._is_video_file

RMF = b'.RMF' + b'\x00' * 44 + b'\x00' * 4000
cases = [
    ("rmvb 头", RMF, True),
    ("mp4 头", b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 4000, True),
    ("avi 头", b'RIFF\x00\x00\x00\x00AVI ' + b'\x00' * 4000, True),
    ("mkv 头", b'\x1a\x45\xdf\xa3' + b'\x00' * 4000, True),
    ("ts 包流", bytes(0x47 if i % 188 == 0 else 0 for i in range(4096)), True),
    ("纯文本", b'hello world, not a video at all' * 128, False),
    ("空文件", b'', False),
]

tmpdir = tempfile.mkdtemp()
ok = True
for name, data, expected in cases:
    path = os.path.join(tmpdir, "sample.bin")
    with open(path, 'wb') as f:
        f.write(data)
    got = check(None, path)
    status = "PASS" if got == expected else "FAIL"
    if got != expected:
        ok = False
    print(f"[{status}] {name}: expect={expected} got={got}")

# 无扩展名的 RMF 文件也应被识别（体现「不依赖扩展名」）
path = os.path.join(tmpdir, "noext")
with open(path, 'wb') as f:
    f.write(RMF)
got = check(None, path)
print(f"[{'PASS' if got else 'FAIL'}] 无扩展名 rmvb: expect=True got={got}")
ok = ok and got

for p in (os.path.join(tmpdir, "sample.bin"), os.path.join(tmpdir, "noext")):
    os.remove(p)
os.rmdir(tmpdir)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
