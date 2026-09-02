import time
import unittest

import numpy as np

from software.api.checkerboard_detector import find_checkerboard_bounded


class _BaseCV:
    COLOR_BGR2GRAY = 1
    INTER_AREA = 2
    CC_STAT_LEFT = 0
    CC_STAT_TOP = 1
    CC_STAT_WIDTH = 2
    CC_STAT_HEIGHT = 3
    CC_STAT_AREA = 4
    MORPH_ELLIPSE = 2
    INPAINT_TELEA = 1

    @staticmethod
    def cvtColor(image, _mode):
        return image[:, :, 0]

    @staticmethod
    def findChessboardCorners(_gray, _pattern, _flags=0):
        return False, None


class _ScaleCV(_BaseCV):
    def __init__(self):
        self.sb_calls = 0

    @staticmethod
    def resize(_image, size, interpolation):
        assert interpolation == _ScaleCV.INTER_AREA
        return np.zeros((size[1], size[0], 3), dtype=np.uint8)

    def findChessboardCornersSB(self, _gray, pattern, _flags=0):
        self.sb_calls += 1
        corners = np.tile(
            np.array([[[100.0, 200.0]]], dtype=np.float32),
            (pattern[0] * pattern[1], 1, 1),
        )
        return True, corners


class _ClassicCV(_BaseCV):
    @staticmethod
    def findChessboardCorners(_gray, pattern, _flags=0):
        corners = np.tile(
            np.array([[[20.0, 30.0]]], dtype=np.float32),
            (pattern[0] * pattern[1], 1, 1),
        )
        return True, corners

    @staticmethod
    def findChessboardCornersSB(*_args):
        raise AssertionError("SB must not run after classic detection succeeds")


class _GlareCV(_BaseCV):
    @staticmethod
    def connectedComponentsWithStats(candidate, _connectivity):
        labels = np.zeros(candidate.shape, dtype=np.int32)
        rows, columns = np.nonzero(candidate)
        labels[rows, columns] = 1
        left, top = int(columns.min()), int(rows.min())
        width, height = int(np.ptp(columns)) + 1, int(np.ptp(rows)) + 1
        area = len(rows)
        stats = np.array(
            [[0, 0, 100, 100, 10000 - area], [left, top, width, height, area]],
            dtype=np.int32,
        )
        return 2, labels, stats, np.array([[50, 50], [columns.mean(), rows.mean()]])

    @staticmethod
    def getStructuringElement(_shape, size):
        return np.ones(size, dtype=np.uint8)

    @staticmethod
    def dilate(mask, _kernel, iterations=1):
        assert iterations == 1
        return mask

    @staticmethod
    def inpaint(image, mask, _radius, _method):
        assert 4 <= np.count_nonzero(mask) <= 25
        corrected = image.copy()
        corrected[:] = 99
        return corrected

    @staticmethod
    def findChessboardCornersSB(gray, pattern, _flags=0):
        if int(gray[0, 0]) != 99:
            return False, None
        corners = np.tile(
            np.array([[[30.0, 40.0]]], dtype=np.float32),
            (pattern[0] * pattern[1], 1, 1),
        )
        return True, corners


class _SlowCV(_BaseCV):
    @staticmethod
    def findChessboardCornersSB(_gray, _pattern, _flags=0):
        time.sleep(0.5)
        return False, None


class _CornerOccludedCV(_GlareCV):
    @staticmethod
    def findChessboardCornersSB(gray, pattern, _flags=0):
        if int(gray[0, 0]) != 99:
            return False, None
        corners = np.tile(
            np.array([[[46.0, 46.0]]], dtype=np.float32),
            (pattern[0] * pattern[1], 1, 1),
        )
        return True, corners


class CheckerboardDetectorTests(unittest.TestCase):
    def test_exact_pattern_classic_success_skips_sb_and_glare_processing(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        result = find_checkerboard_bounded(
            _ClassicCV(), image, ((10, 6),), timeout_s=0.5
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["pattern"], (10, 6))
        self.assertEqual(result["method"], "classic")
        self.assertFalse(result["glare_masked"])

    def test_sb_fallback_returns_full_resolution_coordinates_after_scaling(self):
        image = np.zeros((1920, 2560, 3), dtype=np.uint8)
        cv = _ScaleCV()
        result = find_checkerboard_bounded(
            cv, image, ((10, 6),), max_width=1280, timeout_s=0.5
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["method"], "sb")
        self.assertEqual(cv.sb_calls, 1)
        np.testing.assert_allclose(result["corners"][0, 0], [200, 400])

    def test_partial_bright_ir_spot_is_narrowly_inpainted_before_sb_retry(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        image[45:49, 45:49] = [255, 40, 250]
        result = find_checkerboard_bounded(
            _GlareCV(), image, ((10, 6),), max_width=1280, timeout_s=0.5
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["method"], "sb")
        self.assertTrue(result["glare_masked"])
        np.testing.assert_allclose(result["corners"][0, 0], [30, 40])

    def test_inpainted_result_is_rejected_if_glare_overlaps_a_corner(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        image[45:49, 45:49] = [255, 40, 250]
        result = find_checkerboard_bounded(
            _CornerOccludedCV(), image, ((10, 6),), timeout_s=0.5
        )
        self.assertFalse(result["found"])
        self.assertIn("overlaps", result["error"])

    def test_broad_saturated_region_is_not_inpainted(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        image[10:90, 10:90] = [255, 40, 250]
        result = find_checkerboard_bounded(
            _GlareCV(), image, ((10, 6),), max_width=1280, timeout_s=0.5
        )
        self.assertFalse(result["found"])
        self.assertFalse(result.get("glare_masked", False))

    def test_slow_sb_call_returns_at_configured_deadline(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        started = time.monotonic()
        result = find_checkerboard_bounded(
            _SlowCV(), image, ((10, 6),), timeout_s=0.03
        )
        self.assertTrue(result["timed_out"])
        self.assertLess(time.monotonic() - started, 0.2)


if __name__ == "__main__":
    unittest.main()
