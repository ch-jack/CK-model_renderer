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

from vehicle_assembly import build_assembly_plan, parse_vehicle_models, vehicle_resource_root


SCRIPT_DIR = Path(__file__).resolve().parent
TOOLS_DIR = SCRIPT_DIR / "tools"
INNER_SCRIPT = SCRIPT_DIR / "blender_render_vehicle.py"
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}


@dataclass(frozen=True)
class VehicleJob:
    model: str
    asset_kind: str
    source_dir: Path
    asset_name: str
    ytd_names: tuple[str, ...]
    shared_ytd_paths: tuple[Path, ...]
    texture_dir: Path
    texture_log_path: Path
    texture_bind_report_path: Path
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


def clean_model_name(asset: Path) -> str:
    name = asset.stem
    lower = name.lower()
    if lower.endswith("_hi") or lower.endswith("+hi"):
        return name[:-3]
    return name


def path_is_generated_output(path: Path) -> bool:
    generated = {"_vehicle_renders", "_assembled_blender", "_work", "_archive_unpacked", "_rpf_unpacked"}
    return any(part.lower() in generated for part in path.parts)


def selected_model_matches(asset: Path, selected_models: set[str] | None) -> bool:
    if not selected_models:
        return True
    return bool({asset.stem.lower(), clean_model_name(asset).lower()} & selected_models)


def scan_vehicle_yfts(root: Path, selected_models: set[str] | None) -> list[Path]:
    all_yfts = [p for p in root.rglob("*.yft") if p.is_file() and not path_is_generated_output(p)]
    by_model: dict[str, dict[str, Path]] = {}
    resource_models: dict[Path, set[str] | None] = {}
    for yft in all_yfts:
        model = clean_model_name(yft)
        if selected_models and model.lower() not in selected_models:
            continue
        source_dir = yft.parent.resolve()
        if source_dir not in resource_models:
            resource_root = vehicle_resource_root(source_dir)
            metadata_models = parse_vehicle_models(resource_root, source_dir) if resource_root else []
            resource_models[source_dir] = {name.lower() for name in metadata_models} if metadata_models else None
        metadata_models = resource_models[source_dir]
        if metadata_models is not None and model.lower() not in metadata_models:
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

def scan_hi_preferred_assets(root: Path, extension: str, selected_models: set[str] | None) -> list[Path]:
    all_assets = [p for p in root.rglob(f"*{extension}") if p.is_file() and not path_is_generated_output(p)]
    by_model: dict[str, dict[str, Path]] = {}
    for asset in all_assets:
        if not selected_model_matches(asset, selected_models):
            continue
        model = clean_model_name(asset)
        slot = by_model.setdefault(model.lower(), {})
        lower = asset.stem.lower()
        if lower.endswith("_hi") or lower.endswith("+hi"):
            slot["hi"] = asset
        else:
            slot["base"] = asset

    result = []
    for item in by_model.values():
        result.append(item.get("hi") or item["base"])
    return sorted(result, key=lambda p: (str(p.parent).lower(), clean_model_name(p).lower()))


def scan_plain_assets(root: Path, extension: str, selected_models: set[str] | None) -> list[Path]:
    result = []
    for asset in root.rglob(f"*{extension}"):
        if asset.is_file() and not path_is_generated_output(asset) and selected_model_matches(asset, selected_models):
            result.append(asset)
    return sorted(result, key=lambda p: (str(p.parent).lower(), clean_model_name(p).lower()))


def parse_asset_types(spec: str) -> set[str]:
    all_types = {"vehicle", "drawable", "drawable-dict", "map"}
    aliases = {
        "all": all_types,
        "vehicles": {"vehicle"},
        "vehicle": {"vehicle"},
        "yft": {"vehicle"},
        "props": {"drawable"},
        "prop": {"drawable"},
        "weapons": {"drawable"},
        "weapon": {"drawable"},
        "accessories": {"drawable"},
        "accessory": {"drawable"},
        "drawable": {"drawable"},
        "ydr": {"drawable"},
        "drawable-dict": {"drawable-dict"},
        "ydd": {"drawable-dict"},
        "maps": {"map"},
        "map": {"map"},
        "ymap": {"map"},
    }
    selected: set[str] = set()
    for raw in spec.split(","):
        key = raw.strip().lower()
        if not key:
            continue
        if key not in aliases:
            raise ValueError(f"Unknown asset type: {raw}")
        selected.update(aliases[key])
    return selected or all_types


def scan_render_assets(root: Path, selected_models: set[str] | None, asset_types: set[str]) -> list[tuple[Path, str]]:
    assets: list[tuple[Path, str]] = []
    if "vehicle" in asset_types:
        assets.extend((path, "vehicle") for path in scan_vehicle_yfts(root, selected_models))
    if "drawable" in asset_types:
        assets.extend((path, "drawable") for path in scan_hi_preferred_assets(root, ".ydr", selected_models))
    if "drawable-dict" in asset_types:
        assets.extend((path, "drawable-dict") for path in scan_plain_assets(root, ".ydd", selected_models))
    if "map" in asset_types:
        assets.extend((path, "map") for path in scan_plain_assets(root, ".ymap", selected_models))
    return assets


def requested_asset_type_keys(spec: str) -> set[str]:
    return {raw.strip().lower() for raw in spec.split(",") if raw.strip()}


def classify_drawable_asset(asset: Path, asset_kind: str, requested_spec: str) -> str:
    if asset_kind != "drawable":
        return asset_kind

    requested = requested_asset_type_keys(requested_spec)
    stem = asset.stem.lower()
    path_text = str(asset).replace("\\", "/").lower()
    if stem.startswith(("w_", "weapon_")) or "/wea" in path_text or "weapon" in path_text:
        return "weapon"
    if any(hint in path_text for hint in ("accessory", "accessories", "shipin", "labubu", "backpack", "bag")):
        return "accessory"
    if "prop" in path_text:
        return "prop"

    semantic = requested & {"weapon", "weapons", "accessory", "accessories", "prop", "props"}
    if len(semantic) == 1:
        value = next(iter(semantic))
        if value.endswith("s"):
            value = value[:-1]
        return value
    return asset_kind


def requested_drawable_filter(spec: str) -> set[str] | None:
    requested = requested_asset_type_keys(spec)
    if requested & {"all", "drawable", "ydr"}:
        return None
    mapping = {
        "weapon": "weapon",
        "weapons": "weapon",
        "accessory": "accessory",
        "accessories": "accessory",
        "prop": "prop",
        "props": "prop",
    }
    selected = {mapping[key] for key in requested if key in mapping}
    return selected or None


def filter_classified_assets(assets: list[tuple[Path, str]], requested_spec: str) -> list[tuple[Path, str]]:
    drawable_filter = requested_drawable_filter(requested_spec)
    if drawable_filter is None:
        return assets
    filtered = []
    for asset, asset_kind in assets:
        if asset.suffix.lower() != ".ydr":
            filtered.append((asset, asset_kind))
        elif asset_kind in drawable_filter:
            filtered.append((asset, asset_kind))
    return filtered


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
    if input_dir.is_file() and input_dir.suffix.lower() in ARCHIVE_EXTENSIONS:
        archives = [input_dir]
    else:
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
    skipped: list[Path] = []
    for batch in chunked(dds_files, 80):
        cmd = [str(texconv), "-ft", "png", "-y", "-o", str(output_dir), *[str(p) for p in batch]]
        result = run_logged(cmd, texconv.parent, log)
        if result.returncode == 0:
            continue

        log.write("texconv batch failed; retrying files one by one and skipping corrupt DDS files.\n")
        log.flush()
        for dds in batch:
            expected_png = output_dir / f"{dds.stem}.png"
            if expected_png.exists():
                continue
            single_cmd = [str(texconv), "-ft", "png", "-y", "-o", str(output_dir), str(dds)]
            single = run_logged(single_cmd, texconv.parent, log)
            if single.returncode != 0:
                skipped.append(dds)
                log.write(f"texconv skipped corrupt/unreadable dds: {dds}\n")
                log.flush()
    if skipped:
        print(f"[textures] skipped corrupt DDS: {len(skipped)}")
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


def write_job_file(args, asset: Path, asset_kind: str, jobs_dir: Path, logs_dir: Path, out_dir: Path) -> VehicleJob:
    model = clean_model_name(asset)
    source_dir = asset.parent.resolve()
    animation_stems = {path.stem.lower() for path in source_dir.glob("*.ycd")}
    accessory_closeup = asset_kind == "accessory" and (
        model.lower() in animation_stems or f"clip@{model.lower()}" in animation_stems
    )
    ytd_names = tuple(matching_ytds(source_dir, model, args.ytd_mode))
    resource_root = vehicle_resource_root(source_dir) if asset_kind == "vehicle" else None
    assembly_plan: dict[str, object] = {"enabled": False, "mode": "none", "parts": []}
    if resource_root is not None:
        base_models = {name.lower() for name in parse_vehicle_models(resource_root, source_dir)}
        if model.lower() in base_models:
            assembly_plan = build_assembly_plan(
                resource_root,
                source_dir,
                model,
                mode=args.vehicle_assembly,
                requested_kit=args.vehicle_kit,
                mod_specs=args.vehicle_mod,
            )
            if assembly_plan.get("enabled"):
                print(
                    f"[assembly] {model}: mode={assembly_plan['mode']} "
                    f"parts={len(assembly_plan['parts'])} kit={assembly_plan.get('kit') or '-'}"
                )
    exposure = args.exposure
    world_strength = args.world_strength
    light_scale = args.light_scale
    yaw = args.yaw
    engine = args.engine
    key_padding = args.key_padding
    if asset_kind == "accessory":
        if args.engine_auto:
            engine = "cycles"
        if args.yaw_auto and accessory_closeup:
            yaw = 155.0
        if args.exposure_auto:
            exposure = -0.30
        if args.world_strength_auto:
            world_strength = 0.20
        if args.light_scale_auto:
            light_scale = 0.62
    elif args.cutout and asset_kind != "vehicle":
        if args.exposure_auto:
            exposure = -0.08
        if args.world_strength_auto:
            world_strength = 0.40
        if args.light_scale_auto:
            light_scale = 0.90
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
    texture_bind_report_path = logs_dir / f"{model}.textures.bind.json"
    job_path = jobs_dir / f"{model}.json"

    data = {
        "model": model,
        "asset_kind": asset_kind,
        "accessory_closeup": accessory_closeup,
        "source_dir": str(source_dir),
        "asset_name": asset.name,
        "yft_name": asset.name,
        "resource_root": str(resource_root) if resource_root else "",
        "vehicle_assembly": assembly_plan,
        "vehicle_attach": args.vehicle_attach,
        "ytd_names": list(ytd_names),
        "shared_ytd_paths": [str(p) for p in args.shared_ytd_paths],
        "texture_dir": str(texture_dir.resolve()),
        "texture_manifest_path": str((texture_dir / "_texture_manifest.json").resolve()),
        "texture_bind_report_path": str(texture_bind_report_path.resolve()),
        "output_path": str(output_path.resolve()),
        "green_screen_path": str(green_screen_path.resolve()) if green_screen_path else "",
        "cutout_path": str(final_output_path.resolve()) if args.cutout else "",
        "green_screen": args.cutout,
        "key_threshold": args.key_threshold,
        "key_padding": key_padding,
        "cutout_width": args.cutout_width,
        "cutout_height": args.cutout_height,
        "width": args.width,
        "height": args.height,
        "samples": args.samples,
        "engine": engine,
        "yaw": yaw,
        "elevation": args.elevation,
        "exposure": exposure,
        "world_strength": world_strength,
        "light_scale": light_scale,
        "floor_clearance": args.floor_gap,
        "model_tone": args.model_tone,
        "special_lights": not args.no_special_lights,
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
        asset_kind,
        source_dir,
        asset.name,
        ytd_names,
        tuple(args.shared_ytd_paths),
        texture_dir,
        texture_log_path,
        texture_bind_report_path,
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


def read_json_object(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_texture_summary_report(jobs: list[VehicleJob], out_dir: Path) -> int:
    items = []
    issue_count = 0
    for job in jobs:
        bind_report = read_json_object(job.texture_bind_report_path)
        manifest = read_json_object(job.texture_dir / "_texture_manifest.json")
        local_textures = manifest.get("local", []) if isinstance(manifest.get("local", []), list) else []
        shared_textures = manifest.get("shared", []) if isinstance(manifest.get("shared", []), list) else []
        missing = bind_report.get("missing", []) if isinstance(bind_report.get("missing", []), list) else []
        item = {
            "model": job.model,
            "asset_kind": job.asset_kind,
            "asset_name": job.asset_name,
            "source_dir": str(job.source_dir),
            "output": str(job.final_output_path),
            "log": str(job.log_path),
            "texture_log": str(job.texture_log_path),
            "texture_bind_report": str(job.texture_bind_report_path),
            "local_texture_count": len(local_textures),
            "shared_texture_count": len(shared_textures),
            "texture_file_count": int(bind_report.get("texture_files", 0) or 0),
            "matched": int(bind_report.get("matched", 0) or 0),
            "missing": sorted(str(name) for name in missing),
            "livery_links": int(bind_report.get("livery_links", 0) or 0),
            "generic_links": int(bind_report.get("generic_links", 0) or 0),
            "part_links": int(bind_report.get("part_links", 0) or 0),
            "status": "ok" if job.final_output_path.exists() else "missing_output",
        }
        item["has_texture_issue"] = bool(item["missing"]) or item["status"] != "ok"
        if item["has_texture_issue"]:
            issue_count += 1
        items.append(item)

    report = {
        "jobs": len(jobs),
        "issues": issue_count,
        "items": items,
    }
    json_path = out_dir / "_texture_report.json"
    txt_path = out_dir / "_texture_report.txt"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["Texture report", f"jobs={len(jobs)} issues={issue_count}", ""]
    for item in items:
        if not item["has_texture_issue"]:
            continue
        lines.append(
            f"{item['model']} [{item['asset_kind']}] matched={item['matched']} "
            f"missing={len(item['missing'])} local={item['local_texture_count']} "
            f"shared={item['shared_texture_count']} generic={item['generic_links']} "
            f"part={item['part_links']} status={item['status']}"
        )
        if item["missing"]:
            preview = ", ".join(item["missing"][:32])
            suffix = "..." if len(item["missing"]) > 32 else ""
            lines.append(f"  missing: {preview}{suffix}")
            if item["local_texture_count"] == 0:
                lines.append("  note: no local YTD textures were extracted; add the correct .ytd next to the model or pass --shared-ytd.")
        lines.append(f"  log: {item['log']}")
        lines.append("")
    if issue_count == 0:
        lines.append("No missing material textures were reported.")
    txt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return issue_count


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
        f"cutout_width={args.cutout_width}",
        f"cutout_height={args.cutout_height}",
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    if result.returncode == 0:
        print(f"Cutout output: {output_path}")
    return result.returncode


def apply_render_defaults(args) -> None:
    if args.engine is None:
        args.engine = "eevee"
    if args.yaw is None:
        args.yaw = 135.0
    if args.exposure is None:
        args.exposure = 0.16 if args.cutout else -0.2
    if args.world_strength is None:
        args.world_strength = 0.56 if args.cutout else 0.45
    if args.light_scale is None:
        args.light_scale = 1.18 if args.cutout else 0.72


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch render GTA/FiveM models and maps with Blender and Sollumz.")
    parser.add_argument("input", nargs="?", help="Folder containing archives or extracted FiveM/GTA resources.")
    parser.add_argument("--out", default="", help="Output folder. Default: <input>/_vehicle_renders")
    parser.add_argument("--workers", type=int, default=default_workers(), help="Parallel Blender process count.")
    parser.add_argument("--model", action="append", default=[], help="Only render this model/asset name. Can be repeated.")
    parser.add_argument("--asset-types", default="all", help="Comma list: all,vehicle,drawable,drawable-dict,map,weapon,prop,accessory.")
    parser.add_argument(
        "--vehicle-assembly",
        "--assembly-mode",
        dest="vehicle_assembly",
        choices=("auto", "showcase", "all", "none"),
        default="auto",
        help="Assemble carcols.meta vehicle parts. Auto uses showcase when a mod kit is present.",
    )
    parser.add_argument("--vehicle-mod", "--assembly-mod", dest="vehicle_mod", action="append", default=[], help="Explicit assembly model or mod type, e.g. VMT_GRILL:2.")
    parser.add_argument("--vehicle-kit", "--assembly-kit", dest="vehicle_kit", default="", help="carcols.meta kitName override.")
    parser.add_argument("--vehicle-attach", "--assembly-attach", dest="vehicle_attach", choices=("preserve", "none"), default="preserve", help="Attach assembled parts to base bones while preserving world transforms.")
    parser.add_argument("--blender", default="", help="Path to blender.exe. Otherwise BLENDER_EXE is used.")
    parser.add_argument("--sollumz", default="", help="Path to Sollumz addon folder if it is not installed.")
    parser.add_argument("--blender-user-config", default="", help="Optional isolated Blender user config folder.")
    parser.add_argument("--blender-user-scripts", default="", help="Optional isolated Blender user scripts folder.")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--engine", choices=("eevee", "cycles"), default=None, help="Render engine. Auto: Cycles for accessories, Eevee for other models.")
    parser.add_argument("--yaw", type=float, default=None, help="Camera yaw. Auto: 155 for accessories, 135 for other models.")
    parser.add_argument("--elevation", type=float, default=26.0)
    parser.add_argument(
        "--exposure",
        type=float,
        default=None,
        help="Render exposure. Default: 0.16 with --cutout, otherwise -0.2.",
    )
    parser.add_argument(
        "--world-strength",
        type=float,
        default=None,
        help="White world light strength. Default: 0.56 with --cutout, otherwise 0.45.",
    )
    parser.add_argument(
        "--light-scale",
        type=float,
        default=None,
        help="Multiplier for all area lights. Default: 1.18 with --cutout, otherwise 0.72.",
    )
    parser.add_argument("--floor-gap", type=float, default=0.12, help="Lower the floor below visible bounds to avoid wheel clipping.")
    parser.add_argument("--cutout", action="store_true", help="Render green screen, a cropped transparent PNG, and a full-frame _alpha PNG.")
    parser.add_argument(
        "--model-tone",
        choices=("gray", "white", "black"),
        default="black",
        help="Model paint tone. All tones change native paint layers without darkening appearance textures.",
    )
    parser.add_argument("--no-special-lights", action="store_true", help="Disable police/self-emissive material emission tuning.")
    parser.add_argument("--key-green", default="", help="Standalone green-screen PNG file/folder to key and crop.")
    parser.add_argument("--key-out", default="", help="Output file/folder for --key-green.")
    parser.add_argument("--key-threshold", type=int, default=70, help="Green key threshold, 0-255.")
    parser.add_argument("--key-padding", type=int, default=0, help="Transparent crop padding. Default 0 matches PNG transparent-pixel trim.")
    parser.add_argument("--cutout-width", type=int, default=0, help="Minimum cropped PNG width. Upscales only; 0 keeps native size.")
    parser.add_argument("--cutout-height", type=int, default=0, help="Minimum cropped PNG height. Upscales only; 0 keeps native size.")
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
    args.engine_auto = args.engine is None
    args.yaw_auto = args.yaw is None
    args.exposure_auto = args.exposure is None
    args.world_strength_auto = args.world_strength is None
    args.light_scale_auto = args.light_scale is None
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
    default_out_root = input_dir.parent if input_dir.is_file() else input_dir
    out_dir = Path(args.out).resolve() if args.out else default_out_root / "_vehicle_renders"
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

    temp_root_obj = None
    if args.keep_work:
        temp_root = Path(tempfile.mkdtemp(prefix="vehicle_renderer_"))
    else:
        temp_root_obj = tempfile.TemporaryDirectory(prefix="vehicle_renderer_")
        temp_root = Path(temp_root_obj.name)

    scan_roots = [] if input_dir.is_file() else [input_dir]
    if not args.no_unpack:
        archive_tool = find_archive_tool(args.archive_tool)
        scan_roots.extend(unpack_archives(input_dir, temp_root, archive_tool))
        rpf_tool = find_rpf_tool(args.rpf_tool)
        if rpf_tool:
            scan_roots.extend(unpack_rpfs(scan_roots, temp_root, rpf_tool))
        elif any(root.rglob("*.rpf") for root in scan_roots):
            print("[rpf] RpfTools.exe not found; skip .rpf unpack")

    selected_models = {m.lower() for m in args.model} if args.model else None
    asset_types = parse_asset_types(args.asset_types)
    assets: list[tuple[Path, str]] = []
    for root in scan_roots:
        assets.extend(scan_render_assets(root, selected_models, asset_types))

    # Deduplicate by type, model name and source file path.
    seen: set[tuple[str, str, str]] = set()
    unique_assets: list[tuple[Path, str]] = []
    for asset, asset_kind in assets:
        key = (asset_kind, clean_model_name(asset).lower(), str(asset.resolve()).lower())
        if key not in seen:
            seen.add(key)
            unique_assets.append((asset, asset_kind))

    if not unique_assets:
        print("No renderable assets found (.yft/.ydr/.ydd/.ymap).")
        return 1

    unique_assets = [
        (asset, classify_drawable_asset(asset, asset_kind, args.asset_types))
        for asset, asset_kind in unique_assets
    ]
    unique_assets = filter_classified_assets(unique_assets, args.asset_types)
    if not unique_assets:
        print(f"No assets matched --asset-types {args.asset_types!r} after classification.")
        return 1

    jobs = [write_job_file(args, asset, asset_kind, jobs_dir, logs_dir, out_dir) for asset, asset_kind in unique_assets]
    workers = max(1, args.workers)

    print(f"Blender: {blender}")
    print(f"Input: {input_dir}")
    print(f"Output: {out_dir}")
    print(f"Assets: {len(jobs)}")
    print(f"Requested asset types: {args.asset_types}")
    print(f"Scanned asset groups: {','.join(sorted(asset_types))}")
    print(f"Model tone: {args.model_tone}")
    print(f"Workers: {workers}")
    if args.shared_ytd_paths:
        print(f"Shared YTD: {len(args.shared_ytd_paths)}")
    if args.cutout:
        print(f"Cutout: exact transparent-pixel trim + full-frame _alpha + green-screen ({args.width}x{args.height})")
        if args.cutout_width or args.cutout_height:
            print(f"Cutout minimum: {max(args.cutout_width, 0)}x{max(args.cutout_height, 0)} (aspect ratio preserved)")

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

    texture_issue_count = 0
    if not args.skip_textures:
        texture_issue_count = write_texture_summary_report(jobs, out_dir)
        texture_report_path = out_dir / "_texture_report.txt"
        if texture_issue_count:
            print(f"[textures] issues={texture_issue_count}; report={texture_report_path}")
        else:
            print(f"[textures] report={texture_report_path}")

    if args.keep_work and temp_root.exists():
        kept = out_dir / "_work"
        if kept.exists():
            shutil.rmtree(kept)
        shutil.move(str(temp_root), str(kept))
        print(f"Work folder kept: {kept}")
    elif temp_root_obj is not None:
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
