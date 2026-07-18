from __future__ import annotations

import json
import struct
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from render_all_vehicles import (
    RenderJobResult,
    VehicleJob,
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
        model_tone="black",
        cutout=True,
        perspective=False,
        timeout=420,
        skip_textures=False,
        texture_format="png",
        ytd_mode="all",
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
        self.assertEqual(paths["latest_json"].read_bytes(), paths["history_json"].read_bytes())

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


if __name__ == "__main__":
    unittest.main()
