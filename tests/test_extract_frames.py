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
