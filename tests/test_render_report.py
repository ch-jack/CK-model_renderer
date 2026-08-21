from __future__ import annotations

import contextlib
import io
import json
import struct
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from render_all_vehicles import (
    RenderJobResult,
    VehicleJob,
    build_arg_parser,
    execute_render_jobs,
    load_model_selection,
    matching_ytds,
    scan_render_assets,
    walk_input_files,
    write_model_render_execution_report,
)


def make_args() -> SimpleNamespace:
    return SimpleNamespace(
        model=["demo"],
        asset_types="all",
        workers=2,
        width=1600,
        height=1000,
        samples=64,
        engine="eevee",
        engine_auto=True,
        yaw=135.0,
        yaw_auto=False,
        model_tone="black",
        cutout=True,
        perspective=False,
        timeout=420,
        skip_textures=False,
        texture_format="png",
        ytd_mode="match",
        shared_ytd_paths=(),
        no_unpack=False,
        keep_work=False,
        force=True,
        skip_existing=False,
        sollumz="C:/component/Sollumz",
        ytd_tool_path="C:/component/tools/YtdTools.exe",
        rpf_tool_path="C:/component/tools/RpfTools.exe",
        archive_tool_path="C:/component/tools/7z.exe",
    )


class ModelRenderReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out_dir = self.root / "_vehicle_renders"
        self.out_dir.mkdir()
        self.started_at = datetime.now().astimezone()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_writes_history_and_latest_reports_with_model_artifacts(self) -> None:
        source_dir = self.root / "resource" / "stream"
        source_dir.mkdir(parents=True)
        (source_dir / "demo.yft").write_bytes(b"asset")

        jobs_dir = self.out_dir / "_jobs"
        logs_dir = self.out_dir / "_logs"
        texture_dir = self.out_dir / "_textures" / "demo"
        jobs_dir.mkdir()
        logs_dir.mkdir()
        texture_dir.mkdir(parents=True)
        final_png = self.out_dir / "demo.png"
        alpha_png = self.out_dir / "_alpha" / "demo.png"
        final_png.write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 2, 3)
        )
        alpha_png.parent.mkdir()
        alpha_png.write_bytes(final_png.read_bytes())

        job_path = jobs_dir / "demo.json"
        bind_report = logs_dir / "demo.textures.bind.json"
        texture_log = logs_dir / "demo.textures.log"
        blender_log = logs_dir / "demo.log"
        job_path.write_text(
            json.dumps(
                {
                    "green_screen_path": "",
                    "blend_path": str(jobs_dir / "demo.blend"),
                    "vehicle_assembly": {"enabled": False, "mode": "none"},
                }
            ),
            encoding="utf-8",
        )
        bind_report.write_text(
            json.dumps({"matched": 2, "missing": ["paint_d"]}),
            encoding="utf-8",
        )
        (texture_dir / "_texture_manifest.json").write_text(
            json.dumps({"local": ["paint_n"], "shared": []}),
            encoding="utf-8",
        )
        texture_log.write_text("", encoding="utf-8")
        blender_log.write_text("finished", encoding="utf-8")

        job = VehicleJob(
            model="demo",
            asset_kind="vehicle",
            source_dir=source_dir,
            asset_name="demo.yft",
            ytd_names=("demo.ytd",),
            shared_ytd_paths=(),
            texture_dir=texture_dir,
            texture_log_path=texture_log,
            texture_bind_report_path=bind_report,
            output_path=alpha_png,
            final_output_path=final_png,
            log_path=blender_log,
            job_path=job_path,
        )
        result = RenderJobResult(job, "success", 0, 1.25, "")
        paths = write_model_render_execution_report(
            out_dir=self.out_dir,
            run_id="testrun",
            started_at=self.started_at,
            started_monotonic=time.monotonic(),
            input_path=source_dir.parent,
            args=make_args(),
            blender=Path("C:/Blender/blender.exe"),
            blender_label="Blender 5.1.0",
            jobs=[job],
            results=[result],
            operations=[
                {
                    "operation": "input_scan",
                    "status": "completed",
                    "scan_roots": 1,
                    "discovered": 1,
                    "jobs": 1,
                }
            ],
        )

        for path in paths.values():
            self.assertTrue(path.is_file(), path)
        payload = json.loads(paths["latest_json"].read_text(encoding="utf-8"))
        self.assertEqual(payload["report_type"], "model_render_execution")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["summary"]["rendered"], 1)
        self.assertEqual(payload["summary"]["texture_issues"], 1)
        self.assertEqual(payload["results"][0]["outputs"]["final_png"]["width"], 2)
        self.assertEqual(payload["results"][0]["outputs"]["final_png"]["height"], 3)
        markdown = paths["latest_markdown"].read_text(encoding="utf-8")
        self.assertIn("\u6a21\u578b\u81ea\u52a8\u622a\u56fe\u6267\u884c\u62a5\u544a", markdown)
        gallery = paths["latest_html"].read_text(encoding="utf-8")
        self.assertIn("<table>", gallery)
        self.assertIn("<img", gallery)
        self.assertIn("demo.png", gallery)
        self.assertEqual(paths["latest_json"].read_bytes(), paths["history_json"].read_bytes())
        self.assertEqual(paths["latest_html"].read_bytes(), paths["history_html"].read_bytes())

    def test_writes_failure_report_when_scan_creates_no_jobs(self) -> None:
        paths = write_model_render_execution_report(
            out_dir=self.out_dir,
            run_id="emptyrun",
            started_at=self.started_at,
            started_monotonic=time.monotonic(),
            input_path=self.root,
            args=make_args(),
            blender=Path("C:/Blender/blender.exe"),
            blender_label="Blender 5.1.0",
            jobs=[],
            results=[],
            operations=[
                {
                    "operation": "input_scan",
                    "status": "failed",
                    "scan_roots": 1,
                    "discovered": 0,
                    "jobs": 0,
                }
            ],
            status_override="failed",
            error="No renderable assets found.",
        )
        payload = json.loads(paths["latest_json"].read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["summary"]["jobs"], 0)
        self.assertEqual(payload["error"], "No renderable assets found.")


class YtdMatchingTests(unittest.TestCase):
    def test_match_mode_uses_exact_and_delimited_companions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "bear2.ytd",
                "bear2_hi.ytd",
                "bear2_sign_1.ytd",
                "bear20.ytd",
                "bear21.ytd",
                "shared.ytd",
            ):
                (root / name).write_bytes(b"ytd")

            self.assertEqual(
                matching_ytds(root, "bear2", "match"),
                ["bear2.ytd", "bear2_hi.ytd", "bear2_sign_1.ytd", "shared.ytd"],
            )

    def test_match_mode_falls_back_when_folder_has_one_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "resource_textures.ytd").write_bytes(b"ytd")
            self.assertEqual(matching_ytds(root, "different_model", "match"), ["resource_textures.ytd"])

    def test_parser_defaults_to_match_mode(self) -> None:
        args = build_arg_parser().parse_args(["C:/models"])
        self.assertEqual(args.ytd_mode, "match")


class ModelSelectionTests(unittest.TestCase):
    def test_model_file_combines_deduplicates_and_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            selection_file = Path(temp_dir) / "models.txt"
            selection_file.write_text("Alpha\n beta \nALPHA\n\n模型三\n", encoding="utf-8-sig")

            selected = load_model_selection(["CLI", "Beta"], str(selection_file))

            self.assertEqual(selected, ["CLI", "Beta", "Alpha", "模型三"])

    def test_model_file_missing_returns_clear_error(self) -> None:
        missing = Path(tempfile.gettempdir()) / f"missing-models-{time.time_ns()}.txt"
        with self.assertRaisesRegex(ValueError, "Unable to read model selection file"):
            load_model_selection([], str(missing))

    def test_parser_accepts_model_file(self) -> None:
        args = build_arg_parser().parse_args(["C:/models", "--model-file", "C:/temp/models.txt"])
        self.assertEqual(args.model_file, "C:/temp/models.txt")


class LargeBatchProgressTests(unittest.TestCase):
    def test_vehicle_metadata_keeps_base_vehicle_and_hides_parts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resource = Path(temp_dir) / "unified_pack"
            stream = resource / "stream"
            stream.mkdir(parents=True)
            (resource / "vehicles.meta").write_text(
                "<CVehicleModelInfo__InitDataList><InitDatas><Item>"
                "<modelName>base_car</modelName>"
                "</Item></InitDatas></CVehicleModelInfo__InitDataList>",
                encoding="utf-8",
            )
            (stream / "base_car.yft").write_bytes(b"")
            (stream / "base_car_dryclutch_1.yft").write_bytes(b"")

            assets = scan_render_assets(Path(temp_dir), None, {"vehicle"})

            self.assertEqual([(path.stem, kind) for path, kind in assets], [("base_car", "vehicle")])

    def test_walk_input_files_prunes_generated_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "stream").mkdir()
            (root / "stream" / "base_car.yft").write_bytes(b"")
            (root / "_vehicle_renders").mkdir()
            (root / "_vehicle_renders" / "old_output.yft").write_bytes(b"")
            (root / "_temp").mkdir()
            (root / "_temp" / "temporary_part.yft").write_bytes(b"")

            names = [path.name for path in walk_input_files(root)]

            self.assertEqual(names, ["base_car.yft"])

    def test_scan_reports_progress_for_ten_thousand_candidates(self) -> None:
        fake_paths = [Path("C:/pack/stream") / f"car_{index:05d}.yft" for index in range(10_000)]
        output = io.StringIO()
        with mock.patch("render_all_vehicles.walk_input_files", return_value=iter(fake_paths)):
            with contextlib.redirect_stdout(output):
                assets = scan_render_assets(Path("C:/pack"), None, {"vehicle"})

        self.assertEqual(len(assets), 10_000)
        self.assertIn("phase=assets scanned=1000 candidates=1000", output.getvalue())
        self.assertIn(
            "phase=assets status=done scanned=10000 candidates=10000 selected=10000",
            output.getvalue(),
        )

    def test_render_scheduler_logs_started_models_and_limits_concurrency(self) -> None:
        jobs = [SimpleNamespace(model=f"car_{index:03d}") for index in range(24)]
        args = SimpleNamespace(workers=4)
        lock = threading.Lock()
        active = 0
        max_active = 0

        def fake_runner(blender, job, runner_args):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return RenderJobResult(job, "success", 0, 0.01, "")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            results, failures = execute_render_jobs(Path("C:/Blender/blender.exe"), jobs, args, fake_runner)

        self.assertEqual(len(results), len(jobs))
        self.assertEqual(failures, [])
        self.assertGreaterEqual(max_active, 2)
        self.assertLessEqual(max_active, args.workers)
        self.assertIn("[start] car_000 1/24", output.getvalue())
        self.assertIn("24/24", output.getvalue())


if __name__ == "__main__":
    unittest.main()
