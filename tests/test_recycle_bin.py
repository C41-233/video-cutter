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
