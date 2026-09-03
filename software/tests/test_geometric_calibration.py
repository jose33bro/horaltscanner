import copy
from contextlib import contextmanager
import json
import math
import os
import shutil
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - optional in non-vision test environments
    cv2 = None

from software.api.geometric_calibration import (
    AtomicCalibrationStore,
    CalibrationCancelled,
    CalibrationError,
    CheckerboardDetectionRejected,
    CheckerboardDetectionTimeout,
    GeometricCalibrationService,
    BOARD_TO_SCANNER_AT_REFERENCE,
    PNP_BOARD_FRAME_ADJUSTMENTS,
    checkerboard_view_metrics,
    checkerboard_points,
    extract_laser_line_pixels,
    fit_plane_robust,
    transform_from_beam,
    validate_calibration_payload,
    validate_view_diversity,
)


ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / ".test-geometric-calibration"


def valid_calibration():
    camera = {
        "intrinsic_matrix": [[800, 0, 320], [0, 800, 240], [0, 0, 1]],
        "distortion_coefficients": [0, 0, 0, 0, 0],
        "camera_to_scanner": np.eye(4).tolist(),
        "quality": {
            "accepted": True,
            "rms_px": 0.2,
            "maximum_rms_px": 1.0,
            "extrinsic_translation_rms_mm": 0.3,
            "maximum_extrinsic_rms_mm": 5.0,
            "extrinsic_rotation_rms_deg": 0.2,
            "maximum_extrinsic_rms_deg": 3.0,
        },
    }
    plane = {
        "normal": [1, 0, 0],
        "offset_mm": -20,
        "source": "pi_checkerboard_structured_light",
        "quality": {
            "accepted": True,
            "rms_mm": 0.2,
            "maximum_rms_mm": 2.0,
            "primary_camera": "pi",
            "views": 3,
            "minimum_views": 3,
            "independent_board_orientations": 3,
            "minimum_board_orientations": 3,
            "plane_spread_ratio": 0.5,
            "minimum_plane_spread_ratio": 0.001,
            "minimum_points_per_view": 10,
            "inlier_points_per_pose": [
                {"pose_index": 0, "points": 10},
                {"pose_index": 1, "points": 10},
                {"pose_index": 2, "points": 10},
            ],
        },
    }
    return {
        "checkerboard": {
            "board_columns": 11,
            "board_rows": 6,
            "square_size_mm": 13,
        },
        "cameras": {"pi": copy.deepcopy(camera), "usb": copy.deepcopy(camera)},
        "laser_planes": {"left": copy.deepcopy(plane), "right": copy.deepcopy(plane)},
        "turntable": {
            "center_mm": [0, 0, 0],
            "axis": [0, 0, 1],
            "diameter_mm": 200,
            "mm_per_revolution": np.pi * 200,
            "command_radians_per_mm": 0.01,
            "commanded_mm_per_revolution": 200 * np.pi,
            "command_direction": "positive",
            "reference_pose_mm": {"x": 195, "y": 0, "z": 20},
            "source": "measured_diameter",
            "quality": {"accepted": True},
        },
        "lidar": {
            "lidar_to_scanner": np.eye(4).tolist(),
            "source": "operator_measured_origin_direction",
            "quality": {"accepted": True, "rms_mm": 2.0, "maximum_rms_mm": 20.0},
        },
        "x_scale_validation": {
            "accepted": True,
            "measured_mm_per_commanded_mm": 1.0,
            "signed_mm_per_commanded_mm": 1.0,
            "command_direction": "positive",
            "expected_mm_per_commanded_mm": 1.0,
            "tolerance_fraction": 0.05,
            "repeatability_rms_mm": 0.2,
            "maximum_repeatability_mm": 3.0,
            "motor_rotation_distance_changed": False,
        },
    }


class CalibrationMathTests(unittest.TestCase):
    def test_checkerboard_is_centered_and_uses_exact_measured_geometry(self):
        points = checkerboard_points()
        self.assertEqual(points.shape, (66, 3))
        np.testing.assert_allclose(points.mean(axis=0), [0, 0, 0], atol=1e-7)
        np.testing.assert_allclose(np.ptp(points, axis=0), [130, 65, 0])

    def test_repeated_views_are_rejected_for_insufficient_diversity(self):
        corners = np.column_stack(
            (
                np.tile(np.arange(11), 6) * 5 + 10,
                np.repeat(np.arange(6), 11) * 5 + 10,
            )
        ).astype(float)
        views = [{"corners": corners.copy(), "image_size": (100, 100)} for _ in range(6)]
        with self.assertRaisesRegex(CalibrationError, "repeated near-identical"):
            validate_view_diversity(views, minimum_views=6, minimum_corner_motion=0)

    def test_centered_rotating_board_has_valid_corner_diversity(self):
        grid = checkerboard_points()[:, :2].astype(float)
        grid[:, 0] /= 500.0
        grid[:, 1] /= 500.0
        views = []
        for angle_deg in (0, 6, 12, 18, 24, 30, 36):
            angle = math.radians(angle_deg)
            distorted = grid.copy()
            distorted[:, 0] *= math.cos(angle)
            distorted[:, 1] += 0.18 * grid[:, 0] * math.sin(angle)
            corners = (distorted + [0.5, 0.5]) * [1280, 960]
            views.append({"corners": corners, "image_size": (1280, 960)})
        metrics = validate_view_diversity(views, minimum_views=6)
        self.assertLess(metrics["center_span"], 1e-12)
        self.assertGreaterEqual(metrics["unique_views"], 6)
        self.assertGreater(metrics["centered_corner_shape_motion_rms"], 0.004)
        self.assertIn("maximum_corner_track_hull", checkerboard_view_metrics(views))

    def test_view_count_is_enforced_before_opencv(self):
        with self.assertRaisesRegex(CalibrationError, "insufficient accepted views"):
            validate_view_diversity([], minimum_views=6)

    def test_robust_plane_fit_discards_outliers(self):
        grid = np.array([[x, y, 25.0] for x in range(8) for y in range(8)], dtype=float)
        points = np.vstack((grid, [[500, 500, -500], [-400, 300, 700]]))
        normal, offset, quality = fit_plane_robust(points, minimum_points=20)
        self.assertAlmostEqual(abs(normal[2]), 1.0, places=6)
        self.assertAlmostEqual(abs(offset), 25.0, places=6)
        self.assertLess(quality["inliers"], quality["samples"])
        self.assertLess(quality["rms_mm"], 0.01)

    def test_robust_plane_fit_rejects_collinear_points(self):
        points = np.array([[float(index), 0.0, 0.0] for index in range(30)])
        with self.assertRaisesRegex(CalibrationError, "2D conditioning"):
            fit_plane_robust(points, minimum_points=20)

    def test_robust_plane_fit_rejects_nearly_collinear_spread(self):
        x = np.linspace(0.0, 100.0, 30)
        points = np.column_stack(
            (x, np.where(np.arange(30) % 2, 0.0001, -0.0001), np.zeros(30))
        )

        with self.assertRaisesRegex(CalibrationError, "spread ratio"):
            fit_plane_robust(points, minimum_points=20)

    def test_lidar_transform_requires_explicit_finite_nonzero_direction(self):
        with self.assertRaises(CalibrationError):
            transform_from_beam([0, 0, 0], [0, 0, 0])
        transform = transform_from_beam([1, 2, 3], [1, 0, 0])
        np.testing.assert_allclose(transform[:3, 3], [1, 2, 3])
        np.testing.assert_allclose(transform[:3, 2], [1, 0, 0])
        self.assertAlmostEqual(np.linalg.det(transform[:3, :3]), 1.0)

    def test_payload_rejects_singular_or_unaccepted_results(self):
        payload = valid_calibration()
        validate_calibration_payload(payload)
        payload["cameras"]["pi"]["intrinsic_matrix"] = np.zeros((3, 3)).tolist()
        with self.assertRaisesRegex(CalibrationError, "singular"):
            validate_calibration_payload(payload)

    def test_payload_rejects_reflected_camera_transform(self):
        payload = valid_calibration()
        payload["cameras"]["usb"]["camera_to_scanner"][0][0] = -1
        with self.assertRaisesRegex(
            CalibrationError, "right-handed and orthonormal"
        ):
            validate_calibration_payload(payload)

    def test_payload_rejects_false_checkerboard_pattern_metadata(self):
        payload = valid_calibration()
        payload["checkerboard"]["board_columns"] = 10
        with self.assertRaisesRegex(CalibrationError, "exactly 11x6"):
            validate_calibration_payload(payload)

    def test_payload_requires_reference_for_each_moving_sensor(self):
        for sensor in ("usb", "lidar"):
            with self.subTest(sensor=sensor):
                payload = valid_calibration()
                target = (
                    payload["cameras"]["usb"]
                    if sensor == "usb"
                    else payload["lidar"]
                )
                target["carriage_axis"] = "z"
                target["carriage_direction"] = [0, 0, 1]
                with self.assertRaisesRegex(
                    CalibrationError, "reference_axis_position_mm"
                ):
                    validate_calibration_payload(payload)

    def test_payload_rejects_carriage_scale_inconsistent_with_direction(self):
        payload = valid_calibration()
        payload["cameras"]["usb"].update(
            carriage_axis="z",
            carriage_direction=[0.0, 0.0, 1.02],
            carriage_scale_mm_per_commanded_mm=1.0,
            reference_axis_position_mm=20.0,
        )
        with self.assertRaisesRegex(CalibrationError, "carriage scale"):
            validate_calibration_payload(payload)

    def test_payload_requires_lidar_to_share_usb_carriage_vector(self):
        payload = valid_calibration()
        payload["cameras"]["usb"].update(
            carriage_axis="z",
            carriage_direction=[-0.0117, -0.1742, -0.9370],
            reference_axis_position_mm=20.0,
        )
        payload["lidar"].update(
            carriage_axis="z",
            carriage_direction=[0.0, 0.0, 1.0],
            reference_axis_position_mm=20.0,
        )
        with self.assertRaisesRegex(
            CalibrationError, "must match the measured USB carriage fit"
        ):
            validate_calibration_payload(payload)

    def test_payload_rejects_legacy_laser_plane_without_pi_provenance(self):
        payload = valid_calibration()
        payload["laser_planes"]["left"].pop("source")

        with self.assertRaisesRegex(CalibrationError, "laser plane quality"):
            validate_calibration_payload(payload)

    def test_payload_never_accepts_laser_plane_limit_above_two_mm(self):
        payload = valid_calibration()
        payload["laser_planes"]["left"]["quality"].update(
            rms_mm=3.0,
            maximum_rms_mm=4.0,
        )

        with self.assertRaisesRegex(CalibrationError, "laser plane quality"):
            validate_calibration_payload(payload)

    def test_payload_requires_per_pose_inliers_and_plane_conditioning(self):
        for mutate in (
            lambda quality: quality["inlier_points_per_pose"][1].update(
                points=1
            ),
            lambda quality: quality.update(plane_spread_ratio=1e-6),
        ):
            with self.subTest(mutate=mutate):
                payload = valid_calibration()
                mutate(payload["laser_planes"]["left"]["quality"])
                with self.assertRaisesRegex(
                    CalibrationError, "laser plane quality"
                ):
                    validate_calibration_payload(payload)

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_ignores_off_board_reflections(self):
        ambient, laser, corners = self._synthetic_laser_images()
        cv2.line(laser, (8, 0), (22, 239), (0, 0, 255), 8)
        cv2.rectangle(laser, (270, 10), (319, 230), (0, 0, 255), -1)

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertTrue(diagnostic["accepted"], diagnostic)
        self.assertGreater(len(pixels), 100)
        self.assertTrue(all(145 <= point[0] <= 175 for point in pixels))
        self.assertLess(diagnostic["line_residual_rms_px"], 1.0)

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_absent_and_board_edge_lines(self):
        ambient, absent, corners = self._synthetic_laser_images(draw_line=False)
        edge = absent.copy()
        cv2.line(edge, (61, 40), (61, 200), (0, 0, 255), 3)
        short_reflection = absent.copy()
        cv2.rectangle(short_reflection, (145, 100), (175, 115), (0, 0, 255), -1)

        for name, image in (
            ("absent", absent),
            ("edge", edge),
            ("short-on-board-reflection", short_reflection),
        ):
            with self.subTest(candidate=name):
                pixels, diagnostic = extract_laser_line_pixels(
                    cv2,
                    ambient,
                    image,
                    corners,
                    config={
                        "board_columns": 11,
                        "board_rows": 6,
                        "laser_row_stride": 1,
                    },
                )
                self.assertEqual(pixels, [])
                self.assertFalse(diagnostic["accepted"])

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_finds_narrow_ridge_inside_broad_pink_halo(self):
        for halo_width, ridge_width in ((40, 3), (40, 8), (100, 3), (100, 8)):
            with self.subTest(halo_width=halo_width, ridge_width=ridge_width):
                ambient, laser, corners = self._synthetic_laser_images(
                    draw_line=False
                )
                reflectance = self._paint_checkerboard(ambient)
                laser = ambient.copy()
                laser = self._add_vertical_laser_profiles(
                    laser,
                    (
                        (160.0, halo_width / 2.355, (8.0, 8.0, 72.0)),
                        (
                            160.0,
                            ridge_width / 2.355,
                            (150.0, 150.0, 180.0),
                        ),
                    ),
                    gain=reflectance,
                )

                pixels, diagnostic = extract_laser_line_pixels(
                    cv2,
                    ambient,
                    laser,
                    corners,
                    config={
                        "board_columns": 11,
                        "board_rows": 6,
                        "laser_row_stride": 1,
                    },
                )

                self.assertTrue(diagnostic["accepted"], diagnostic)
                self.assertGreater(len(pixels), 100)
                self.assertTrue(all(157.0 <= point[0] <= 163.0 for point in pixels))
                self.assertLessEqual(diagnostic["median_line_width_px"], 8.0)
                self.assertGreater(diagnostic["raw_candidate_pixels"], 3000)
                self.assertGreater(
                    diagnostic["background_suppressed_ridge_candidates"], 100
                )
                self.assertGreater(diagnostic["median_peak_prominence"], 20.0)

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_broad_pink_halo_without_ridge(self):
        for halo_width in (20, 28, 36, 40, 100):
            with self.subTest(halo_width=halo_width):
                ambient, laser, corners = self._synthetic_laser_images(
                    draw_line=False
                )
                reflectance = self._paint_checkerboard(ambient)
                laser = ambient.copy()
                laser = self._add_vertical_laser_profiles(
                    laser,
                    ((160.0, halo_width / 2.355, (8.0, 8.0, 72.0)),),
                    gain=reflectance,
                )

                pixels, diagnostic = extract_laser_line_pixels(
                    cv2,
                    ambient,
                    laser,
                    corners,
                    config={
                        "board_columns": 11,
                        "board_rows": 6,
                        "laser_row_stride": 1,
                    },
                )

                self.assertEqual(pixels, [])
                self.assertFalse(diagnostic["accepted"])
                self.assertGreater(diagnostic["raw_candidate_pixels"], 500)

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_finds_slanted_ridge_without_cross_row_blur(self):
        ambient, laser, corners = self._synthetic_laser_images(draw_line=False)
        reflectance = self._paint_checkerboard(ambient)
        laser = ambient.copy()
        laser = self._add_vertical_laser_profiles(
            laser,
            (
                (160.0, 60 / 2.355, (8.0, 8.0, 72.0)),
                (160.0, 6 / 2.355, (150.0, 150.0, 180.0)),
            ),
            gain=reflectance,
            slope=0.35,
        )

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertTrue(diagnostic["accepted"], diagnostic)
        self.assertGreater(len(pixels), 100)
        self.assertAlmostEqual(diagnostic["line_slope_x_per_y"], 0.35, delta=0.02)
        self.assertLess(diagnostic["line_residual_rms_px"], 2.0)

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_two_comparable_parallel_ridges(self):
        ambient, laser, corners = self._synthetic_laser_images(draw_line=False)
        laser = self._add_vertical_laser_profiles(
            laser,
            (
                (145.0, 2.0, (25.0, 25.0, 190.0)),
                (175.0, 2.0, (25.0, 25.0, 180.0)),
            ),
        )

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertGreaterEqual(diagnostic["ambiguous_rows"], 100)
        self.assertIn("ambiguous", diagnostic["reason"])

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_checker_brightness_changes(self):
        ambient, laser, corners = self._synthetic_laser_images(draw_line=False)
        for row in range(5):
            for column in range(10):
                shade = 65 if (row + column) % 2 else 145
                y0, y1 = 40 + row * 32, 40 + (row + 1) * 32
                x0, x1 = 60 + column * 20, 60 + (column + 1) * 20
                ambient[y0:y1, x0:x1] = shade
                changed = min(shade + (22 if column % 2 else 38), 230)
                laser[y0:y1, x0:x1] = changed

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertEqual(diagnostic["background_suppressed_ridge_candidates"], 0)

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_gapped_ridge_and_reflections(self):
        ambient, laser, corners = self._synthetic_laser_images(draw_line=False)
        cv2.line(laser, (157, 45), (159, 95), (0, 0, 255), 4)
        cv2.line(laser, (162, 145), (164, 195), (0, 0, 255), 4)
        cv2.rectangle(laser, (112, 105), (125, 120), (0, 0, 230), -1)
        cv2.rectangle(laser, (275, 15), (315, 225), (0, 0, 255), -1)

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertIn("gap", diagnostic["reason"])

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_bridges_one_projected_checker_square(self):
        ambient, laser, corners, missing_rows = (
            self._projected_checker_ridge_images()
        )
        laser[missing_rows[0] : missing_rows[1] + 1] = ambient[
            missing_rows[0] : missing_rows[1] + 1
        ]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertTrue(diagnostic["accepted"], diagnostic)
        self.assertGreater(len(pixels), 90)
        self.assertEqual(diagnostic["bridged_checker_gaps"], 1)
        self.assertGreater(diagnostic["raw_max_gap_px"], 25)
        self.assertLessEqual(
            diagnostic["raw_max_gap_px"],
            diagnostic["checker_gap_limit_px_max"],
        )
        self.assertLessEqual(
            diagnostic["unexplained_max_gap_px"],
            diagnostic["strict_unexplained_gap_limit_px"],
        )
        self.assertGreater(diagnostic["checker_boundary_contrast_min"], 20)

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_bridges_periodic_dark_checker_gaps(self):
        ambient, laser, corners = self._checker_ridge_images()
        laser[72:104] = ambient[72:104]
        laser[136:168] = ambient[136:168]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertTrue(diagnostic["accepted"], diagnostic)
        self.assertEqual(diagnostic["bridged_checker_gaps"], 2)
        self.assertEqual(diagnostic["observed_line_segments"], 3)
        self.assertEqual(diagnostic["checker_gap_rejection_counts"], {})

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_same_size_nonchecker_gap(self):
        ambient, laser, corners = self._checker_ridge_images()
        laser[80:112] = ambient[80:112]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertEqual(diagnostic["bridged_checker_gaps"], 0)
        self.assertGreater(
            diagnostic["unexplained_max_gap_px"],
            diagnostic["strict_unexplained_gap_limit_px"],
        )
        self.assertEqual(
            diagnostic["checker_gap_rejection_counts"]["not_one_checker_square"],
            1,
        )

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_gap_on_bright_checker_band(self):
        ambient, laser, corners = self._checker_ridge_images()
        laser[104:136] = ambient[104:136]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertEqual(diagnostic["bridged_checker_gaps"], 0)
        self.assertEqual(
            diagnostic["checker_gap_rejection_counts"][
                "reflectance_boundary_mismatch"
            ],
            1,
        )

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_aligned_gap_with_ridge_response(self):
        ambient, laser, corners = self._checker_ridge_images()
        grayscale_response = self._add_vertical_laser_profiles(
            ambient.copy(),
            ((150.0, 2.0, (110.0, 110.0, 110.0)),),
        )
        laser[72:104] = grayscale_response[72:104]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertEqual(diagnostic["bridged_checker_gaps"], 0)
        self.assertEqual(
            diagnostic["checker_gap_rejection_counts"]["ridge_response_not_low"],
            1,
        )

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_shifted_stub_inside_checker_gap(self):
        ambient, laser, corners = self._checker_ridge_images()
        _, shifted, _ = self._checker_ridge_images(center=164.0)
        laser[72:104] = ambient[72:104]
        laser[82:92] = shifted[82:92]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertEqual(diagnostic["bridged_checker_gaps"], 0)
        self.assertEqual(
            diagnostic["checker_gap_rejection_counts"]["ridge_response_not_low"],
            1,
        )

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_aligned_gap_without_reflectance_boundary(self):
        ambient, _, corners = self._synthetic_laser_images(draw_line=False)
        laser = self._add_vertical_laser_profiles(
            ambient.copy(),
            ((150.0, 2.0, (90.0, 90.0, 195.0)),),
        )
        laser[72:104] = ambient[72:104]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertEqual(diagnostic["bridged_checker_gaps"], 0)
        self.assertEqual(
            diagnostic["checker_gap_rejection_counts"][
                "reflectance_boundary_mismatch"
            ],
            1,
        )

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_two_checker_square_gap(self):
        ambient, laser, corners = self._checker_ridge_images()
        laser[72:136] = ambient[72:136]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertEqual(diagnostic["bridged_checker_gaps"], 0)
        self.assertGreater(
            diagnostic["raw_max_gap_px"],
            diagnostic["checker_gap_limit_px_max"],
        )

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_checker_gap_with_sparse_adjacent_stub(self):
        ambient, laser, corners = self._checker_ridge_images()
        laser[45:61] = ambient[45:61]
        laser[72:104] = ambient[72:104]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertEqual(diagnostic["bridged_checker_gaps"], 0)
        self.assertEqual(
            diagnostic["checker_gap_rejection_counts"]["insufficient_long_segments"],
            1,
        )

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_shifted_segment_across_checker_gap(self):
        ambient, straight, corners = self._checker_ridge_images()
        _, shifted, _ = self._checker_ridge_images(center=158.0)
        laser = straight.copy()
        laser[72:104] = ambient[72:104]
        laser[104:] = shifted[104:]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertEqual(diagnostic["bridged_checker_gaps"], 0)
        self.assertIn("gap", diagnostic["reason"])

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_robustly_discards_outlier_segment(self):
        ambient, straight, corners = self._checker_ridge_images()
        _, shifted, _ = self._checker_ridge_images(center=164.0)
        laser = straight.copy()
        laser[116:126] = shifted[116:126]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertTrue(diagnostic["accepted"], diagnostic)
        self.assertGreater(len(pixels), 120)
        self.assertGreaterEqual(diagnostic["line_fit_outlier_rows"], 8)
        self.assertGreaterEqual(diagnostic["line_fit_outlier_segments"], 1)
        self.assertLess(diagnostic["line_residual_rms_px"], 2.0)

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_broadly_incoherent_ridge(self):
        ambient, _, corners = self._checker_ridge_images()
        reflectance = self._paint_checkerboard(ambient)
        rows, columns = np.indices(ambient.shape[:2], dtype=np.float32)
        center = (
            150.0
            + 5.0 * np.sin(rows * 0.31)
            + 3.0 * np.sin(rows * 0.83)
        )
        profile = np.exp(-0.5 * ((columns - center) / 2.0) ** 2)
        laser = ambient.astype(np.float32)
        laser += (
            reflectance[:, :, None]
            * profile[:, :, None]
            * np.asarray((90.0, 90.0, 195.0), dtype=np.float32)
        )
        laser = np.clip(laser, 0, 255).astype(np.uint8)

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertGreater(diagnostic["line_residual_rms_px"], 2.0)
        self.assertIn("residual", diagnostic["reason"])

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_smoothly_curved_ridge(self):
        ambient, _, corners = self._checker_ridge_images()
        reflectance = self._paint_checkerboard(ambient)
        rows, columns = np.indices(ambient.shape[:2], dtype=np.float32)
        normalized_row = (rows - 120.0) / 75.0
        center = 150.0 + 20.0 * np.square(normalized_row)
        profile = np.exp(-0.5 * ((columns - center) / 2.0) ** 2)
        laser = ambient.astype(np.float32)
        laser += (
            reflectance[:, :, None]
            * profile[:, :, None]
            * np.asarray((90.0, 90.0, 195.0), dtype=np.float32)
        )
        laser = np.clip(laser, 0, 255).astype(np.uint8)

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertGreater(diagnostic["line_residual_rms_px"], 2.0)
        self.assertIn("residual", diagnostic["reason"])

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_laser_extraction_rejects_broad_halo_and_reflections_with_gap(self):
        ambient, _, corners = self._checker_ridge_images()
        laser = self._add_vertical_laser_profiles(
            ambient.copy(),
            ((150.0, 42.0 / 2.355, (8.0, 8.0, 78.0)),),
        )
        cv2.rectangle(laser, (105, 82), (122, 102), (0, 0, 235), -1)
        cv2.rectangle(laser, (190, 138), (214, 158), (0, 0, 245), -1)
        laser[72:104] = ambient[72:104]

        pixels, diagnostic = extract_laser_line_pixels(
            cv2,
            ambient,
            laser,
            corners,
            config={
                "board_columns": 11,
                "board_rows": 6,
                "laser_row_stride": 1,
            },
        )

        self.assertEqual(pixels, [])
        self.assertFalse(diagnostic["accepted"])
        self.assertLess(
            diagnostic["sharp_ridge_candidates"],
            diagnostic["background_suppressed_ridge_candidates"],
        )

    @staticmethod
    def _synthetic_laser_images(*, draw_line=True):
        ambient = np.full((240, 320, 3), 40, dtype=np.uint8)
        corners = np.array(
            [
                [60 + column * 20, 40 + row * 32]
                for row in range(6)
                for column in range(11)
            ],
            dtype=np.float32,
        )
        cv2.circle(ambient, (160, 120), 4, (255, 255, 255), -1)
        laser = ambient.copy()
        if draw_line:
            cv2.line(laser, (156, 45), (164, 195), (0, 0, 255), 3)
        return ambient, laser, corners

    @classmethod
    def _checker_ridge_images(cls, *, center=150.0):
        ambient, _, corners = cls._synthetic_laser_images(draw_line=False)
        reflectance = cls._paint_checkerboard(ambient)
        laser = cls._add_vertical_laser_profiles(
            ambient.copy(),
            ((center, 2.0, (90.0, 90.0, 195.0)),),
            gain=reflectance,
        )
        return ambient, laser, corners

    @classmethod
    def _projected_checker_ridge_images(cls):
        height, width = 260, 340
        ambient = np.full((height, width, 3), 40, dtype=np.uint8)
        reflectance = np.ones((height, width), dtype=np.float32)
        source = np.asarray(
            ((0, 0), (10, 0), (10, 5), (0, 5)),
            dtype=np.float32,
        )
        destination = np.asarray(
            ((55, 35), (282, 48), (252, 226), (73, 202)),
            dtype=np.float32,
        )
        homography = cv2.getPerspectiveTransform(source, destination)
        grid = np.asarray(
            [
                [float(column), float(row)]
                for row in range(6)
                for column in range(11)
            ],
            dtype=np.float32,
        )
        corners = cv2.perspectiveTransform(
            grid.reshape(-1, 1, 2),
            homography,
        ).reshape(-1, 2)
        corner_grid = corners.reshape(6, 11, 2)
        for row in range(5):
            for column in range(10):
                polygon = np.rint(
                    (
                        corner_grid[row, column],
                        corner_grid[row, column + 1],
                        corner_grid[row + 1, column + 1],
                        corner_grid[row + 1, column],
                    )
                ).astype(np.int32)
                is_light = (row + column) % 2 == 0
                cv2.fillConvexPoly(ambient, polygon, 130 if is_light else 30)
                cv2.fillConvexPoly(
                    reflectance,
                    polygon,
                    1.0 if is_light else 0.55,
                )

        projected_centerline = cv2.perspectiveTransform(
            np.asarray([[[4.5, 0.0]], [[4.5, 5.0]]], dtype=np.float32),
            homography,
        ).reshape(-1, 2)
        slope = float(
            (projected_centerline[1, 0] - projected_centerline[0, 0])
            / (projected_centerline[1, 1] - projected_centerline[0, 1])
        )
        center = float(
            np.mean(projected_centerline[:, 0])
            - slope * (np.mean(projected_centerline[:, 1]) - (height - 1) / 2.0)
        )
        laser = cls._add_vertical_laser_profiles(
            ambient.copy(),
            ((center, 2.0, (90.0, 90.0, 195.0)),),
            gain=reflectance,
            slope=slope,
        )
        gap_boundaries = cv2.perspectiveTransform(
            np.asarray([[[4.5, 1.0]], [[4.5, 2.0]]], dtype=np.float32),
            homography,
        ).reshape(-1, 2)
        missing_rows = (
            int(math.ceil(float(gap_boundaries[0, 1]))),
            int(math.floor(float(gap_boundaries[1, 1]))),
        )
        return ambient, laser, corners, missing_rows

    @staticmethod
    def _paint_checkerboard(image):
        reflectance = np.ones(image.shape[:2], dtype=np.float32)
        for row in range(5):
            for column in range(10):
                y0, y1 = 40 + row * 32, 40 + (row + 1) * 32
                x0, x1 = 60 + column * 20, 60 + (column + 1) * 20
                is_light = (row + column) % 2 == 0
                image[y0:y1, x0:x1] = 130 if is_light else 30
                reflectance[y0:y1, x0:x1] = 1.0 if is_light else 0.55
        return reflectance

    @staticmethod
    def _add_vertical_laser_profiles(image, profiles, *, gain=None, slope=0.0):
        result = image.astype(np.float32)
        rows, columns = np.indices(image.shape[:2], dtype=np.float32)
        if gain is None:
            gain = np.ones(image.shape[:2], dtype=np.float32)
        for center, sigma, bgr_gain in profiles:
            center_by_row = center + slope * (rows - (image.shape[0] - 1) / 2.0)
            profile = np.exp(-0.5 * ((columns - center_by_row) / sigma) ** 2)
            result += gain[:, :, None] * profile[:, :, None] * np.asarray(
                bgr_gain, dtype=np.float32
            )[None, None, :]
        return np.clip(result, 0, 255).astype(np.uint8)


class _FakeCV:
    def __init__(self, rms=0.25):
        self.rms = rms

    def calibrateCamera(self, object_points, image_points, image_size, _a, _b):
        count = len(object_points)
        intrinsic = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=float)
        return (
            self.rms,
            intrinsic,
            np.zeros((1, 5)),
            [np.zeros((3, 1)) for _ in range(count)],
            [np.array([[0], [0], [300]], dtype=float) for _ in range(count)],
        )

    @staticmethod
    def projectPoints(points, _rvec, _tvec, _intrinsic, _distortion):
        projected = np.asarray(points)[:, :2].reshape(-1, 1, 2)
        return projected, None


class _Reservation:
    def __init__(self):
        self.held = False

    def acquire(self, blocking=False):
        if self.held:
            return False
        self.held = True
        return True

    def release(self):
        self.held = False


class _Motor:
    connected = True

    def __init__(self):
        self.positions = {"x": 195.0, "y": 0.0, "z": 10.0}
        self.calls = []

    def get_motor_status(self):
        return {
            "positions": dict(self.positions),
            "homed": {"x": True, "y": True, "z": True},
            "moving": {"x": False, "y": False, "z": False},
        }

    def move_motor(self, axis, delta):
        self.positions[axis] += delta
        self.calls.append(("move", axis, delta))
        return True

    def stop_motor(self, axis):
        self.calls.append(("stop", axis))
        return True


class _GPIO:
    simulation = False
    hardware_available = True

    def __init__(self):
        self.state = {"left": False, "right": False}
        self.calls = []

    def laser_on(self, side):
        self.state[side] = True
        self.calls.append(("on", side))
        return True

    def laser_off(self, side):
        self.state[side] = False
        self.calls.append(("off", side))
        return True


class _Camera:
    is_open = True

    @staticmethod
    def capture_jpeg():
        return b"jpeg"

    @contextmanager
    def matched_photometric_controls(self):
        yield _PhotometricSession()


class _PhotometricSession:
    controls = {
        "ExposureTime": 12000,
        "AnalogueGain": 2.5,
        "ColourGains": [1.4, 1.8],
    }

    @staticmethod
    def capture_metadata():
        return {
            "ExposureTime": 12000,
            "AnalogueGain": 2.5,
            "ColourGains": (1.4, 1.8),
        }

    def lock_from_metadata(self, _metadata):
        return copy.deepcopy(self.controls)

    def confirm_locked_controls(self):
        return copy.deepcopy(self.controls)

    def capture_jpeg(self):
        return b"jpeg", self.capture_metadata()

    @staticmethod
    def metadata_for_report(metadata):
        return {
            "ExposureTime": int(metadata["ExposureTime"]),
            "AnalogueGain": float(metadata["AnalogueGain"]),
            "ColourGains": [
                float(value) for value in metadata["ColourGains"]
            ],
        }


class _TrackedPhotometricCamera(_Camera):
    def __init__(self, capture_callback=None):
        self.photometry_active = False
        self.entries = 0
        self.restorations = 0
        self.capture_callback = capture_callback

    @contextmanager
    def matched_photometric_controls(self):
        self.entries += 1
        self.photometry_active = True
        try:
            session = _PhotometricSession()
            original_capture = session.capture_jpeg

            def capture():
                assert self.photometry_active
                if self.capture_callback is not None:
                    self.capture_callback()
                return original_capture()

            session.capture_jpeg = capture
            yield session
        finally:
            self.photometry_active = False
            self.restorations += 1


class _Lidar:
    def __init__(self):
        self.output_commands = []

    @staticmethod
    def read_distance_mm():
        return 200.0

    def set_output_enabled(self, enabled, *, timeout_s):
        assert timeout_s > 0
        self.output_commands.append(enabled)
        return True


def service_config():
    return {
        "board_columns": 11,
        "board_rows": 6,
        "square_size_mm": 13,
        "minimum_views": 3,
        "starting_pose_mm": {"x": 195, "y": 0, "z": 20},
        "pose_offsets_mm": [
            {"x": 0, "y": 0, "z": 0},
            {"x": -10, "y": 10.4719755, "z": 10},
            {"x": -20, "y": 20.9439510, "z": 20},
            {"x": -30, "y": 31.4159265, "z": 0},
            {"x": 0, "y": 41.8879020, "z": 20},
            {"x": -30, "y": 52.3598776, "z": 10},
            {"x": -15, "y": 62.8318531, "z": 20},
        ],
        "axis_limits_mm": {
            "x": {"min": 0, "max": 195},
            "y": {"min": 0, "max": 628.32},
            "z": {"min": 0, "max": 270},
        },
        "maximum_camera_rms_px": 1.0,
        "x_scale_tolerance_fraction": 0.05,
        "maximum_x_repeatability_mm": 1.0,
        "motion_timeout_s": 0.1,
        "capture_timeout_s": 0.1,
        "lidar_timeout_s": 0.1,
        "laser_photometric_settle_s": 0,
    }


class CalibrationServiceTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(exist_ok=True)
        self.config_path = SCRATCH / f"hardware-{id(self)}.json"
        self.config_path.write_text(json.dumps({"scan_calibration": {"old": True}}), encoding="utf-8")
        self.motor = _Motor()
        self.gpio = _GPIO()
        self.reservation = _Reservation()
        self.service = GeometricCalibrationService(
            motor_driver=self.motor,
            gpio_driver=self.gpio,
            cameras={"pi": _Camera(), "usb": _Camera()},
            lidar_driver=_Lidar(),
            hardware_reservation=self.reservation,
            store=AtomicCalibrationStore(self.config_path),
            config=service_config(),
            cv_module=_FakeCV(),
            sleep=lambda _seconds: None,
        )

    def tearDown(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)

    def test_preflight_requires_homing_and_explicit_lidar_transform(self):
        readiness = self.service.readiness({})
        self.assertFalse(readiness["ready"])
        self.assertTrue(any("not fully observable" in blocker for blocker in readiness["blockers"]))
        readiness = self.service.readiness(
            {"lidar": {"origin_mm": [0, 0, 0], "direction": [1, 0, 0]}}
        )
        self.assertTrue(readiness["ready"], readiness["blockers"])
        self.motor.get_motor_status = lambda: {
            "positions": self.motor.positions,
            "homed": {"x": False, "y": True, "z": True},
            "moving": {"x": False, "y": False, "z": False},
        }
        self.assertTrue(any("X must be homed" in item for item in self.service.readiness({})["blockers"]))

    def test_passive_preflight_probes_fresh_frames_and_lidar_under_reservation(self):
        options = {"lidar": {"origin_mm": [0, 0, 0], "direction": [1, 0, 0]}}
        result = self.service.preflight(options)
        self.assertTrue(result["ready"], result["blockers"])
        self.assertFalse(self.reservation.held)
        self.service._lidar.read_distance_mm = lambda: None
        result = self.service.preflight(options)
        self.assertFalse(result["ready"])
        self.assertTrue(any("TF-Luna preflight failed" in item for item in result["blockers"]))
        self.assertEqual(self.motor.calls, [])

    def test_trajectory_is_bounded_and_configurable(self):
        poses = self.service._trajectory({"starting_pose_mm": {"x": 190, "y": 5, "z": 20}})
        self.assertEqual(poses[0], {"x": 190.0, "y": 5.0, "z": 20.0})
        self.assertTrue(all(pose["x"] <= 195 for pose in self.service._trajectory({})))
        with self.assertRaisesRegex(CalibrationError, "outside configured limits"):
            self.service._trajectory({"starting_pose_mm": {"x": 206, "y": 0, "z": 10}})

    def test_trajectory_hard_caps_x_even_if_configured_limit_is_unsafe(self):
        self.service._config["axis_limits_mm"]["x"]["max"] = 210
        poses = self.service._trajectory({})
        self.assertTrue(all(pose["x"] <= 195 for pose in poses))
        readiness = self.service.readiness(
            {"lidar": {"origin_mm": [0, 0, 0], "direction": [1, 0, 0]}}
        )
        self.assertFalse(readiness["ready"])
        self.assertIn(
            "calibration X maximum must not exceed 195mm",
            readiness["blockers"],
        )
        with self.assertRaisesRegex(CalibrationError, "outside configured limits"):
            self.service._trajectory(
                {"starting_pose_mm": {"x": 210, "y": 0, "z": 10}}
            )

    def test_trajectory_rejects_z_correlated_with_commanded_x(self):
        self.service._config["pose_offsets_mm"] = [
            {
                "x": x_offset,
                "y": y_offset,
                "z": -2.0 * x_offset / 3.0,
            }
            for x_offset, y_offset in (
                (0.0, 0.0),
                (-5.0, 5.2359878),
                (-10.0, 10.4719755),
                (-15.0, 20.943951),
                (-20.0, 31.4159265),
                (-25.0, 47.1238898),
                (-30.0, 62.8318531),
            )
        ]

        with self.assertRaisesRegex(
            CalibrationError, "independently observable"
        ):
            self.service._trajectory({})

    def test_failed_starting_framing_blocks_multi_pose_motion(self):
        moved = []
        self.service._move_to = lambda pose: moved.append(dict(pose))
        self.service._capture = lambda name, **_kwargs: name.encode()
        pi_view = {
            "corners": np.zeros((66, 2), dtype=np.float32),
            "image_size": (1280, 960),
            "coverage": 0.2,
        }
        self.service._detect_checkerboard = lambda frame, pose, **_kwargs: (
            {**pi_view, "pose": dict(pose)} if frame == b"pi" else None
        )
        poses = self.service._trajectory({})
        with self.assertRaisesRegex(CalibrationError, "starting pose framing rejected"):
            self.service._capture_checkerboard_views(poses)
        self.assertEqual(moved, [poses[0]])
        self.assertEqual(self.service._lidar.output_commands, [False, True])

    def test_checkerboard_capture_restores_lidar_output_after_failure(self):
        self.service._capture_checkerboard_views_output_suspended = mock.Mock(
            side_effect=CalibrationError("simulated camera failure")
        )
        with self.assertRaisesRegex(CalibrationError, "simulated camera failure"):
            self.service._capture_checkerboard_views(
                [{"x": 195.0, "y": 0.0, "z": 10.0}]
            )
        self.assertEqual(self.service._lidar.output_commands, [False, True])
        self.assertFalse(self.service.status()["lidar_output_suspended"])

    def test_checkerboard_capture_attempts_restore_if_output_suspend_fails(self):
        def set_output(enabled, *, timeout_s):
            self.assertGreater(timeout_s, 0)
            self.service._lidar.output_commands.append(enabled)
            if not enabled:
                self.assertTrue(self.service._lidar_output_restore_required)
            return enabled

        self.service._lidar.set_output_enabled = set_output
        with self.assertRaisesRegex(CalibrationError, "output suspend failed"):
            self.service._capture_checkerboard_views(
                [{"x": 195.0, "y": 0.0, "z": 10.0}]
            )
        self.assertEqual(self.service._lidar.output_commands, [False, True])
        self.assertFalse(self.service.status()["lidar_output_suspended"])
        self.assertFalse(self.service._lidar_output_restore_required)

    def test_checkerboard_capture_restores_lidar_output_on_cancellation(self):
        def cancel(_poses):
            self.service._cancel.set()
            raise CalibrationCancelled("calibration cancelled")

        self.service._capture_checkerboard_views_output_suspended = cancel
        with self.assertRaises(CalibrationCancelled):
            self.service._capture_checkerboard_views(
                [{"x": 195.0, "y": 0.0, "z": 10.0}]
            )
        self.assertEqual(self.service._lidar.output_commands, [False, True])
        self.assertFalse(self.service.status()["lidar_output_suspended"])

    def test_framing_retries_after_one_timeout_and_accepts_first_exact_view(self):
        view = {
            "corners": np.zeros((66, 2), dtype=np.float32),
            "image_size": (1280, 960),
            "coverage": 0.2,
            "pose": {"x": 195, "y": 0, "z": 10},
        }
        self.service._capture = mock.Mock(return_value=b"usb")
        self.service._detect_checkerboard = mock.Mock(
            side_effect=[
                CheckerboardDetectionTimeout("checkerboard detection timed out"),
                view,
            ]
        )

        candidate, timeouts, exhausted, rejection_reasons = (
            self.service._capture_checkerboard_candidate(
                "usb",
                view["pose"],
                frames_per_pose=3,
                pose_deadline=time.monotonic() + 1,
            )
        )

        self.assertIs(candidate, view)
        self.assertEqual(timeouts, 1)
        self.assertFalse(exhausted)
        self.assertEqual(rejection_reasons, [])
        self.assertEqual(self.service._capture.call_count, 2)
        self.assertEqual(self.service._detect_checkerboard.call_count, 2)

    def test_starting_framing_fails_after_all_configured_frames_time_out(self):
        pose = {"x": 195.0, "y": 0.0, "z": 10.0}
        view = {
            "corners": np.zeros((66, 2), dtype=np.float32),
            "image_size": (1280, 960),
            "coverage": 0.2,
            "pose": pose,
        }
        attempts = {"usb": 0}
        self.service._config.update(
            fresh_frames_per_pose=3,
            checkerboard_pose_timeout_s=1,
        )
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda name, **_kwargs: name.encode()

        def detect(frame, _pose, **_kwargs):
            if frame == b"pi":
                return view
            attempts["usb"] += 1
            raise CheckerboardDetectionTimeout("checkerboard detection timed out")

        self.service._detect_checkerboard = detect
        with self.assertRaisesRegex(
            CalibrationError, r"usb: 3 detector timeout\(s\)"
        ):
            self.service._capture_checkerboard_views([pose])
        self.assertEqual(attempts["usb"], 3)

    def test_checkerboard_retries_obey_overall_pose_deadline(self):
        self.service._config.update(
            checkerboard_timeout_s=0.03,
            capture_timeout_s=0.03,
        )
        self.service._capture = lambda _name, **_kwargs: b"jpeg"
        attempts = 0

        def bounded_timeout(_frame, _pose, *, timeout_s):
            nonlocal attempts
            attempts += 1
            time.sleep(timeout_s)
            raise CheckerboardDetectionTimeout("checkerboard detection timed out")

        self.service._detect_checkerboard = bounded_timeout
        started = time.monotonic()
        candidate, timeouts, exhausted, rejection_reasons = (
            self.service._capture_checkerboard_candidate(
                "usb",
                {"x": 195, "y": 0, "z": 10},
                frames_per_pose=20,
                pose_deadline=started + 0.055,
            )
        )
        elapsed = time.monotonic() - started

        self.assertIsNone(candidate)
        self.assertEqual(timeouts, attempts)
        self.assertTrue(exhausted)
        self.assertEqual(rejection_reasons, [])
        self.assertLessEqual(attempts, 2)
        self.assertLess(elapsed, 0.15)

    def test_capture_cancellation_near_deadline_is_not_converted_to_timeout(self):
        def cancel_during_capture(_name, **_kwargs):
            self.service._cancel.set()
            time.sleep(0.01)
            raise CalibrationCancelled("calibration cancelled")

        self.service._capture = cancel_during_capture
        with self.assertRaises(CalibrationCancelled):
            self.service._capture_checkerboard_candidate(
                "usb",
                {"x": 195, "y": 0, "z": 10},
                frames_per_pose=1,
                pose_deadline=time.monotonic() + 0.005,
            )

    def test_cancel_at_last_camera_last_pose_is_checked_before_diversity(self):
        pose = {"x": 195.0, "y": 0.0, "z": 10.0}
        view = {
            "corners": np.zeros((66, 2), dtype=np.float32),
            "image_size": (1280, 960),
            "coverage": 0.2,
            "pose": pose,
        }
        self.service._config.update(
            fresh_frames_per_pose=1,
            checkerboard_pose_timeout_s=1,
        )
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda name, **_kwargs: name.encode()

        def cancel_on_last_camera(frame, _pose, **_kwargs):
            if frame == b"usb":
                self.service._cancel.set()
            return view

        self.service._detect_checkerboard = cancel_on_last_camera
        with (
            mock.patch(
                "software.api.geometric_calibration.validate_view_diversity"
            ) as diversity,
            self.assertRaises(CalibrationCancelled),
        ):
            self.service._capture_checkerboard_views([pose])
        diversity.assert_not_called()

    def test_intrinsic_solver_preserves_distortion_and_rejects_bad_rms(self):
        points = checkerboard_points()[:, :2]
        views = [
            {"corners": points.copy(), "image_size": (640, 480)}
            for _ in range(3)
        ]
        result = self.service._calibrate_camera_intrinsics(views)
        self.assertEqual(len(result["distortion_coefficients"]), 5)
        self.assertTrue(result["quality"]["accepted"])
        self.service._cv.rms = 2.0
        with self.assertRaisesRegex(CalibrationError, "exceeds"):
            self.service._calibrate_camera_intrinsics(views)

    def test_calibration_detector_accepts_sb_full_frame_corners_and_records_glare(self):
        image = np.zeros((960, 1280, 3), dtype=np.uint8)
        corners = np.array(
            [[[200 + column * 70, 250 + row * 70]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with mock.patch(
            "software.api.geometric_calibration.find_checkerboard_bounded",
            return_value={
                "found": True,
                "pattern": (11, 6),
                "corners": corners,
                "method": "sb",
                "glare_masked": True,
            },
        ):
            view = self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )
        self.assertIsNotNone(view)
        self.assertEqual(view["image_size"], (1280, 960))
        self.assertEqual(view["detection_method"], "sb")
        self.assertTrue(view["glare_masked"])

    def test_calibration_accepts_exact_board_with_2_7_percent_corner_margin(self):
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        corners = np.array(
            [[[27 + column * 80, 100 + row * 100]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with mock.patch(
            "software.api.geometric_calibration.find_checkerboard_bounded",
            return_value={
                "found": True,
                "pattern": (11, 6),
                "corners": corners,
                "method": "sb",
                "glare_masked": False,
            },
        ):
            view = self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )

        self.assertAlmostEqual(view["minimum_frame_margin"], 0.027, places=6)
        self.assertEqual(view["frame_margins"]["left"], view["minimum_frame_margin"])

    def test_calibration_frame_margin_remains_configurable(self):
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        corners = np.array(
            [[[27 + column * 80, 100 + row * 100]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._config["minimum_frame_margin"] = 0.03
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with (
            mock.patch(
                "software.api.geometric_calibration.find_checkerboard_bounded",
                return_value={
                    "found": True,
                    "pattern": (11, 6),
                    "corners": corners,
                    "method": "sb",
                },
            ),
            self.assertRaisesRegex(
                CheckerboardDetectionRejected,
                r"left corner margin 0\.0270.*minimum_frame_margin 0\.0300",
            ),
        ):
            self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )

    def test_calibration_rejects_exact_board_too_close_to_frame_edge(self):
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        corners = np.array(
            [[[19 + column * 80, 100 + row * 100]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with mock.patch(
            "software.api.geometric_calibration.find_checkerboard_bounded",
            return_value={
                "found": True,
                "pattern": (11, 6),
                "corners": corners,
                "method": "sb",
            },
        ):
            with self.assertRaisesRegex(
                CheckerboardDetectionRejected,
                r"left corner margin 0\.0190.*minimum_frame_margin 0\.0200",
            ):
                self.service._detect_checkerboard(
                    b"jpeg", {"x": 195, "y": 0, "z": 10}
                )

    def test_calibration_reports_low_coverage_separately_from_frame_margin(self):
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        corners = np.array(
            [[[100 + column * 4, 100 + row * 4]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with (
            mock.patch(
                "software.api.geometric_calibration.find_checkerboard_bounded",
                return_value={
                    "found": True,
                    "pattern": (11, 6),
                    "corners": corners,
                    "method": "classic",
                },
            ),
            self.assertRaisesRegex(
                CheckerboardDetectionRejected,
                r"board coverage 0\.0008.*minimum_board_coverage 0\.0300",
            ),
        ):
            self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )

    def test_starting_framing_reports_detection_and_coverage_rejections(self):
        pose = {"x": 195.0, "y": 0.0, "z": 10.0}
        self.service._config.update(fresh_frames_per_pose=1)
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda name, **_kwargs: name.encode()

        def reject(frame, _pose, **_kwargs):
            if frame == b"pi":
                raise CheckerboardDetectionRejected(
                    "board coverage 0.0120 is below minimum_board_coverage 0.0300"
                )
            raise CheckerboardDetectionRejected(
                "IR glare mask overlaps a detected checkerboard corner"
            )

        self.service._detect_checkerboard = reject
        with self.assertRaisesRegex(
            CalibrationError,
            r"pi: board coverage 0\.0120.*usb: IR glare mask overlaps",
        ):
            self.service._capture_checkerboard_views([pose])
        self.assertIn(
            "board coverage",
            self.service.status()["last_checkerboard_rejection"]["pi"],
        )
        self.assertIn(
            "IR glare",
            self.service.status()["last_checkerboard_rejection"]["usb"],
        )

    def test_calibration_detector_surfaces_bounded_detection_timeout(self):
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: np.zeros(
            (960, 1280, 3), dtype=np.uint8
        )
        with mock.patch(
            "software.api.geometric_calibration.find_checkerboard_bounded",
            return_value={"found": False, "timed_out": True},
        ):
            with self.assertRaisesRegex(CalibrationError, "timed out"):
                self.service._detect_checkerboard(
                    b"jpeg", {"x": 195, "y": 0, "z": 10}
                )

    def test_calibration_rejects_detector_result_for_different_pattern(self):
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: np.zeros(
            (960, 1280, 3), dtype=np.uint8
        )
        false_corners = np.zeros((60, 1, 2), dtype=np.float32)
        with (
            mock.patch(
                "software.api.geometric_calibration.find_checkerboard_bounded",
                return_value={
                    "found": True,
                    "pattern": (10, 6),
                    "corners": false_corners,
                    "method": "sb",
                },
            ),
            self.assertRaisesRegex(
                CheckerboardDetectionRejected,
                r"detected checkerboard pattern \(10, 6\), expected \(11, 6\)",
            ),
        ):
            self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )

    def test_x_scale_is_validated_without_changing_rotation_distance(self):
        self.service._motion_model.update(
            x_mm_per_commanded_mm=-1.0,
            x_direction="negative",
            x_translation_rms_mm=0.2,
        )
        result = self.service._validate_x_scale()
        self.assertTrue(result["accepted"])
        self.assertEqual(result["signed_mm_per_commanded_mm"], -1.0)
        self.assertFalse(result["motor_rotation_distance_changed"])
        self.service._motion_model["x_mm_per_commanded_mm"] = -1.2
        with self.assertRaisesRegex(CalibrationError, "rotation_distance was not changed"):
            self.service._validate_x_scale()

    def test_scanner_frame_pose_math_and_extrinsic_average_are_consistent(self):
        self.service._reference_pose = {"x": 195, "y": 0, "z": 10}
        self.service._motion_model.update(
            x_mm_per_commanded_mm=1.0,
            y_radians_per_commanded_mm=0.01,
        )
        transform = self.service._board_to_scanner({"x": 185, "y": 0, "z": 10})
        np.testing.assert_allclose(transform[:3, 3], [-10, 0, 0])
        np.testing.assert_allclose(transform[:3, :3], [[0, 0, 1], [1, 0, 0], [0, 1, 0]])
        shifted = transform.copy()
        shifted[:3, 3] += [0, 2, 0]
        average, translation_rms, rotation_rms = self.service._average_transforms(
            [transform, shifted]
        )
        np.testing.assert_allclose(average[:3, 3], [-10, 1, 0])
        self.assertAlmostEqual(translation_rms, 1.0)
        self.assertAlmostEqual(rotation_rms, 0.0)

    def _synthetic_motion_views(
        self,
        x_scale,
        y_scale,
        *,
        opposed_usb_pnp_frame=False,
        live_candidate_split_noise=False,
        usb_pnp_adjustment=None,
        usb_carriage_direction=None,
        usb_same_side=False,
    ):
        poses = self.service._trajectory({})
        self.service._reference_pose = dict(poses[0])
        camera_to_scanner = {
            "pi": np.array(
                [
                    [0, 0, -1, 280],
                    [1, 0, 0, -35],
                    [0, -1, 0, 80],
                    [0, 0, 0, 1],
                ],
                dtype=float,
            ),
            "usb": np.array(
                [
                    [0, 0, 1, -260],
                    [-1, 0, 0, 45],
                    [0, -1, 0, 70],
                    [0, 0, 0, 1],
                ],
                dtype=float,
            ),
        }
        if usb_same_side:
            camera_to_scanner["usb"] = np.array(
                [
                    [0, 0, -1, 240],
                    [1, 0, 0, 35],
                    [0, -1, 0, 65],
                    [0, 0, 0, 1],
                ],
                dtype=float,
            )
        adjustment_name = usb_pnp_adjustment
        if opposed_usb_pnp_frame and adjustment_name is None:
            adjustment_name = "rotate_180_about_board_normal"
        pnp_adjustment = np.eye(4)
        if adjustment_name is not None:
            pnp_adjustment[:3, :3] = PNP_BOARD_FRAME_ADJUSTMENTS[
                adjustment_name
            ]
        carriage_direction = np.asarray(
            usb_carriage_direction
            if usb_carriage_direction is not None
            else [0.0, 0.0, 1.0],
            dtype=float,
        )
        rotation_noise_deg = {
            "pi": [0.7, -0.35, 0.25, -0.7, 0.35, -0.25, 0.0],
            "usb": [-0.38, 0.75, -0.28, 0.38, -0.75, 0.28, 0.0],
        }
        translation_noise_scale = {"pi": 1.045, "usb": 0.24}
        translation_noise = [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0]
        views = {"pi": [], "usb": []}
        for name in ("pi", "usb"):
            for index, pose in enumerate(poses):
                scanner_from_board = self.service._board_transform(
                    pose, x_scale=x_scale, y_scale=y_scale
                )
                scanner_from_camera = camera_to_scanner[name].copy()
                if name == "usb":
                    scanner_from_camera[:3, 3] += (
                        carriage_direction * (pose["z"] - poses[0]["z"])
                    )
                if live_candidate_split_noise:
                    scanner_from_camera[:3, :3] = (
                        self.service._rotation_z(
                            math.radians(rotation_noise_deg[name][index])
                        )
                        @ scanner_from_camera[:3, :3]
                    )
                    scanner_from_camera[1, 3] += (
                        translation_noise_scale[name] * translation_noise[index]
                    )
                views[name].append(
                    {
                        "pose": dict(pose),
                        "board_to_camera": (
                            np.linalg.inv(scanner_from_camera) @ scanner_from_board
                        )
                        @ (pnp_adjustment if name == "usb" else np.eye(4)),
                    }
                )
        return views, camera_to_scanner

    @staticmethod
    def _reported_pnp_transform(center, rotation_vector_deg):
        vector = np.radians(np.asarray(rotation_vector_deg, dtype=float))
        angle = float(np.linalg.norm(vector))
        axis = vector / angle
        skew = np.array(
            [
                [0.0, -axis[2], axis[1]],
                [axis[2], 0.0, -axis[0]],
                [-axis[1], axis[0], 0.0],
            ]
        )
        rotation = (
            np.eye(3)
            + math.sin(angle) * skew
            + (1.0 - math.cos(angle)) * (skew @ skew)
        )
        transform = np.eye(4)
        transform[:3, :3] = rotation
        transform[:3, 3] = center
        return transform

    def _reported_usb_instability_views(self):
        reported = (
            ((195.0, 0.0, 20.0), (7.7689, -42.6043, 303.6122), (-5.2297, 10.1599, -179.4221)),
            ((190.0, 5.2359878, 25.0), (7.1835, -37.5778, 299.1696), (-11.2113, 9.7636, -179.0354)),
            ((185.0, 10.4719755, 30.0), (6.9176, -32.5128, 294.6806), (-16.7733, 9.4206, -178.4601)),
            ((175.0, 20.943951, 40.0), (5.7753, -22.0782, 285.7573), (-25.7417, 9.0713, -177.2481)),
            ((170.0, 26.1799388, 35.0), (5.4555, -26.4063, 280.3378), (-31.3192, 8.9019, -176.2627)),
            ((165.0, 31.4159265, 20.0), (5.6126, -40.3572, 273.9613), (-35.0612, 8.7755, -175.5182)),
            ((190.0, 36.6519143, 30.0), (5.9068, -32.8844, 299.0631), (-40.0429, 8.7588, -174.3194)),
            ((195.0, 41.887902, 40.0), (5.3358, -23.5975, 304.9199), (5.6128, 29.1607, 1.0009)),
            ((175.0, 47.1238898, 25.0), (4.8782, -36.4416, 284.1871), (5.5275, 32.2762, 1.0628)),
            ((165.0, 52.3598776, 30.0), (4.4545, -30.9514, 274.6899), (-53.5058, 8.473, -170.4277)),
            ((180.0, 62.8318531, 40.0), (3.9563, -22.4114, 290.0987), (-63.9066, 8.2341, -166.5688)),
        )
        return [
            {
                "pose": dict(zip(("x", "y", "z"), pose)),
                "board_to_camera": self._reported_pnp_transform(center, rotation),
            }
            for pose, center, rotation in reported
        ]

    def _usb_extrinsic_candidates(self, views, adjustment_name):
        adjustment = PNP_BOARD_FRAME_ADJUSTMENTS[adjustment_name]
        candidates = []
        for view in views:
            observed = view["board_to_camera"].copy()
            observed[:3, :3] = observed[:3, :3] @ adjustment
            candidates.append(
                self.service._board_to_scanner(view["pose"])
                @ np.linalg.inv(observed)
            )
        return candidates

    def test_axis_model_recovers_both_command_signs_and_moving_usb(self):
        expected_y = 2.0 / 200.0
        for x_sign in (-1.0, 1.0):
            for y_sign in (-1.0, 1.0):
                with self.subTest(x_sign=x_sign, y_sign=y_sign):
                    views, expected_cameras = self._synthetic_motion_views(
                        x_sign, y_sign * expected_y * 1.02
                    )
                    model = self.service._estimate_motion_model(views)
                    self.service._motion_model = model
                    self.assertAlmostEqual(
                        model["x_mm_per_commanded_mm"], x_sign, places=5
                    )
                    self.assertAlmostEqual(
                        model["y_radians_per_commanded_mm"],
                        y_sign * expected_y * 1.02,
                        places=6,
                    )
                    self.assertGreater(
                        model["candidate_residuals"]["x"][
                            "direction_score_ratio"
                        ],
                        2,
                    )
                    for name in ("pi", "usb"):
                        camera = {
                            "quality": {
                                "accepted": True,
                                "rms_px": 0.1,
                                "maximum_rms_px": 1.0,
                            }
                        }
                        result = self.service._calibrate_camera_extrinsics(
                            name, views[name], camera, {}
                        )
                        np.testing.assert_allclose(
                            result["camera_to_scanner"],
                            expected_cameras[name],
                            atol=1e-5,
                        )
                        self.assertEqual(
                            result["quality"]["command_sign_reference_camera"], "pi"
                        )

    def test_fixed_pi_sign_fit_handles_opposed_usb_candidate_split(self):
        expected_x = -0.984607
        expected_y = 0.01065
        views, expected_cameras = self._synthetic_motion_views(
            expected_x,
            expected_y,
            opposed_usb_pnp_frame=True,
            live_candidate_split_noise=True,
        )

        pi_positive = self.service._rotation_fit(
            {"pi": views["pi"]}, expected_y
        )
        pi_negative = self.service._rotation_fit(
            {"pi": views["pi"]}, -expected_y
        )
        usb_positive = self.service._rotation_fit(
            {"usb": views["usb"]}, expected_y
        )
        usb_negative = self.service._rotation_fit(
            {"usb": views["usb"]}, -expected_y
        )
        self.assertGreater(pi_positive["rotation_rms_deg"], 0.4)
        self.assertLess(pi_positive["rotation_rms_deg"], 0.5)
        self.assertGreater(pi_negative["rotation_rms_deg"], 24)
        self.assertLess(pi_negative["rotation_rms_deg"], 27)
        self.assertGreater(usb_positive["rotation_rms_deg"], 24)
        self.assertLess(usb_positive["rotation_rms_deg"], 27)
        self.assertGreater(usb_negative["rotation_rms_deg"], 0.4)
        self.assertLess(usb_negative["rotation_rms_deg"], 0.55)

        raw_x_candidate = self.service._translation_fit_score(
            views, x_scale=expected_x, y_scale=expected_y
        )
        self.assertGreater(
            raw_x_candidate["per_camera_translation_rms_mm"]["pi"], 1.8
        )
        self.assertLess(
            raw_x_candidate["per_camera_translation_rms_mm"]["pi"], 2.3
        )
        self.assertGreater(
            raw_x_candidate["per_camera_translation_rms_mm"]["usb"], 120
        )

        self.service._config["maximum_x_repeatability_mm"] = 3.0
        model = self.service._estimate_motion_model(views)
        self.service._motion_model = model
        self.assertEqual(model["command_sign_reference_camera"], "pi")
        self.assertAlmostEqual(
            model["x_mm_per_commanded_mm"], expected_x, delta=0.003
        )
        self.assertAlmostEqual(
            model["y_radians_per_commanded_mm"], expected_y, places=4
        )
        self.assertEqual(
            model["candidate_residuals"]["command_sign_reference_camera"], "pi"
        )

        for name in ("pi", "usb"):
            result = self.service._calibrate_camera_extrinsics(
                name,
                views[name],
                {
                    "quality": {
                        "accepted": True,
                        "rms_px": 0.1,
                        "maximum_rms_px": 1.0,
                    }
                },
                {},
            )
            actual = np.asarray(result["camera_to_scanner"])
            expected = expected_cameras[name]
            np.testing.assert_allclose(
                actual[:3, :3], expected[:3, :3], atol=0.01
            )
            self.assertLess(
                float(np.linalg.norm(actual[:3, 3] - expected[:3, 3])), 1.0
            )
        self.assertEqual(
            result["quality"]["pnp_board_frame_adjustment"],
            "rotate_180_about_board_normal",
        )
        self.assertEqual(
            result["quality"]["calibration_role"],
            "moving_cross_validation_after_z_correction",
        )

    def test_usb_joint_fit_selects_planar_normal_and_signed_carriage_vector(self):
        self.service._config["minimum_views"] = 6
        expected_carriage = np.array([-0.0117, -0.1742, -0.9370])
        cases = (
            ("identity", True),
            ("rotate_180_about_board_x", False),
            ("rotate_180_about_board_y", False),
            ("rotate_180_about_board_normal", False),
        )
        for adjustment_name, same_side in cases:
            with self.subTest(
                adjustment=adjustment_name, same_side=same_side
            ):
                views, expected_cameras = self._synthetic_motion_views(
                    -1.0,
                    0.01,
                    usb_pnp_adjustment=adjustment_name,
                    usb_carriage_direction=expected_carriage,
                    usb_same_side=same_side,
                )
                self.service._motion_model = self.service._estimate_motion_model(
                    views
                )
                result = self.service._calibrate_camera_extrinsics(
                    "usb",
                    views["usb"],
                    {
                        "quality": {
                            "accepted": True,
                            "rms_px": 0.1,
                            "maximum_rms_px": 1.0,
                        }
                    },
                    {},
                )
                np.testing.assert_allclose(
                    result["camera_to_scanner"],
                    expected_cameras["usb"],
                    atol=1e-6,
                )
                np.testing.assert_allclose(
                    result["carriage_direction"],
                    expected_carriage,
                    atol=1e-8,
                )
                self.assertAlmostEqual(
                    result["carriage_scale_mm_per_commanded_mm"],
                    float(np.linalg.norm(expected_carriage)),
                )
                self.assertEqual(
                    result["quality"]["pnp_board_frame_adjustment"],
                    adjustment_name,
                )
                self.assertTrue(result["quality"]["carriage_fit"]["accepted"])
                self.assertAlmostEqual(
                    result["quality"]["carriage_fit"]["vertical_alignment_deg"],
                    10.557,
                    delta=0.01,
                )
                self.assertEqual(
                    result["quality"]["carriage_fit"][
                        "maximum_vertical_alignment_deg"
                    ],
                    12.0,
                )
                self.assertAlmostEqual(
                    np.linalg.det(
                        np.asarray(
                            result["quality"][
                                "pnp_board_frame_adjustment_matrix"
                            ]
                        )
                    ),
                    1.0,
                )

    def test_reported_pnp_switches_recover_stable_carriage_fit(self):
        views = self._reported_usb_instability_views()
        self.service._reference_pose = dict(views[0]["pose"])
        self.service._motion_model.update(
            x_mm_per_commanded_mm=-1.041255564387572,
            y_radians_per_commanded_mm=0.010325040740740742,
        )
        self.service._config.update(
            minimum_views=6,
            maximum_usb_z_vertical_alignment_deg=12.0,
        )

        result = self.service._calibrate_camera_extrinsics(
            "usb",
            views,
            {
                "quality": {
                    "accepted": True,
                    "rms_px": 0.5366,
                    "maximum_rms_px": 1.25,
                }
            },
            {},
        )

        np.testing.assert_allclose(
            result["carriage_direction"],
            [-0.014956, -0.185308, -0.925129],
            atol=1e-5,
        )
        self.assertLess(
            result["quality"]["carriage_fit"]["vertical_alignment_deg"], 12.0
        )
        self.assertLess(result["quality"]["extrinsic_translation_rms_mm"], 3.0)
        self.assertLess(result["quality"]["extrinsic_rotation_rms_deg"], 0.6)
        self.assertEqual(result["quality"]["robust_pnp_inliers"], 11)
        normalization = result["quality"]["pnp_board_frame_normalization"]
        self.assertEqual(normalization["changed_views"], [8, 9])
        self.assertEqual(
            [normalization["per_view"][index]["selected_adjustment"] for index in (7, 8)],
            ["rotate_180_about_board_y", "rotate_180_about_board_y"],
        )
        fit = result["quality"]["carriage_fit"]
        self.assertEqual(fit["estimator"], "z_residualized_against_commanded_x_y")
        self.assertEqual(fit["commanded_xy_model_source"], "fixed_pi_axis_model")
        self.assertAlmostEqual(
            fit["pi_x_mm_per_commanded_mm"], -1.041255564387572
        )
        self.assertEqual(fit["z_level_inliers"], {"20": 2, "25": 2, "30": 3, "35": 1, "40": 3})
        self.assertGreater(fit["independent_z_leverage_ratio"], 0.8)
        self.assertLess(fit["vector_uncertainty_mm_per_commanded_mm"], 0.15)

    def test_stable_nine_to_thirteen_degree_carriage_vectors_remain_distinct(self):
        self.service._config.update(
            minimum_views=6,
            maximum_usb_z_vertical_alignment_deg=15.0,
        )
        stable_vectors = (
            ([-0.0130, -0.1543, -0.9367], 9.39),
            ([-0.0139, -0.2164, -0.9171], 13.31),
            ([-0.0134, -0.2114, -0.9222], 12.94),
        )
        for expected, expected_alignment in stable_vectors:
            with self.subTest(expected=expected):
                views, _ = self._synthetic_motion_views(
                    -1.0,
                    0.01,
                    usb_pnp_adjustment="rotate_180_about_board_x",
                    usb_carriage_direction=expected,
                )
                self.service._motion_model = self.service._estimate_motion_model(
                    views
                )
                result = self.service._calibrate_camera_extrinsics(
                    "usb",
                    views["usb"],
                    {
                        "quality": {
                            "accepted": True,
                            "rms_px": 0.2,
                            "maximum_rms_px": 1.25,
                        }
                    },
                    {},
                )
                np.testing.assert_allclose(
                    result["carriage_direction"], expected, atol=1e-8
                )
                self.assertAlmostEqual(
                    result["quality"]["carriage_fit"][
                        "vertical_alignment_deg"
                    ],
                    expected_alignment,
                    delta=0.02,
                )

        self.service._config["maximum_usb_z_vertical_alignment_deg"] = 12.0
        views, _ = self._synthetic_motion_views(
            -1.0,
            0.01,
            usb_pnp_adjustment="rotate_180_about_board_x",
            usb_carriage_direction=stable_vectors[1][0],
        )
        self.service._motion_model = self.service._estimate_motion_model(views)
        with self.assertRaisesRegex(CalibrationError, "usb carriage Z fit"):
            self.service._calibrate_camera_extrinsics(
                "usb",
                views["usb"],
                {
                    "quality": {
                        "accepted": True,
                        "rms_px": 0.2,
                        "maximum_rms_px": 1.25,
                    }
                },
                {},
            )

    def test_carriage_fit_rejects_pnp_mask_without_every_z_level(self):
        views, _ = self._synthetic_motion_views(
            -1.0,
            0.01,
            usb_pnp_adjustment="rotate_180_about_board_x",
            usb_carriage_direction=[-0.0117, -0.1742, -0.9370],
        )
        self.service._motion_model = self.service._estimate_motion_model(views)
        candidates = self._usb_extrinsic_candidates(
            views["usb"], "rotate_180_about_board_x"
        )
        eligible = np.asarray(
            [view["pose"]["z"] != 20.0 for view in views["usb"]], dtype=bool
        )

        with self.assertRaisesRegex(
            CalibrationError, "removes all support for Z=20"
        ):
            self.service._fit_usb_carriage(
                views["usb"],
                candidates,
                minimum=6,
                eligible=eligible,
            )

    def test_carriage_fit_rejects_commands_without_independent_z_leverage(self):
        self.service._reference_pose = {"x": 195.0, "y": 0.0, "z": 20.0}
        offsets = (
            (0.0, 0.0),
            (-5.0, 5.0),
            (-10.0, 10.0),
            (-15.0, 15.0),
            (-20.0, 20.0),
            (-25.0, 25.0),
            (-30.0, 30.0),
        )
        views = []
        candidates = []
        for x_offset, y_offset in offsets:
            z_offset = -2.0 * x_offset / 3.0
            views.append(
                {
                    "pose": {
                        "x": 195.0 + x_offset,
                        "y": y_offset,
                        "z": 20.0 + z_offset,
                    }
                }
            )
            candidate = np.eye(4)
            candidate[:3, 3] = [
                100.0 + x_offset,
                -20.0 + y_offset,
                30.0 - z_offset,
            ]
            candidates.append(candidate)

        with self.assertRaisesRegex(CalibrationError, "independent Z leverage"):
            self.service._fit_usb_carriage(views, candidates, minimum=6)

    def test_carriage_fit_isolates_one_translation_outlier_without_losing_level(self):
        expected = np.array([-0.0117, -0.1742, -0.9370])
        views, _ = self._synthetic_motion_views(
            -1.0,
            0.01,
            usb_pnp_adjustment="rotate_180_about_board_x",
            usb_carriage_direction=expected,
        )
        self.service._motion_model = self.service._estimate_motion_model(views)
        candidates = self._usb_extrinsic_candidates(
            views["usb"], "rotate_180_about_board_x"
        )
        candidates[2][:3, 3] += [30.0, -20.0, 15.0]

        fit = self.service._fit_usb_carriage(
            views["usb"], candidates, minimum=6
        )

        self.assertTrue(fit["accepted"])
        self.assertEqual(fit["regression_rejected_views"], [3])
        self.assertGreaterEqual(fit["z_level_inliers"]["40"], 2)
        np.testing.assert_allclose(
            fit["vector_mm_per_commanded_mm"], expected, atol=1e-8
        )

    def test_carriage_rejection_keeps_original_view_number_after_missing_pnp(self):
        expected = np.array([-0.0117, -0.1742, -0.9370])
        views, _ = self._synthetic_motion_views(
            -1.0,
            0.01,
            usb_pnp_adjustment="rotate_180_about_board_x",
            usb_carriage_direction=expected,
        )
        self.service._motion_model = self.service._estimate_motion_model(views)
        self.service._config["maximum_extrinsic_rms_mm"] = 1.0
        candidates = self._usb_extrinsic_candidates(
            views["usb"], "rotate_180_about_board_x"
        )
        candidate_views = views["usb"][1:]
        candidates = candidates[1:]
        candidates[1][:3, 3] += [30.0, -20.0, 15.0]

        fit = self.service._fit_usb_carriage(
            candidate_views,
            candidates,
            minimum=5,
            required_z_levels=[20.0, 30.0, 40.0],
            view_numbers=[2, 3, 4, 5, 6, 7],
        )

        self.assertTrue(fit["accepted"])
        self.assertEqual(fit["regression_rejected_views"], [3])

    def test_discrete_pnp_normalization_does_not_hide_real_rotation_wobble(self):
        expected_carriage = np.array([-0.0117, -0.1742, -0.9370])
        views, expected_cameras = self._synthetic_motion_views(
            -1.0,
            0.01,
            usb_pnp_adjustment="rotate_180_about_board_x",
            usb_carriage_direction=expected_carriage,
        )
        self.service._motion_model = self.service._estimate_motion_model(views)
        for index, view in enumerate(views["usb"]):
            scanner_from_camera = expected_cameras["usb"].copy()
            scanner_from_camera[:3, 3] += expected_carriage * (
                view["pose"]["z"] - views["usb"][0]["pose"]["z"]
            )
            scanner_from_camera[:3, :3] = (
                self.service._rotation_z(
                    math.radians(8.0 if index % 2 else -8.0)
                )
                @ scanner_from_camera[:3, :3]
            )
            board_adjustment = np.eye(4)
            board_adjustment[:3, :3] = PNP_BOARD_FRAME_ADJUSTMENTS[
                "rotate_180_about_board_x"
            ]
            view["board_to_camera"] = (
                np.linalg.inv(scanner_from_camera)
                @ self.service._board_to_scanner(view["pose"])
                @ board_adjustment
            )

        with self.assertRaisesRegex(
            CalibrationError, "usb carriage Z fit"
        ) as raised:
            self.service._calibrate_camera_extrinsics(
                "usb",
                views["usb"],
                {
                    "quality": {
                        "accepted": True,
                        "rms_px": 0.2,
                        "maximum_rms_px": 1.25,
                    }
                },
                {},
            )
        self.assertIn(
            "removes all support for Z=30mm", str(raised.exception)
        )

    def test_wrong_planar_normal_exposes_two_x_slope_and_is_rejected(self):
        views, _ = self._synthetic_motion_views(
            -1.0,
            0.01,
            usb_pnp_adjustment="rotate_180_about_board_y",
        )
        self.service._motion_model = self.service._estimate_motion_model(views)
        result = self.service._calibrate_camera_extrinsics(
            "usb",
            views["usb"],
            {
                "quality": {
                    "accepted": True,
                    "rms_px": 0.1,
                    "maximum_rms_px": 1.0,
                }
            },
            {},
        )
        fits = result["quality"]["pnp_board_frame_candidate_fits"]
        wrong = fits["identity"]
        self.assertFalse(wrong["accepted"])
        self.assertGreater(wrong["translation_rms_mm"], 5.0)
        x_slope = wrong["translation_slopes_mm_per_commanded_mm"][
            "commanded_x"
        ]["scanner_x"]
        self.assertGreater(abs(x_slope), 1.8)
        self.assertLess(abs(x_slope), 2.2)
        self.assertEqual(
            result["quality"]["pnp_board_frame_adjustment"],
            "rotate_180_about_board_y",
        )

    def test_unobservable_candidate_does_not_abort_later_planar_rotations(self):
        self.service._config["minimum_views"] = 6
        views, _ = self._synthetic_motion_views(
            -1.0,
            0.01,
            usb_pnp_adjustment="rotate_180_about_board_y",
        )
        self.service._motion_model = self.service._estimate_motion_model(views)
        original_fit = self.service._fit_usb_carriage
        calls = 0

        def reject_first_candidate(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise CalibrationError("synthetic unobservable candidate")
            return original_fit(*args, **kwargs)

        with mock.patch.object(
            self.service,
            "_fit_usb_carriage",
            side_effect=reject_first_candidate,
        ):
            result = self.service._calibrate_camera_extrinsics(
                "usb",
                views["usb"],
                {
                    "quality": {
                        "accepted": True,
                        "rms_px": 0.1,
                        "maximum_rms_px": 1.0,
                    }
                },
                {},
            )

        fits = result["quality"]["pnp_board_frame_candidate_fits"]
        self.assertIn("synthetic unobservable", fits["identity"]["carriage_fit"]["error"])
        self.assertEqual(
            result["quality"]["pnp_board_frame_adjustment"],
            "rotate_180_about_board_y",
        )

    def test_ambiguous_usb_board_frame_convention_is_rejected(self):
        views, _ = self._synthetic_motion_views(-1.0, 0.01)
        self.service._motion_model = self.service._estimate_motion_model(views)
        self.service._config["maximum_extrinsic_rms_mm"] = 1000.0
        self.service._config["maximum_extrinsic_rms_deg"] = 180.0
        with self.assertRaisesRegex(
            CalibrationError, "usb PnP board-frame convention is ambiguous"
        ):
            self.service._calibrate_camera_extrinsics(
                "usb",
                views["usb"],
                {
                    "quality": {
                        "accepted": True,
                        "rms_px": 0.1,
                        "maximum_rms_px": 1.0,
                    }
                },
                {},
            )

    def test_bad_usb_cross_validation_cannot_be_ignored(self):
        views, _ = self._synthetic_motion_views(
            -0.984607,
            0.01065,
            opposed_usb_pnp_frame=True,
        )
        model = self.service._estimate_motion_model(views)
        self.service._motion_model = model
        for index, view in enumerate(views["usb"]):
            view["board_to_camera"][:3, 3] += [
                15.0 * (-1 if index % 2 else 1),
                8.0 * (index - 3),
                0.0,
            ]
        with self.assertRaisesRegex(
            CalibrationError, "usb extrinsic residual too high"
        ):
            self.service._calibrate_camera_extrinsics(
                "usb",
                views["usb"],
                {
                    "quality": {
                        "accepted": True,
                        "rms_px": 0.1,
                        "maximum_rms_px": 1.0,
                    }
                },
                {},
            )

    def test_axis_model_rejects_degenerate_and_wrong_scale_trajectories(self):
        expected_y = 2.0 / 200.0
        views, _ = self._synthetic_motion_views(1.0, expected_y)
        for camera_views in views.values():
            reference_rotation = camera_views[0]["board_to_camera"][:3, :3].copy()
            for view in camera_views:
                view["board_to_camera"][:3, :3] = reference_rotation
        with self.assertRaisesRegex(
            CalibrationError, "Y rotation direction from fixed Pi reference camera is ambiguous"
        ):
            self.service._estimate_motion_model(views)

        views, _ = self._synthetic_motion_views(1.0, expected_y * 1.2)
        with self.assertRaisesRegex(CalibrationError, "validation boundary"):
            self.service._estimate_motion_model(views)

    def test_axis_and_extrinsic_fit_reject_single_pnp_outlier(self):
        expected_y = 2.0 / 200.0
        views, expected_cameras = self._synthetic_motion_views(-1.0, -expected_y)
        outlier = views["pi"][3]["board_to_camera"]
        outlier[:3, 3] += [40, -25, 30]
        outlier[:3, :3] = (
            self.service._rotation_z(math.radians(12)) @ outlier[:3, :3]
        )

        model = self.service._estimate_motion_model(views)
        self.service._motion_model = model
        self.assertAlmostEqual(model["x_mm_per_commanded_mm"], -1.0, places=4)
        self.assertAlmostEqual(
            model["y_radians_per_commanded_mm"], -expected_y, places=6
        )
        result = self.service._calibrate_camera_extrinsics(
            "pi",
            views["pi"],
            {
                "quality": {
                    "accepted": True,
                    "rms_px": 0.1,
                    "maximum_rms_px": 1.0,
                }
            },
            {},
        )
        np.testing.assert_allclose(
            result["camera_to_scanner"], expected_cameras["pi"], atol=1e-4
        )
        self.assertEqual(result["quality"]["robust_pnp_inliers"], 6)

    def test_lidar_geometry_rejects_unobservable_beam_direction(self):
        self.service._move_to = lambda _pose: None
        poses = self.service._trajectory({})
        with self.assertRaisesRegex(CalibrationError, "not observable"):
            self.service._calibrate_lidar(
                poses,
                {},
                {"origin_mm": [0, 0, 0], "direction": [0, 0, 1]},
            )

    def test_lidar_uses_and_persists_validated_usb_carriage_vector_once(self):
        poses = [
            {"x": 195.0, "y": 0.0, "z": 20.0},
            {"x": 195.0, "y": 0.0, "z": 30.0},
            {"x": 195.0, "y": 0.0, "z": 40.0},
        ]
        carriage = np.array([-0.0117, -0.1742, -0.9370])
        calibration = {
            "cameras": {
                "usb": {
                    "carriage_axis": "z",
                    "carriage_direction": carriage.tolist(),
                }
            }
        }
        current_pose = poses[0]
        self.service._move_to = lambda pose: current_pose.update(pose)
        board = np.eye(4)
        board[:3, 2] = [0.0, 1.0, 0.0]
        board[:3, 3] = [0.0, 200.0, 0.0]
        self.service._board_to_scanner = lambda _pose: board.copy()
        self.service._lidar.read_distance_mm = lambda: (
            200.0 - carriage[1] * (current_pose["z"] - 20.0)
        )
        self.service._config["maximum_lidar_rms_mm"] = 0.01

        result = self.service._calibrate_lidar(
            poses,
            calibration,
            {
                "origin_mm": [0.0, 0.0, 0.0],
                "direction": [0.0, 1.0, 0.0],
                "reference_z_mm": 20.0,
            },
        )

        np.testing.assert_allclose(result["carriage_direction"], carriage)
        self.assertAlmostEqual(
            result["carriage_scale_mm_per_commanded_mm"],
            float(np.linalg.norm(carriage)),
        )
        self.assertEqual(
            result["quality"]["carriage_source"],
            "validated_usb_carriage_fit",
        )
        self.assertLess(result["quality"]["rms_mm"], 1e-9)

    @unittest.skipIf(cv2 is None, "OpenCV is required for laser image tests")
    def test_synthetic_checkerboard_lines_recover_true_laser_plane(self):
        self.service._cv = cv2
        self.service._reference_pose = {"x": 195.0, "y": 0.0, "z": 20.0}
        self.service._motion_model.update(
            x_mm_per_commanded_mm=1.0,
            y_radians_per_commanded_mm=0.01,
        )
        self.service._config.update(
            laser_row_stride=1,
            minimum_laser_line_rows=20,
            minimum_laser_points_per_view=20,
        )
        intrinsic = np.array(
            [[300.0, 0.0, 160.0], [0.0, 300.0, 120.0], [0.0, 0.0, 1.0]]
        )
        camera_to_scanner = np.eye(4)
        camera_to_scanner[:3, :3] = BOARD_TO_SCANNER_AT_REFERENCE
        camera_to_scanner[:3, 3] = [-300.0, 0.0, 0.0]
        calibration = {
            "cameras": {
                "pi": {
                    "intrinsic_matrix": intrinsic.tolist(),
                    "distortion_coefficients": [0, 0, 0, 0, 0],
                    "camera_to_scanner": camera_to_scanner.tolist(),
                }
            }
        }
        expected_normal = np.array([-0.2, 1.0, 0.0])
        expected_normal /= np.linalg.norm(expected_normal)
        expected_offset = -10.0 / np.linalg.norm([-0.2, 1.0, 0.0])
        points = []
        poses = [
            {"x": 195.0, "y": 0.0, "z": 20.0},
            {"x": 185.0, "y": 10.0, "z": 20.0},
            {"x": 175.0, "y": 20.0, "z": 20.0},
        ]
        for pose in poses:
            board = self.service._board_to_scanner(pose)
            board_points = checkerboard_points().astype(float)
            scanner_corners = (
                board[:3, :3] @ board_points.T
            ).T + board[:3, 3]
            camera_corners = (
                camera_to_scanner[:3, :3].T
                @ (scanner_corners - camera_to_scanner[:3, 3]).T
            ).T
            image_corners = np.column_stack(
                (
                    intrinsic[0, 0] * camera_corners[:, 0] / camera_corners[:, 2]
                    + intrinsic[0, 2],
                    intrinsic[1, 1] * camera_corners[:, 1] / camera_corners[:, 2]
                    + intrinsic[1, 2],
                )
            )
            tangent = board[:3, 0]
            board_center = board[:3, 3]
            local_u = -(
                float(np.dot(expected_normal, board_center)) + expected_offset
            ) / float(np.dot(expected_normal, tangent))
            endpoints = np.array(
                [
                    board_center + tangent * local_u + board[:3, 1] * vertical
                    for vertical in (-30.0, 30.0)
                ]
            )
            camera_endpoints = (
                camera_to_scanner[:3, :3].T
                @ (endpoints - camera_to_scanner[:3, 3]).T
            ).T
            image_endpoints = np.column_stack(
                (
                    intrinsic[0, 0]
                    * camera_endpoints[:, 0]
                    / camera_endpoints[:, 2]
                    + intrinsic[0, 2],
                    intrinsic[1, 1]
                    * camera_endpoints[:, 1]
                    / camera_endpoints[:, 2]
                    + intrinsic[1, 2],
                )
            )
            ambient = np.full((240, 320, 3), 40, dtype=np.uint8)
            laser = ambient.copy()
            cv2.line(
                laser,
                tuple(np.rint(image_endpoints[0]).astype(int)),
                tuple(np.rint(image_endpoints[1]).astype(int)),
                (0, 0, 255),
                3,
            )
            cv2.line(laser, (5, 0), (25, 239), (0, 0, 255), 8)
            _, ambient_jpeg = cv2.imencode(".jpg", ambient)
            _, laser_jpeg = cv2.imencode(".jpg", laser)
            extracted = self.service._laser_board_points(
                "pi",
                "left",
                ambient_jpeg.tobytes(),
                laser_jpeg.tobytes(),
                pose,
                calibration,
                checkerboard_view={
                    "corners": image_corners.astype(np.float32),
                    "jpeg": b"cached",
                },
            )
            self.assertTrue(extracted["diagnostic"]["accepted"], extracted)
            points.extend(extracted["points"])

        normal, offset, quality = fit_plane_robust(points, minimum_points=30)
        if np.dot(normal, expected_normal) < 0:
            normal, offset = -normal, -offset
        np.testing.assert_allclose(normal, expected_normal, atol=0.01)
        self.assertAlmostEqual(offset, expected_offset, delta=0.5)
        self.assertLess(quality["rms_mm"], 0.5)

    def test_laser_plane_fit_rejects_insufficient_independent_views(self):
        poses = [
            {"x": 195.0, "y": 0.0, "z": 20.0},
            {"x": 185.0, "y": 10.0, "z": 30.0},
            {"x": 175.0, "y": 20.0, "z": 40.0},
        ]
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda _name: b"jpeg"
        pose_index = {pose["x"]: index for index, pose in enumerate(poses)}

        def extract(name, _side, _ambient, _laser, pose, _calibration, **_kwargs):
            accepted = name == "usb" or pose_index[pose["x"]] < 2
            return {
                "points": (
                    [[float(index), float(index % 5), 0.0] for index in range(20)]
                    if accepted
                    else []
                ),
                "diagnostic": {
                    "accepted": accepted,
                    "reason": None if accepted else "no board intersection",
                },
            }

        self.service._laser_board_points = extract
        views = {
            name: [
                {"pose": dict(pose), "corners": np.zeros((66, 2))}
                for pose in poses
            ]
            for name in ("pi", "usb")
        }
        with self.assertRaisesRegex(
            CalibrationError, "insufficient valid Pi-camera checkerboard intersections"
        ):
            self.service._calibrate_lasers(
                poses, {"cameras": {}}, checkerboard_views=views
            )
        status = self.service.status()
        self.assertEqual(len(status["laser_views"]["left"]["pi"]), 3)
        self.assertEqual(len(status["laser_views"]["right"]["usb"]), 3)

    def test_robust_laser_fit_requires_minimum_inliers_in_each_pose(self):
        poses = [
            {"x": 195.0, "y": 0.0, "z": 20.0},
            {"x": 185.0, "y": 10.0, "z": 30.0},
            {"x": 175.0, "y": 20.0, "z": 40.0},
        ]
        first_pose = [
            [float(x), float(y), 0.0]
            for x in range(6)
            for y in range(5)
        ]
        points = first_pose + [[20.0, 20.0, 0.0], [30.0, 30.0, 0.0]]
        pose_indexes = [0] * 30 + [1, 2]

        with self.assertRaisesRegex(
            CalibrationError, "retains only 1 Pi poses"
        ):
            self.service._fit_laser_plane_views(
                points,
                pose_indexes,
                poses,
                minimum_points=30,
                minimum_points_per_view=10,
                minimum_views=3,
                minimum_orientations=3,
            )

    def test_robust_laser_fit_converges_after_more_than_pose_count_passes(self):
        poses = [
            {"x": 195.0, "y": 0.0, "z": 20.0},
            {"x": 185.0, "y": 10.0, "z": 30.0},
            {"x": 175.0, "y": 20.0, "z": 40.0},
        ]
        points = [
            [float(pose_index * 20 + index), float(index % 7), 0.0]
            for pose_index in range(3)
            for index in range(20)
        ]
        pose_indexes = [
            pose_index for pose_index in range(3) for _ in range(20)
        ]
        calls = 0

        def slowly_converging_fit(values, **_kwargs):
            nonlocal calls
            calls += 1
            mask = np.ones(len(values), dtype=bool)
            if calls <= 4:
                mask[-1] = False
            return (
                np.array([0.0, 0.0, 1.0]),
                0.0,
                {
                    "accepted": True,
                    "rms_mm": 0.1,
                    "inliers": int(mask.sum()),
                    "samples": len(values),
                    "plane_spread_ratio": 0.5,
                    "minimum_plane_spread_ratio": 0.001,
                    "inlier_mask": mask.tolist(),
                },
            )

        with mock.patch(
            "software.api.geometric_calibration.fit_plane_robust",
            side_effect=slowly_converging_fit,
        ):
            _, _, quality = self.service._fit_laser_plane_views(
                points,
                pose_indexes,
                poses,
                minimum_points=30,
                minimum_points_per_view=10,
                minimum_views=3,
                minimum_orientations=3,
            )

        self.assertEqual(calls, 5)
        self.assertEqual(quality["views"], 3)

    def test_unverified_usb_laser_path_never_replaces_or_blocks_pi_plane(self):
        poses = [
            {"x": 195.0, "y": 0.0, "z": 20.0},
            {"x": 185.0, "y": 10.0, "z": 30.0},
            {"x": 175.0, "y": 20.0, "z": 40.0},
        ]
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda _name: b"jpeg"
        pose_index = {pose["x"]: index for index, pose in enumerate(poses)}

        def extract(name, _side, _ambient, _laser, pose, _calibration, **_kwargs):
            z = 0.0 if name == "pi" else 10.0
            x = float(pose_index[pose["x"]] * 10)
            return {
                "points": [[x, float(index), z] for index in range(15)],
                "diagnostic": {"accepted": True, "reason": None},
            }

        self.service._laser_board_points = extract
        views = {
            name: [
                {"pose": dict(pose), "corners": np.zeros((66, 2))}
                for pose in poses
            ]
            for name in ("pi", "usb")
        }

        result = self.service._calibrate_lasers(
            poses, {"cameras": {}}, checkerboard_views=views
        )

        for side in ("left", "right"):
            self.assertAlmostEqual(abs(result[side]["normal"][2]), 1.0)
            cross_validation = result[side]["quality"]["usb_cross_validation"]
            self.assertFalse(cross_validation["performed"])
            self.assertIsNone(cross_validation["accepted"])
        status = self.service.status()
        left_controls = status["laser_views"]["left"]["pi"][0][
            "photometric_controls"
        ]
        right_controls = status["laser_views"]["right"]["pi"][0][
            "photometric_controls"
        ]
        self.assertEqual(left_controls, right_controls)
        self.assertTrue(
            all(
                item["photometry_matched"]
                for side in ("left", "right")
                for item in status["laser_views"][side]["pi"]
            )
        )
        for side in ("left", "right"):
            for item in status["laser_views"][side]["pi"]:
                self.assertEqual(
                    item["ambient_photometric_metadata"],
                    item["laser_photometric_metadata"],
                )
                self.assertEqual(
                    item["photometric_controls"],
                    item["laser_photometric_metadata"],
                )

    def test_optional_usb_capture_failure_does_not_abort_pi_plane_fit(self):
        poses = [
            {"x": 195.0, "y": 0.0, "z": 20.0},
            {"x": 185.0, "y": 10.0, "z": 30.0},
            {"x": 175.0, "y": 20.0, "z": 40.0},
        ]
        self.service._move_to = lambda _pose: None
        pose_index = {pose["x"]: index for index, pose in enumerate(poses)}

        def capture(name):
            if name == "usb":
                raise CalibrationError("USB unavailable")
            return b"jpeg"

        def extract(_name, _side, _ambient, _laser, pose, _calibration, **_kwargs):
            x = float(pose_index[pose["x"]] * 10)
            return {
                "points": [[x, float(index), 0.0] for index in range(15)],
                "diagnostic": {"accepted": True, "reason": None},
            }

        self.service._capture = capture
        self.service._laser_board_points = extract
        views = {
            name: [
                {"pose": dict(pose), "corners": np.zeros((66, 2))}
                for pose in poses
            ]
            for name in ("pi", "usb")
        }

        result = self.service._calibrate_lasers(
            poses, {"cameras": {}}, checkerboard_views=views
        )

        self.assertEqual(result["left"]["quality"]["primary_camera"], "pi")
        usb_diagnostics = self.service.status()["laser_views"]["left"]["usb"]
        self.assertEqual(len(usb_diagnostics), 3)
        self.assertTrue(
            all(
                "USB matched photometry/capture unavailable" in item["reason"]
                for item in usb_diagnostics
            )
        )

    def test_unsupported_usb_photometry_is_explicit_and_does_not_block_pi(self):
        poses = [
            {"x": 195.0, "y": 0.0, "z": 20.0},
            {"x": 185.0, "y": 10.0, "z": 30.0},
            {"x": 175.0, "y": 20.0, "z": 40.0},
        ]

        class UnsupportedUsb:
            is_open = True

            @staticmethod
            def capture_jpeg():
                return b"usb"

        self.service._cameras["usb"] = UnsupportedUsb()
        self.service._move_to = lambda _pose: None
        pose_index = {pose["x"]: index for index, pose in enumerate(poses)}
        self.service._capture = lambda name: b"pi" if name == "pi" else b"usb"

        def extract(_name, _side, _ambient, _laser, pose, _calibration, **_kwargs):
            return {
                "points": [
                    [float(pose_index[pose["x"]] * 10), float(index), 0.0]
                    for index in range(15)
                ],
                "diagnostic": {"accepted": True, "reason": None},
            }

        self.service._laser_board_points = extract
        views = {
            name: [
                {"pose": dict(pose), "corners": np.zeros((66, 2))}
                for pose in poses
            ]
            for name in ("pi", "usb")
        }

        result = self.service._calibrate_lasers(
            poses, {"cameras": {}}, checkerboard_views=views
        )

        self.assertEqual(result["left"]["quality"]["primary_camera"], "pi")
        usb_diagnostics = self.service.status()["laser_views"]["left"]["usb"]
        self.assertTrue(
            all(not item["photometry_matched"] for item in usb_diagnostics)
        )
        self.assertTrue(
            all(
                "no verified matched-photometry" in item["reason"]
                for item in usb_diagnostics
            )
        )

    def test_pi_photometry_restores_after_error_and_lasers_are_off(self):
        camera = _TrackedPhotometricCamera()
        self.service._cameras["pi"] = camera
        self.service._move_to = lambda _pose: None

        def capture(name):
            if name == "pi":
                self.assertTrue(camera.photometry_active)
            return b"jpeg"

        self.service._capture = capture
        self.service._laser_board_points = mock.Mock(
            side_effect=CalibrationError("bad line")
        )

        with self.assertRaisesRegex(CalibrationError, "bad line"):
            self.service._calibrate_lasers(
                [{"x": 195, "y": 0, "z": 20}],
                {"cameras": {}},
            )

        self.assertEqual(camera.entries, 1)
        self.assertEqual(camera.restorations, 1)
        self.assertFalse(camera.photometry_active)
        self.assertFalse(any(self.gpio.state.values()))

    def test_pi_photometry_restores_after_cancel_and_lasers_are_off(self):
        def cancel_when_laser_is_on():
            if self.gpio.state["left"]:
                self.service._cancel.set()
                raise CalibrationCancelled("calibration cancelled")

        camera = _TrackedPhotometricCamera(cancel_when_laser_is_on)
        self.service._cameras["pi"] = camera
        self.service._move_to = lambda _pose: None

        with self.assertRaises(CalibrationCancelled):
            self.service._calibrate_lasers(
                [{"x": 195, "y": 0, "z": 20}],
                {"cameras": {}},
            )

        self.assertEqual(camera.restorations, 1)
        self.assertFalse(camera.photometry_active)
        self.assertFalse(any(self.gpio.state.values()))

    def test_unsupported_pi_photometry_blocks_before_laser_enable(self):
        class UnsupportedPi:
            is_open = True

            @staticmethod
            def capture_jpeg():
                return b"pi"

        self.service._cameras["pi"] = UnsupportedPi()
        readiness = self.service.readiness(
            {"lidar": {"origin_mm": [0, 0, 0], "direction": [1, 0, 0]}}
        )

        self.assertFalse(readiness["ready"])
        self.assertTrue(
            any("matched ambient/laser photometry" in item for item in readiness["blockers"])
        )
        with self.assertRaisesRegex(
            CalibrationError, "cannot guarantee matched ambient/laser photometry"
        ):
            self.service._calibrate_lasers(
                [{"x": 195, "y": 0, "z": 20}],
                {"cameras": {}},
            )
        self.assertFalse(any(self.gpio.state.values()))

    def test_missing_cached_pose_is_rejected_without_ambient_redetection(self):
        poses = [
            {"x": 195.0, "y": 0.0, "z": 20.0},
            {"x": 185.0, "y": 10.0, "z": 30.0},
            {"x": 175.0, "y": 20.0, "z": 40.0},
        ]
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda name: (
            b"jpeg" if name == "pi" else (_ for _ in ()).throw(
                CalibrationError("USB unavailable")
            )
        )
        extraction = mock.Mock(
            return_value={
                "points": [[float(x), float(y), 0.0] for x in range(5) for y in range(5)],
                "diagnostic": {"accepted": True, "reason": None},
            }
        )
        self.service._laser_board_points = extraction
        views = {
            "pi": [
                {"pose": dict(pose), "corners": np.zeros((66, 2))}
                for pose in poses[:2]
            ],
            "usb": [],
        }

        with self.assertRaisesRegex(CalibrationError, "insufficient valid Pi-camera"):
            self.service._calibrate_lasers(
                poses, {"cameras": {}}, checkerboard_views=views
            )

        self.assertEqual(extraction.call_count, 4)
        missing = self.service.status()["laser_views"]["left"]["pi"][-1]
        self.assertEqual(
            missing["reason"], "no accepted exact-pose checkerboard view"
        )

    def test_laser_capture_error_always_forces_both_lasers_off(self):
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda _name: b"jpeg"
        self.service._laser_board_points = mock.Mock(side_effect=CalibrationError("bad line"))
        with self.assertRaisesRegex(CalibrationError, "bad line"):
            self.service._calibrate_lasers(
                [{"x": 195, "y": 0, "z": 10}],
                {"cameras": {}},
            )
        self.assertFalse(any(self.gpio.state.values()))
        self.assertIn(("on", "left"), self.gpio.calls)
        self.assertIn(("off", "left"), self.gpio.calls)

    def test_cancel_waits_for_inflight_enable_and_prevents_future_enable(self):
        entered = threading.Event()
        release = threading.Event()
        cancel_returned = threading.Event()

        def delayed_on(side):
            entered.set()
            release.wait(1)
            self.gpio.state[side] = True
            self.gpio.calls.append(("on", side))
            return True

        self.gpio.laser_on = delayed_on
        enable_thread = threading.Thread(
            target=lambda: self.service._laser("left", True)
        )
        enable_thread.start()
        self.assertTrue(entered.wait(0.5))

        def cancel():
            self.service.cancel()
            cancel_returned.set()

        cancel_thread = threading.Thread(target=cancel)
        cancel_thread.start()
        self.assertFalse(cancel_returned.wait(0.05))
        release.set()
        enable_thread.join(0.5)
        cancel_thread.join(0.5)

        self.assertTrue(cancel_returned.is_set())
        self.assertFalse(any(self.gpio.state.values()))
        with self.assertRaises(CalibrationCancelled):
            self.service._laser("right", True)

    def test_laser_plane_capture_selects_fixed_calibration_power_profile(self):
        profile_calls = []

        def calibration_on(side):
            profile_calls.append(side)
            self.gpio.state[side] = True
            return True

        self.gpio.laser_on_for_calibration = calibration_on

        self.service._laser("left", True)
        self.service._laser("left", False)

        self.assertEqual(profile_calls, ["left"])
        self.assertFalse(self.gpio.state["left"])

    def test_commit_boundary_rejects_early_cancel_and_defers_late_cancel(self):
        self.service._cancel.set()
        with self.assertRaises(CalibrationCancelled):
            self.service._begin_commit()
        self.assertFalse(self.service._commit_in_progress)

        self.service._cancel = threading.Event()
        self.service._active = True
        self.service._begin_commit()
        status = self.service.cancel()
        self.assertTrue(self.service._commit_in_progress)
        self.assertFalse(self.service._cancel.is_set())
        self.assertEqual(status["phase"], "persisting")
        self.assertIn("Finishing atomic", status["step"])
        self.assertTrue(
            self.service._finish_commit({"generation": "committed"})
        )
        self.assertTrue(self.service._cancel.is_set())
        self.assertEqual(self.service.status()["phase"], "complete")
        self.assertFalse(self.service.active)

    def test_cancel_during_save_finishes_activation_without_cancelled_outcome(self):
        entered = threading.Event()
        release = threading.Event()
        errors = []
        real_save = self.service._store.save
        activated = []

        def blocking_save(calibration, report):
            entered.set()
            release.wait(1)
            return real_save(calibration, report)

        self.service._store.save = blocking_save
        self.service._on_saved = lambda calibration: activated.append(
            copy.deepcopy(dict(calibration))
        )
        self.service._active = True
        self.service._begin_commit()

        def save_and_activate():
            try:
                self.service._save_and_activate(
                    valid_calibration(), {"generation": "new"}
                )
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=save_and_activate)
        thread.start()
        self.assertTrue(entered.wait(0.5))
        status = self.service.cancel()
        self.assertEqual(status["phase"], "persisting")
        self.assertNotEqual(status["phase"], "cancelled")
        self.assertFalse(self.service._cancel.is_set())
        release.set()
        thread.join(1)

        self.assertEqual(errors, [])
        self.assertEqual(activated, [valid_calibration()])
        self.assertTrue(self.service._finish_commit({"generation": "new"}))
        self.assertEqual(self.service.status()["phase"], "complete")
        self.assertNotEqual(self.service.status()["phase"], "cancelled")
        self.service.cancel()
        self.assertEqual(self.service.status()["phase"], "complete")
        persisted = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["scan_calibration"], valid_calibration())

    def test_activation_failure_restores_persistent_and_runtime_calibration(self):
        previous_disk = {"version": "disk-old"}
        previous_runtime = {"version": "runtime-old"}
        self.config_path.write_text(
            json.dumps({"scan_calibration": previous_disk}), encoding="utf-8"
        )
        before = self.config_path.read_bytes()
        runtime = {"calibration": copy.deepcopy(previous_runtime)}

        def activate(calibration):
            runtime["calibration"] = copy.deepcopy(dict(calibration))
            if calibration.get("checkerboard"):
                raise RuntimeError("activation failed")

        self.service._on_saved = activate
        self.service._get_current_calibration = lambda: copy.deepcopy(
            runtime["calibration"]
        )
        with self.assertRaisesRegex(
            CalibrationError, "previous persistent and runtime calibration restored"
        ):
            self.service._save_and_activate(
                valid_calibration(), {"generation": "new"}
            )

        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertEqual(runtime["calibration"], previous_runtime)
        self.assertFalse(self.service._store.backup_path.exists())
        self.assertFalse(self.service._store.report_path.exists())

    def test_cancellation_during_blocked_hardware_call_is_bounded_and_cleans_up(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked_capture():
            entered.set()
            release.wait(1)
            return b"late"

        self.service._cameras["pi"].capture_jpeg = blocked_capture
        errors = []

        def invoke():
            try:
                self.service._capture("pi")
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=invoke)
        thread.start()
        self.assertTrue(entered.wait(0.5))
        self.service.cancel()
        thread.join(0.5)
        release.set()
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(errors[0], CalibrationCancelled)
        self.assertFalse(any(self.gpio.state.values()))
        self.assertIn(("stop", "all"), self.motor.calls)

    def test_hardware_call_times_out_without_infinite_wait(self):
        started = time.monotonic()
        with self.assertRaisesRegex(CalibrationError, "timed out"):
            self.service._hardware_call("blocked", lambda: time.sleep(1), 0.03)
        self.assertLess(time.monotonic() - started, 0.3)


class AtomicCalibrationStoreTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(exist_ok=True)
        self.path = SCRATCH / f"atomic-{id(self)}.json"
        self.original = {"scan_calibration": {"version": "old"}, "other": 7}
        self.path.write_text(json.dumps(self.original), encoding="utf-8")
        self.store = AtomicCalibrationStore(self.path)

    def tearDown(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)

    def test_atomic_save_report_and_rollback(self):
        calibration = valid_calibration()
        report = {"calibration": calibration, "metrics": {"accepted": True}}
        self.store.save(calibration, report)
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["other"], 7)
        self.assertEqual(persisted["scan_calibration"], calibration)
        self.assertEqual(self.store.report()["metrics"]["accepted"], True)
        restored = self.store.rollback()
        self.assertEqual(restored, {"version": "old"})
        self.assertEqual(json.loads(self.path.read_text())["scan_calibration"], {"version": "old"})

    def test_first_save_creates_runtime_state_without_tracked_config(self):
        self.path.unlink()
        calibration = valid_calibration()

        self.store.save(calibration, {"calibration": calibration})

        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["schema_version"], 1)
        self.assertEqual(persisted["scan_calibration"], calibration)

    def test_validation_failure_never_modifies_config_or_backup(self):
        invalid = valid_calibration()
        invalid["lidar"]["quality"]["accepted"] = False
        before = self.path.read_bytes()
        with self.assertRaises(CalibrationError):
            self.store.save(invalid, {"calibration": invalid})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.store.backup_path.exists())

    def test_persistence_failure_leaves_primary_config_unchanged(self):
        before = self.path.read_bytes()
        with mock.patch(
            "software.api.geometric_calibration.os.replace",
            side_effect=OSError("simulated replace failure"),
        ):
            with self.assertRaisesRegex(OSError, "simulated replace failure"):
                self.store.save(valid_calibration(), {"calibration": valid_calibration()})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_suffix(".json.new").exists())

    def test_sidecar_failures_never_partially_activate_or_persist(self):
        self.store.save(valid_calibration(), {"generation": "old"})
        paths = (self.path, self.store.backup_path, self.store.report_path)
        before = {path: path.read_bytes() for path in paths}
        real_replace = os.replace

        for failure_call in (1, 2, 3):
            with self.subTest(failure_call=failure_call):
                calls = 0

                def fail_once(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == failure_call:
                        raise OSError(f"replace {failure_call} failed")
                    return real_replace(source, destination)

                with (
                    mock.patch(
                        "software.api.geometric_calibration.os.replace",
                        side_effect=fail_once,
                    ),
                    self.assertRaisesRegex(OSError, f"replace {failure_call} failed"),
                ):
                    self.store.save(
                        valid_calibration(), {"generation": f"new-{failure_call}"}
                    )
                for path in paths:
                    self.assertEqual(path.read_bytes(), before[path])

    def test_save_fsyncs_sidecars_before_active_config(self):
        events = []
        real_replace = os.replace

        def replace(source, destination):
            events.append(("replace", Path(destination).name))
            return real_replace(source, destination)

        def fsync_directory(path):
            events.append(("fsync-directory", Path(path).name))

        with (
            mock.patch(
                "software.api.geometric_calibration.os.replace",
                side_effect=replace,
            ),
            mock.patch.object(
                self.store,
                "_fsync_directory",
                side_effect=fsync_directory,
            ),
        ):
            self.store.save(valid_calibration(), {"generation": "new"})

        self.assertEqual(
            events,
            [
                ("replace", self.store.report_path.name),
                ("replace", self.store.backup_path.name),
                ("fsync-directory", self.path.parent.name),
                ("replace", self.path.name),
                ("fsync-directory", self.path.parent.name),
            ],
        )

    def test_active_config_fsync_failure_restores_entire_generation(self):
        self.store.save(valid_calibration(), {"generation": "old"})
        paths = (self.path, self.store.backup_path, self.store.report_path)
        before = {path: path.read_bytes() for path in paths}

        with (
            mock.patch.object(
                self.store,
                "_fsync_directory",
                side_effect=[
                    None,
                    CalibrationError("active directory fsync failed"),
                    None,
                    None,
                ],
            ),
            self.assertRaisesRegex(
                CalibrationError, "active directory fsync failed"
            ),
        ):
            self.store.save(valid_calibration(), {"generation": "new"})

        for path in paths:
            self.assertEqual(path.read_bytes(), before[path])

    def test_directory_fsync_failure_is_explicit_on_supported_platforms(self):
        with (
            mock.patch(
                "software.api.geometric_calibration.os.name", "posix"
            ),
            mock.patch(
                "software.api.geometric_calibration.os.open",
                side_effect=OSError("fsync unavailable"),
            ),
            self.assertRaisesRegex(
                CalibrationError, "failed to fsync calibration directory"
            ),
        ):
            self.store._fsync_directory(self.path.parent)


if __name__ == "__main__":
    unittest.main()
