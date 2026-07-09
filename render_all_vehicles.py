from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
TOOLS_DIR = SCRIPT_DIR / "tools"
INNER_SCRIPT = SCRIPT_DIR / "blender_render_vehicle.py"
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}


@dataclass(frozen=True)
class VehicleJob:
    model: str
    source_dir: Path
    yft_name: str
    ytd_names: tuple[str, ...]
    shared_ytd_paths: tuple[Path, ...]
    texture_dir: Path
    texture_log_path: Path
    output_path: Path
    final_output_path: Path
    log_path: Path
    job_path: Path


def find_blender(blender_arg: str | None) -> Path:
    candidates: list[Path] = []
    if blender_arg:
        candidates.append(Path(blender_arg))
    for env_name in ("BLENDER_EXE", "BLENDER_PATH"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value))

    candidates.extend(
        [
            Path(r"D:\Blender 5.0\blender.exe"),
            Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"),
            Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"),
            Path(r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe"),
            Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
            Path(r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"),
        ]
    )

    where_blender = shutil.which("blender")
    if where_blender:
        candidates.append(Path(where_blender))

    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError("Blender not found. Pass --blender or set BLENDER_EXE.")


def default_workers() -> int:
    cpu = os.cpu_count() or 4
    return max(1, min(4, cpu // 2 or 1))


def clean_model_name(yft: Path) -> str:
    name = yft.stem
    if name.lower().endswith("_hi"):
        return name[:-3]
    return name


def scan_vehicle_yfts(root: Path, selected_models: set[str] | None) -> list[Path]:
    all_yfts = [p for p in root.rglob("*.yft") if p.is_file()]
    by_model: dict[str, dict[str, Path]] = {}
    for yft in all_yfts:
        model = clean_model_name(yft)
        if selected_models and model.lower() not in selected_models:
            continue
        slot = by_model.setdefault(model.lower(), {})
        if yft.stem.lower().endswith("_hi"):
            slot["hi"] = yft
        else:
            slot["base"] = yft

    result = []
    for item in by_model.values():
        result.append(item.get("hi") or item["base"])
    return sorted(result, key=lambda p: (str(p.parent).lower(), clean_model_name(p).lower()))


def matching_ytds(source_dir: Path, model: str, mode: str) -> list[str]:
    ytds = sorted(p for p in source_dir.glob("*.ytd") if p.is_file())
    if mode == "none":
        return []
    if mode == "all":
        return [p.name for p in ytds]

    prefixes = {
        model.lower(),
        f"{model.lower()}+hi",
        f"{model.lower()}_hi",
        "vehshare",
        "vehicle",
        "vehicles",
        "shared",
    }
    out = []
    for ytd in ytds:
        stem = ytd.stem.lower()
        if stem in prefixes or stem.startswith(model.lower()):
            out.append(ytd.name)
    return out


def dedupe_paths(paths: list[Path]) -> list[Path]:
    out = []
    seen = set()
    for path in paths:
        resolved = path.resolve()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(resolved)
    return out


def collect_shared_ytds(input_dir: Path, specs: list[str], auto_shared: bool) -> list[Path]:
    shared: list[Path] = []
    for spec in specs:
        path = Path(spec).resolve()
        if path.is_file() and path.suffix.lower() == ".ytd":
            shared.append(path)
        elif path.is_dir():
            shared.extend(p for p in path.rglob("*.ytd") if p.is_file())
        else:
            print(f"[textures] shared ytd path not found: {path}")

    if auto_shared:
        for root in (input_dir, SCRIPT_DIR, SCRIPT_DIR / "shared_ytd"):
            if root.is_dir():
                shared.extend(p for p in root.rglob("vehshare*.ytd") if p.is_file())

    return dedupe_paths(shared)


def find_rpf_tool(rpf_tool_arg: str | None) -> Path | None:
    candidates = []
    if rpf_tool_arg:
        candidates.append(Path(rpf_tool_arg))
    candidates.extend(
        [
            TOOLS_DIR / "RpfTools.exe",
            Path.cwd() / "[Tool]" / "autorpf" / "newdll" / "RpfTools.exe",
            Path.cwd() / "[Tool]" / "autorpf" / "RpfTools" / "RpfTools" / "bin" / "Debug" / "RpfTools.exe",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def find_support_tool(tool_arg: str | None, filename: str) -> Path | None:
    candidates = []
    if tool_arg:
        candidates.append(Path(tool_arg))
    candidates.extend(
        [
            TOOLS_DIR / filename,
            SCRIPT_DIR.parent / "autorpf" / "newdll" / filename,
            Path.cwd() / "[Tool]" / "autorpf" / "newdll" / filename,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def find_archive_tool(tool_arg: str | None) -> Path | None:
    candidates = []
    if tool_arg:
        candidates.append(Path(tool_arg))
    candidates.extend(
        [
            TOOLS_DIR / "7z.exe",
            Path(r"C:\Program Files\7-Zip\7z.exe"),
            Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
        ]
    )
    where_7z = shutil.which("7z") or shutil.which("7z.exe")
    if where_7z:
        candidates.append(Path(where_7z))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def clear_texture_dir(texture_dir: Path, textures_root: Path) -> None:
    texture_dir = texture_dir.resolve()
    textures_root = textures_root.resolve()
    if textures_root not in texture_dir.parents:
        raise RuntimeError(f"Refusing to clear texture dir outside {textures_root}: {texture_dir}")
    if texture_dir.exists():
        def onerror(func, path, exc_info):
            try:
                os.chmod(path, 0o700)
                func(path)
            except Exception:
                raise exc_info[1]

        for attempt in range(5):
            try:
                shutil.rmtree(texture_dir, onerror=onerror)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.4)


def texture_manifest_key(path: Path) -> str:
    return path.stem.strip().lower()


def chunked(items: list[Path], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def run_logged(cmd: list[str], cwd: Path, log) -> subprocess.CompletedProcess:
    log.write(" ".join(cmd) + "\n")
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout:
        log.write(result.stdout)
    if result.stderr:
        log.write(result.stderr)
    log.write(f"\nexit={result.returncode}\n\n")
    log.flush()
    return result


def safe_folder_name(path: Path) -> str:
    name = path.stem or path.name
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)[:80] or "archive"


def unpack_archives(input_dir: Path, work_dir: Path, archive_tool: Path | None) -> list[Path]:
    roots: list[Path] = []
    archives = [p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in ARCHIVE_EXTENSIONS]
    if not archives:
        return roots
    if not archive_tool:
        print("[archive] 7z.exe not found; skip .zip/.rar/.7z unpack")
        return roots

    unpack_root = work_dir / "archive_unpacked"
    unpack_root.mkdir(parents=True, exist_ok=True)
    queue = sorted(archives)
    seen: set[str] = set()
    index = 0
    while queue:
        archive = queue.pop(0)
        key = str(archive.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        index += 1
        out_dir = unpack_root / f"{index:04d}_{safe_folder_name(archive)}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "_archive_unpack.log"
        cmd = [str(archive_tool), "x", "-y", f"-o{out_dir}", str(archive)]
        print(f"[archive] unpack {archive}")
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            result = run_logged(cmd, archive_tool.parent, log)
        if result.returncode != 0:
            print(f"[archive] failed {archive} rc={result.returncode}")
            continue
        roots.append(out_dir)
        queue.extend(
            p for p in out_dir.rglob("*") if p.is_file() and p.suffix.lower() in ARCHIVE_EXTENSIONS
        )
    return roots


def convert_dds_to_png(dds_files: list[Path], output_dir: Path, texconv: Path, log) -> int:
    if not dds_files:
        return 0
    before = {p.name.lower() for p in output_dir.glob("*.png")}
    for batch in chunked(dds_files, 80):
        cmd = [str(texconv), "-ft", "png", "-y", "-o", str(output_dir), *[str(p) for p in batch]]
        result = run_logged(cmd, texconv.parent, log)
        if result.returncode != 0:
            raise RuntimeError(f"texconv failed rc={result.returncode}")
    after = {p.name.lower() for p in output_dir.glob("*.png")}
    return len(after - before)


def extract_textures_for_job(job: VehicleJob, args) -> None:
    if args.skip_textures or (not job.ytd_names and not job.shared_ytd_paths):
        return
    if job.output_path.exists() and args.skip_existing and not args.force:
        return
    if not args.ytd_tool_path:
        print(f"[textures] YtdTools.exe not found, skip {job.model}")
        return

    if args.force:
        clear_texture_dir(job.texture_dir, args.textures_root)
    job.texture_dir.mkdir(parents=True, exist_ok=True)

    existing = list(job.texture_dir.glob("*.png")) or list(job.texture_dir.glob("*.dds"))
    if existing and not args.force:
        return

    with job.texture_log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(f"model={job.model}\n")
        log.write(f"source_dir={job.source_dir}\n")
        log.write(f"texture_dir={job.texture_dir}\n\n")

        total_dds = 0
        total_png = 0
        manifest: dict[str, list[str]] = {"local": [], "shared": []}
        ytd_sources = [("shared", path) for path in job.shared_ytd_paths]
        ytd_sources.extend(("local", job.source_dir / ytd_name) for ytd_name in job.ytd_names)

        for kind, ytd_path in ytd_sources:
            if not ytd_path.exists():
                log.write(f"missing ytd: {ytd_path}\n")
                continue

            with tempfile.TemporaryDirectory(prefix=f"{job.model}_ytd_") as tmp:
                tmp_dir = Path(tmp)
                tmp_ytd = tmp_dir / ytd_path.name
                dds_dir = tmp_dir / "dds"
                dds_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ytd_path, tmp_ytd)

                cmd = [
                    str(args.ytd_tool_path),
                    str(tmp_ytd),
                    str(dds_dir) + os.sep,
                    "0",
                    "0",
                    "0",
                    "0",
                ]
                result = run_logged(cmd, args.ytd_tool_path.parent, log)
                if result.returncode != 0:
                    raise RuntimeError(f"YtdTools failed for {ytd_path.name} rc={result.returncode}")

                dds_files = sorted(dds_dir.glob("*.dds"))
                total_dds += len(dds_files)
                manifest.setdefault(kind, []).extend(texture_manifest_key(dds) for dds in dds_files)
                log.write(f"{kind} {ytd_path} textures={len(dds_files)}\n")
                if args.texture_format == "png" and args.texconv_path:
                    total_png += convert_dds_to_png(dds_files, job.texture_dir, args.texconv_path, log)
                else:
                    for dds in dds_files:
                        shutil.copy2(dds, job.texture_dir / dds.name)

        log.write(f"dds={total_dds}\npng={total_png}\n")
        manifest = {key: sorted(set(value)) for key, value in manifest.items()}
        (job.texture_dir / "_texture_manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
        if total_dds == 0:
            print(f"[textures] no textures extracted for {job.model}")


def unpack_rpfs(scan_roots: list[Path], work_dir: Path, rpf_tool: Path) -> list[Path]:
    roots = []
    rpf_files = []
    seen_rpfs: set[str] = set()
    for root in scan_roots:
        for rpf in root.rglob("*.rpf"):
            key = str(rpf.resolve()).lower()
            if rpf.is_file() and key not in seen_rpfs:
                seen_rpfs.add(key)
                rpf_files.append(rpf)
    rpf_files = sorted(rpf_files)
    if not rpf_files:
        return roots

    unpack_root = work_dir / "rpf_unpacked"
    unpack_root.mkdir(parents=True, exist_ok=True)

    for idx, rpf in enumerate(rpf_files, start=1):
        out_dir = unpack_root / f"{idx:04d}_{rpf.stem}"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [str(rpf_tool), str(rpf), rpf.name, str(out_dir) + os.sep]
        print(f"[rpf] unpack {rpf}")
        result = subprocess.run(
            cmd,
            cwd=str(rpf_tool.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        (out_dir / "_rpf_unpack.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        if result.returncode != 0:
            print(f"[rpf] failed {rpf} rc={result.returncode}")
        roots.append(out_dir)
    return roots


def write_job_file(args, yft: Path, jobs_dir: Path, logs_dir: Path, out_dir: Path) -> VehicleJob:
    model = clean_model_name(yft)
    source_dir = yft.parent.resolve()
    ytd_names = tuple(matching_ytds(source_dir, model, args.ytd_mode))
    if args.cutout:
        output_path = out_dir / "_alpha" / f"{model}.png"
        green_screen_path = out_dir / "_greenscreen" / f"{model}.png"
        final_output_path = out_dir / f"{model}.png"
    else:
        output_path = out_dir / f"{model}.png"
        green_screen_path = None
        final_output_path = output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if green_screen_path:
        green_screen_path.parent.mkdir(parents=True, exist_ok=True)
    final_output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{model}.log"
    texture_dir = out_dir / "_textures" / model
    texture_log_path = logs_dir / f"{model}.textures.log"
    job_path = jobs_dir / f"{model}.json"

    data = {
        "model": model,
        "source_dir": str(source_dir),
        "yft_name": yft.name,
        "ytd_names": list(ytd_names),
        "shared_ytd_paths": [str(p) for p in args.shared_ytd_paths],
        "texture_dir": str(texture_dir.resolve()),
        "texture_manifest_path": str((texture_dir / "_texture_manifest.json").resolve()),
        "output_path": str(output_path.resolve()),
        "green_screen_path": str(green_screen_path.resolve()) if green_screen_path else "",
        "cutout_path": str(final_output_path.resolve()) if args.cutout else "",
        "green_screen": args.cutout,
        "key_threshold": args.key_threshold,
        "key_padding": args.key_padding,
        "width": args.width,
        "height": args.height,
        "samples": args.samples,
        "engine": args.engine,
        "yaw": args.yaw,
        "elevation": args.elevation,
        "exposure": args.exposure,
        "world_strength": args.world_strength,
        "light_scale": args.light_scale,
        "floor_clearance": args.floor_gap,
        "orthographic": not args.perspective,
        "sollumz_path": str(Path(args.sollumz).resolve()) if args.sollumz else "",
        "blender_user_config": str(Path(args.blender_user_config).resolve()) if args.blender_user_config else "",
        "blender_user_scripts": str(Path(args.blender_user_scripts).resolve()) if args.blender_user_scripts else "",
        "save_blend": args.save_blend,
        "blend_path": str((jobs_dir / f"{model}.blend").resolve()),
    }
    job_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return VehicleJob(
        model,
        source_dir,
        yft.name,
        ytd_names,
        tuple(args.shared_ytd_paths),
        texture_dir,
        texture_log_path,
        output_path,
        final_output_path,
        log_path,
        job_path,
    )


def run_blender_job(blender: Path, job: VehicleJob, args) -> tuple[str, int, float]:
    started = time.time()
    if job.final_output_path.exists() and args.skip_existing and not args.force:
        return job.model, 0, 0.0
    if args.force and job.output_path.exists():
        job.output_path.unlink()
    if args.force and job.final_output_path.exists() and job.final_output_path != job.output_path:
        job.final_output_path.unlink()

    try:
        extract_textures_for_job(job, args)
    except Exception as exc:
        job.texture_log_path.parent.mkdir(parents=True, exist_ok=True)
        with job.texture_log_path.open("a", encoding="utf-8", errors="replace") as log:
            log.write(f"\nTEXTURE EXTRACT FAILED: {exc}\n")
        return job.model, 3, time.time() - started

    env = os.environ.copy()
    if args.sollumz:
        env["SOLLUMZ_ADDON_PATH"] = str(Path(args.sollumz).resolve())
    if args.blender_user_config:
        env["BLENDER_USER_CONFIG"] = str(Path(args.blender_user_config).resolve())
    if args.blender_user_scripts:
        env["BLENDER_USER_SCRIPTS"] = str(Path(args.blender_user_scripts).resolve())

    cmd = [
        str(blender),
        "--background",
        "--python",
        str(INNER_SCRIPT),
        "--",
        f"job={job.job_path}",
    ]

    with job.log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(" ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(SCRIPT_DIR),
            env=env,
            text=True,
        )
        try:
            rc = proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = 124
            log.write(f"\nTIMEOUT after {args.timeout}s\n")

    elapsed = time.time() - started
    if rc == 0 and not job.final_output_path.exists():
        rc = 2
    return job.model, rc, elapsed


def run_green_key(blender: Path, args) -> int:
    input_path = Path(args.key_green).resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if args.key_out:
        output_path = Path(args.key_out).resolve()
    elif input_path.is_dir():
        output_path = input_path.parent / f"{input_path.name}_cutouts"
    else:
        output_path = input_path.with_name(f"{input_path.stem}_cutout.png")

    cmd = [
        str(blender),
        "--background",
        "--python",
        str(INNER_SCRIPT),
        "--",
        f"key_input={input_path}",
        f"key_output={output_path}",
        f"key_threshold={args.key_threshold}",
        f"key_padding={args.key_padding}",
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    if result.returncode == 0:
        print(f"Cutout output: {output_path}")
    return result.returncode


def apply_render_defaults(args) -> None:
    if args.exposure is None:
        args.exposure = 0.75 if args.cutout else -0.2
    if args.world_strength is None:
        args.world_strength = 0.78 if args.cutout else 0.45
    if args.light_scale is None:
        args.light_scale = 1.85 if args.cutout else 0.72


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch render GTA/FiveM vehicles with Blender and Sollumz.")
    parser.add_argument("input", nargs="?", help="Folder containing archives or extracted FiveM vehicle resources.")
    parser.add_argument("--out", default="", help="Output folder. Default: <input>/_vehicle_renders")
    parser.add_argument("--workers", type=int, default=default_workers(), help="Parallel Blender process count.")
    parser.add_argument("--model", action="append", default=[], help="Only render this model name. Can be repeated.")
    parser.add_argument("--blender", default="", help="Path to blender.exe. Otherwise BLENDER_EXE is used.")
    parser.add_argument("--sollumz", default="", help="Path to Sollumz addon folder if it is not installed.")
    parser.add_argument("--blender-user-config", default="", help="Optional isolated Blender user config folder.")
    parser.add_argument("--blender-user-scripts", default="", help="Optional isolated Blender user scripts folder.")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--engine", choices=("eevee", "cycles"), default="eevee")
    parser.add_argument("--yaw", type=float, default=135.0)
    parser.add_argument("--elevation", type=float, default=26.0)
    parser.add_argument(
        "--exposure",
        type=float,
        default=None,
        help="Render exposure. Default: 0.75 with --cutout, otherwise -0.2.",
    )
    parser.add_argument(
        "--world-strength",
        type=float,
        default=None,
        help="White world light strength. Default: 0.78 with --cutout, otherwise 0.45.",
    )
    parser.add_argument(
        "--light-scale",
        type=float,
        default=None,
        help="Multiplier for all area lights. Default: 1.85 with --cutout, otherwise 0.72.",
    )
    parser.add_argument("--floor-gap", type=float, default=0.12, help="Lower the floor below visible bounds to avoid wheel clipping.")
    parser.add_argument("--cutout", action="store_true", help="Render green screen and output transparent cropped PNG.")
    parser.add_argument("--key-green", default="", help="Standalone green-screen PNG file/folder to key and crop.")
    parser.add_argument("--key-out", default="", help="Output file/folder for --key-green.")
    parser.add_argument("--key-threshold", type=int, default=70, help="Green key threshold, 0-255.")
    parser.add_argument("--key-padding", type=int, default=12, help="Transparent cutout padding in pixels.")
    parser.add_argument("--perspective", action="store_true", help="Use perspective camera instead of orthographic.")
    parser.add_argument("--ytd-mode", choices=("all", "match", "none"), default="all")
    parser.add_argument("--shared-ytd", action="append", default=[], help="Extra shared .ytd file or folder, for example exported vehshare.ytd.")
    parser.add_argument("--no-auto-shared-ytd", action="store_true", help="Do not auto-scan input/shared_ytd for vehshare*.ytd.")
    parser.add_argument("--skip-textures", action="store_true", help="Do not extract or bind .ytd textures.")
    parser.add_argument("--texture-format", choices=("png", "dds"), default="png", help="Texture format passed to Blender.")
    parser.add_argument("--ytd-tool", default="", help="Path to CodeWalker-based YtdTools.exe.")
    parser.add_argument("--texconv", default="", help="Path to texconv.exe for DDS to PNG conversion.")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--save-blend", action="store_true", help="Save per-model .blend files into _jobs.")
    parser.add_argument("--no-unpack", action="store_true", help="Do not auto-unpack .zip/.rar/.7z/.rpf input files.")
    parser.add_argument("--unpack-rpf", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rpf-tool", default="", help="Path to RpfTools.exe.")
    parser.add_argument("--archive-tool", default="", help="Path to 7z.exe for .zip/.rar/.7z.")
    parser.add_argument("--keep-work", action="store_true", help="Keep temporary RPF extraction folder.")
    return parser


def main(argv: list[str]) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    apply_render_defaults(args)
    if args.key_green:
        blender = find_blender(args.blender)
        return run_green_key(blender, args)
    if not args.input:
        parser.error("input is required unless --key-green is used")

    input_dir = Path(args.input).resolve()
    if not input_dir.exists():
        raise FileNotFoundError(input_dir)
    if not INNER_SCRIPT.exists():
        raise FileNotFoundError(INNER_SCRIPT)

    local_sollumz = SCRIPT_DIR / "Sollumz"
    if not args.sollumz and (local_sollumz / "__init__.py").exists():
        args.sollumz = str(local_sollumz)

    local_config = SCRIPT_DIR / "blender_user_config"
    if not args.blender_user_config and local_config.exists():
        args.blender_user_config = str(local_config)

    local_scripts = SCRIPT_DIR / "blender_user_scripts"
    if not args.blender_user_scripts and local_scripts.exists():
        args.blender_user_scripts = str(local_scripts)

    blender = find_blender(args.blender)
    out_dir = Path(args.out).resolve() if args.out else input_dir / "_vehicle_renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = out_dir / "_jobs"
    logs_dir = out_dir / "_logs"
    textures_root = out_dir / "_textures"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    textures_root.mkdir(parents=True, exist_ok=True)
    args.textures_root = textures_root.resolve()

    args.ytd_tool_path = None
    args.texconv_path = None
    if not args.skip_textures:
        args.ytd_tool_path = find_support_tool(args.ytd_tool, "YtdTools.exe")
        args.texconv_path = find_support_tool(args.texconv, "texconv.exe")
        if args.texture_format == "png" and not args.texconv_path:
            print("[textures] texconv.exe not found; falling back to DDS files")
            args.texture_format = "dds"
    args.shared_ytd_paths = tuple(
        collect_shared_ytds(input_dir, args.shared_ytd, not args.no_auto_shared_ytd)
        if not args.skip_textures
        else []
    )

    temp_root_obj = tempfile.TemporaryDirectory(prefix="vehicle_renderer_")
    temp_root = Path(temp_root_obj.name)

    scan_roots = [input_dir]
    if not args.no_unpack:
        archive_tool = find_archive_tool(args.archive_tool)
        scan_roots.extend(unpack_archives(input_dir, temp_root, archive_tool))
        rpf_tool = find_rpf_tool(args.rpf_tool)
        if rpf_tool:
            scan_roots.extend(unpack_rpfs(scan_roots, temp_root, rpf_tool))
        elif any(root.rglob("*.rpf") for root in scan_roots):
            print("[rpf] RpfTools.exe not found; skip .rpf unpack")

    selected_models = {m.lower() for m in args.model} if args.model else None
    yfts: list[Path] = []
    for root in scan_roots:
        yfts.extend(scan_vehicle_yfts(root, selected_models))

    # Deduplicate by model name and source file path.
    seen: set[tuple[str, str]] = set()
    unique_yfts = []
    for yft in yfts:
        key = (clean_model_name(yft).lower(), str(yft.resolve()).lower())
        if key not in seen:
            seen.add(key)
            unique_yfts.append(yft)

    if not unique_yfts:
        print("No .yft vehicles found.")
        return 1

    jobs = [write_job_file(args, yft, jobs_dir, logs_dir, out_dir) for yft in unique_yfts]
    workers = max(1, args.workers)

    print(f"Blender: {blender}")
    print(f"Input: {input_dir}")
    print(f"Output: {out_dir}")
    print(f"Vehicles: {len(jobs)}")
    print(f"Workers: {workers}")
    if args.shared_ytd_paths:
        print(f"Shared YTD: {len(args.shared_ytd_paths)}")
    if args.cutout:
        print("Cutout: green-screen key + crop")

    failures: list[tuple[str, int]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_blender_job, blender, job, args) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            model, rc, elapsed = future.result()
            if rc == 0:
                print(f"[ok] {model} {elapsed:.1f}s")
            else:
                print(f"[fail] {model} rc={rc} {elapsed:.1f}s")
                failures.append((model, rc))

    if args.keep_work and temp_root.exists():
        kept = out_dir / "_work"
        if kept.exists():
            shutil.rmtree(kept)
        shutil.move(str(temp_root), str(kept))
        print(f"Work folder kept: {kept}")
    else:
        temp_root_obj.cleanup()

    print(f"Done. OK={len(jobs) - len(failures)} FAIL={len(failures)}")
    if failures:
        print(f"Logs: {logs_dir}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise
