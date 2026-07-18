from __future__ import annotations

import argparse
import concurrent.futures
import errno
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vehicle_assembly import build_assembly_plan, parse_vehicle_models, vehicle_resource_root


SCRIPT_DIR = Path(__file__).resolve().parent
TOOLS_DIR = SCRIPT_DIR / "tools"
INNER_SCRIPT = SCRIPT_DIR / "blender_render_vehicle.py"
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}
MIN_BLENDER_VERSION = (4, 2, 0)
MIN_FREE_DISK_BYTES = 1024**3


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


@dataclass(frozen=True)
class RenderJobResult:
    job: VehicleJob
    status: str
    return_code: int
    elapsed_seconds: float
    message: str


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


def require_supported_blender(blender: Path) -> str:
    try:
        result = subprocess.run(
            [str(blender), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动 Blender: {blender} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Blender 版本检测超时: {blender}") from exc

    first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    match = re.search(r"\bBlender\s+(\d+)\.(\d+)(?:\.(\d+))?", first_line, re.IGNORECASE)
    if result.returncode != 0 or not match:
        detail = first_line or f"退出码 {result.returncode}"
        raise RuntimeError(f"无法识别 Blender 版本: {blender} ({detail})")

    version = tuple(int(value or 0) for value in match.groups())
    if version < MIN_BLENDER_VERSION:
        raise RuntimeError(
            f"Blender {version[0]}.{version[1]}.{version[2]} 不受支持；"
            "请安装 Blender 4.2 或更高版本（推荐 5.1）。"
        )
    return first_line


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(max(0, value))
    unit = units[0]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            break
        size /= 1024.0
    return f"{size:.1f} {unit}"


def existing_disk_path(path: Path) -> Path:
    candidate = path.resolve(strict=False)
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise FileNotFoundError(path)
        candidate = parent
    return candidate


def disk_space_text(path: Path) -> str:
    existing = existing_disk_path(path)
    usage = shutil.disk_usage(existing)
    volume = existing.anchor or str(existing)
    return f"{volume} 剩余 {format_bytes(usage.free)}"


def require_free_disk_space(path: Path, label: str, minimum: int = MIN_FREE_DISK_BYTES) -> None:
    existing = existing_disk_path(path)
    usage = shutil.disk_usage(existing)
    print(f"[disk] {label}: {disk_space_text(existing)}", flush=True)
    if usage.free < minimum:
        raise RuntimeError(
            f"磁盘空间不足: {existing.anchor or existing} 仅剩 {format_bytes(usage.free)}，"
            f"至少需要 {format_bytes(minimum)}。请清理{label}所在磁盘后重试。"
        )


def is_no_space_error(exc: BaseException) -> bool:
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) == 112:
            return True
    message = str(exc).lower()
    return "no space left on device" in message or "not enough space on the disk" in message


def texture_failure_message(exc: BaseException, job: VehicleJob) -> str:
    if not is_no_space_error(exc):
        return str(exc)

    locations = []
    for label, path in (
        ("输出目录", job.texture_dir),
        ("临时目录", job.texture_dir.parent.parent / "_temp"),
    ):
        try:
            locations.append(f"{label} {disk_space_text(path)}")
        except OSError:
            locations.append(f"{label} {path}")
    detail = "；".join(locations)
    return f"磁盘空间不足，无法提取纹理。{detail}。请至少释放 1 GB 后重试。"


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
    generated = {"_vehicle_renders", "_assembled_blender", "_temp", "_work", "_archive_unpacked", "_rpf_unpacked"}
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


def append_operation(records: list[dict[str, object]] | None, operation: str, status: str, **details) -> None:
    if records is None:
        return
    item: dict[str, object] = {"operation": operation, "status": status}
    item.update(details)
    records.append(item)


def unpack_archives(
    input_dir: Path, work_dir: Path, archive_tool: Path | None, operations: list[dict[str, object]] | None = None
) -> list[Path]:
    roots: list[Path] = []
    if input_dir.is_file() and input_dir.suffix.lower() in ARCHIVE_EXTENSIONS:
        archives = [input_dir]
    else:
        archives = [p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in ARCHIVE_EXTENSIONS]
    if not archives:
        append_operation(
            operations,
            "archive_unpack",
            "not_needed",
            detected=0,
            note="输入中未发现 ZIP、RAR 或 7Z 压缩包。",
        )
        return roots
    if not archive_tool:
        print("[archive] 7z.exe not found; skip .zip/.rar/.7z unpack")
        append_operation(
            operations,
            "archive_unpack",
            "skipped",
            detected=len(archives),
            sources=[str(path) for path in sorted(archives)],
            reason="7z.exe 不可用，未执行压缩包解包。",
        )
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
            append_operation(
                operations,
                "archive_unpack",
                "failed",
                source=str(archive),
                output=str(out_dir),
                log=str(log_path),
                return_code=result.returncode,
            )
            print(f"[archive] failed {archive} rc={result.returncode}")
            continue
        append_operation(
            operations, "archive_unpack", "success", source=str(archive), output=str(out_dir), log=str(log_path)
        )
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

            with tempfile.TemporaryDirectory(prefix=f"{job.model}_ytd_", dir=args.temp_root) as tmp:
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


def unpack_rpfs(
    scan_roots: list[Path], work_dir: Path, rpf_tool: Path, operations: list[dict[str, object]] | None = None
) -> list[Path]:
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
        append_operation(
            operations,
            "rpf_unpack",
            "not_needed",
            detected=0,
            note="扫描范围内未发现 RPF。",
        )
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
            append_operation(
                operations,
                "rpf_unpack",
                "failed",
                source=str(rpf),
                output=str(out_dir),
                log=str(out_dir / "_rpf_unpack.log"),
                return_code=result.returncode,
            )
            print(f"[rpf] failed {rpf} rc={result.returncode}")
        else:
            append_operation(
                operations, "rpf_unpack", "success", source=str(rpf), output=str(out_dir), log=str(out_dir / "_rpf_unpack.log")
            )
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


def read_blender_error_summary(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    error_pattern = re.compile(
        r"(?:error|exception|failed|failure|cancelled|missing|memoryerror|runtimeerror|"
        r"attributeerror|typeerror|valueerror|keyerror|filenotfounderror|oserror|permissionerror)",
        re.IGNORECASE,
    )
    for raw_line in reversed(lines):
        line = " ".join(raw_line.strip().split())
        if not line or line.lower().startswith(("blender quit", "blender ")):
            continue
        if error_pattern.search(line) or "[DECOMPRESS_FAILED]" in line:
            return line[:600]
    return ""

def run_blender_job(blender: Path, job: VehicleJob, args) -> RenderJobResult:
    started = time.time()
    if job.final_output_path.exists() and args.skip_existing and not args.force:
        return RenderJobResult(job, "skipped_existing", 0, 0.0, "已有截图，按 --skip-existing 跳过。")
    if args.force and job.output_path.exists():
        job.output_path.unlink()
    if args.force and job.final_output_path.exists() and job.final_output_path != job.output_path:
        job.final_output_path.unlink()

    try:
        extract_textures_for_job(job, args)
    except Exception as exc:
        message = texture_failure_message(exc, job)
        try:
            job.texture_log_path.parent.mkdir(parents=True, exist_ok=True)
            with job.texture_log_path.open("a", encoding="utf-8", errors="replace") as log:
                log.write(f"\nTEXTURE EXTRACT FAILED: {message}\n")
        except OSError:
            pass
        print(f"[textures] {job.model} 失败: {message}", flush=True)
        return RenderJobResult(job, "failed", 3, time.time() - started, message)

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
    if rc == 0:
        message = ""
    else:
        detail = read_blender_error_summary(job.log_path)
        if job.output_path.exists() and not job.final_output_path.exists():
            stage = "透明图后处理失败"
        elif not job.output_path.exists():
            stage = "Blender 未生成渲染图"
        else:
            stage = "Blender 执行失败"
        if detail:
            stage = f"{stage}: {detail}"
            print(f"[blender-error] {job.model}: {detail}", flush=True)
        message = f"{stage}；完整日志: {job.log_path}"
    status = "success" if rc == 0 else "failed"
    return RenderJobResult(job, status, rc, elapsed, message)


def read_json_object(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def read_texture_error(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    marker = "TEXTURE EXTRACT FAILED:"
    index = text.rfind(marker)
    if index < 0:
        return ""
    return text[index + len(marker) :].strip().splitlines()[0]


def write_texture_summary_report(jobs: list[VehicleJob], out_dir: Path) -> int:
    items = []
    issue_count = 0
    for job in jobs:
        bind_report = read_json_object(job.texture_bind_report_path)
        manifest = read_json_object(job.texture_dir / "_texture_manifest.json")
        texture_error = read_texture_error(job.texture_log_path)
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
            "texture_error": texture_error,
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
        item["has_texture_issue"] = bool(item["missing"]) or bool(texture_error) or item["status"] != "ok"
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
        if item["texture_error"]:
            lines.append(f"  error: {item['texture_error']}")
            lines.append(f"  texture log: {item['texture_log']}")
        else:
            lines.append(f"  log: {item['log']}")
        lines.append("")
    if issue_count == 0:
        lines.append("No missing material textures were reported.")
    txt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return issue_count


def read_png_artifact(path: Path) -> dict[str, object]:
    artifact: dict[str, object] = {"path": str(path), "exists": path.is_file()}
    if not artifact["exists"]:
        return artifact
    try:
        artifact["bytes"] = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(24)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and header[12:16] == b"IHDR":
            width, height = struct.unpack(">II", header[16:24])
            artifact["width"] = width
            artifact["height"] = height
    except OSError as exc:
        artifact["metadata_error"] = str(exc)
    return artifact


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def build_model_result_record(result: RenderJobResult, textures_enabled: bool = True) -> dict[str, object]:
    job = result.job
    job_data = read_json_object(job.job_path)
    bind_report = read_json_object(job.texture_bind_report_path) if textures_enabled else {}
    manifest = read_json_object(job.texture_dir / "_texture_manifest.json") if textures_enabled else {}
    missing = bind_report.get("missing", [])
    if not isinstance(missing, list):
        missing = []
    local_textures = manifest.get("local", [])
    shared_textures = manifest.get("shared", [])
    if not isinstance(local_textures, list):
        local_textures = []
    if not isinstance(shared_textures, list):
        shared_textures = []
    texture_error = read_texture_error(job.texture_log_path) if textures_enabled else ""
    green_value = str(job_data.get("green_screen_path", ""))
    blend_value = str(job_data.get("blend_path", ""))
    green_screen_path = Path(green_value) if green_value else None
    blend_path = Path(blend_value) if blend_value else None
    warnings: list[str] = []
    if missing:
        warnings.append(f"缺少 {len(missing)} 个材质纹理。")
    if texture_error:
        warnings.append(f"贴图提取失败：{texture_error}")
    if result.status == "failed" and result.message:
        warnings.append(result.message)
    if not job.final_output_path.is_file() and result.status != "skipped_existing":
        warnings.append("最终裁边 PNG 不存在。")

    return {
        "model": job.model,
        "asset_type": job.asset_kind,
        "source": str(job.source_dir / job.asset_name),
        "status": result.status,
        "return_code": result.return_code,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "message": result.message,
        "outputs": {
            "final_png": read_png_artifact(job.final_output_path),
            "full_frame_alpha_png": read_png_artifact(job.output_path)
            if job.output_path != job.final_output_path
            else None,
            "green_screen_png": read_png_artifact(green_screen_path) if green_screen_path else None,
            "blend_file": {
                "path": str(blend_path),
                "exists": bool(blend_path and blend_path.is_file()),
            }
            if blend_path
            else None,
        },
        "textures": {
            "status": "processed" if textures_enabled else "skipped",
            "requested_ytd": list(job.ytd_names),
            "shared_ytd": [str(path) for path in job.shared_ytd_paths],
            "local_texture_count": len(local_textures),
            "shared_texture_count": len(shared_textures),
            "bound_texture_count": int(bind_report.get("matched", 0) or 0),
            "missing": sorted(str(name) for name in missing),
            "error": texture_error,
            "bind_report": str(job.texture_bind_report_path),
            "extraction_log": str(job.texture_log_path),
        },
        "vehicle_assembly": job_data.get("vehicle_assembly", {}),
        "job_file": str(job.job_path),
        "blender_log": str(job.log_path),
        "warnings": warnings,
    }


def markdown_cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def describe_model_operation(item: dict[str, object]) -> str:
    operation = str(item.get("operation", ""))
    status = str(item.get("status", ""))
    status_text = {
        "success": "成功",
        "completed": "完成",
        "failed": "失败",
        "skipped": "跳过",
        "not_needed": "无需执行",
        "cleaned": "已清理",
        "kept": "已保留",
    }.get(status, status or "已记录")
    if operation == "archive_unpack":
        source = item.get("source")
        if source:
            return f"压缩包解包（{status_text}）：{source}"
        detail = item.get("reason") or item.get("note") or "已检查输入。"
        return f"压缩包检查（{status_text}）：{detail}"
    if operation == "rpf_unpack":
        source = item.get("source")
        if source:
            return f"RPF 解包（{status_text}）：{source}"
        detail = item.get("reason") or item.get("note") or "已检查扫描范围。"
        return f"RPF 检查（{status_text}）：{detail}"
    if operation == "input_scan":
        return (
            f"模型扫描（{status_text}）：扫描 {item.get('scan_roots', 0)} 个根目录，"
            f"发现 {item.get('discovered', 0)} 个候选，创建 {item.get('jobs', 0)} 个渲染任务。"
        )
    if operation == "blender_render":
        return (
            f"Blender 渲染（{status_text}）：成功 {item.get('success', 0)}，"
            f"跳过 {item.get('skipped', 0)}，失败 {item.get('failed', 0)}。"
        )
    if operation == "texture_report":
        return f"贴图提取与绑定（{status_text}）：{item.get('issues', 0)} 个模型需要注意。"
    if operation == "temp_workspace":
        return f"临时工作目录（{status_text}）：{item.get('path', '')}"
    return f"{operation or '操作'}（{status_text}）"


def build_model_render_markdown(report: dict[str, object]) -> str:
    summary = report["summary"]
    status_text = {
        "success": "全部成功",
        "partial_success": "部分成功",
        "failed": "失败",
    }.get(str(report["status"]), str(report["status"]))
    tick = chr(96)
    lines = [
        "# 模型自动截图执行报告",
        "",
        f"- 本次编号：{tick}{report['run_id']}{tick}",
        f"- 开始时间：{report['started_at']}",
        f"- 完成时间：{report['finished_at']}",
        f"- 总耗时：{report['duration_seconds']:.1f} 秒",
        f"- 执行结论：**{status_text}**",
        f"- 输入：{tick}{report['input']['path']}{tick}",
        f"- 输出：{tick}{report['output']['path']}{tick}",
        "",
    ]
    if report.get("error"):
        lines.extend(["## 执行错误", "", str(report["error"]), ""])

    lines.extend(
        [
            "## 结果汇总",
            "",
            "| 发现模型 | 成功渲染 | 已有结果跳过 | 失败 | 贴图有问题 |",
            "| ---: | ---: | ---: | ---: | ---: |",
            (
                f"| {summary['jobs']} | {summary['rendered']} | {summary['skipped']} | "
                f"{summary['failed']} | {summary['texture_issues']} |"
            ),
            "",
            "## 本次执行了什么",
            "",
        ]
    )
    operations = report.get("operations", [])
    if operations:
        for index, item in enumerate(operations, start=1):
            lines.append(f"{index}. {describe_model_operation(item)}")
    else:
        lines.append("未进入模型扫描或渲染阶段。")
    lines.extend(
        [
            "",
            "## 逐模型结果",
            "",
            "| 模型 | 类型 | 结果 | 耗时 | 最终 PNG | 贴图情况 | 说明 |",
            "| --- | --- | --- | ---: | --- | --- | --- |",
        ]
    )
    result_labels = {"success": "成功", "skipped_existing": "跳过", "failed": "失败"}
    results = report.get("results", [])
    if results:
        for item in results:
            final_png = item["outputs"]["final_png"]
            texture_data = item["textures"]
            if texture_data["missing"]:
                texture_text = f"缺少 {len(texture_data['missing'])} 项"
            elif texture_data["error"]:
                texture_text = "提取失败"
            else:
                texture_text = "正常"
            output_text = Path(str(final_png["path"])).name if final_png.get("exists") else "未生成"
            lines.append(
                "| {model} | {asset_type} | {status} | {elapsed:.1f}s | {output} | {texture} | {message} |".format(
                    model=markdown_cell(item["model"]),
                    asset_type=markdown_cell(item["asset_type"]),
                    status=markdown_cell(result_labels.get(item["status"], item["status"])),
                    elapsed=float(item["elapsed_seconds"]),
                    output=markdown_cell(output_text),
                    texture=markdown_cell(texture_text),
                    message=markdown_cell(item["message"]),
                )
            )
    else:
        lines.append("| - | - | 未创建任务 | 0.0s | - | - | - |")

    attention_results = [item for item in results if item["warnings"]]
    if attention_results:
        lines.extend(["", "## 失败与警告明细", ""])
        for item in attention_results:
            result_text = result_labels.get(item["status"], item["status"])
            lines.append(f"### {item['model']}（{result_text}）")
            lines.append("")
            lines.append(f"- 源文件：{tick}{item['source']}{tick}")
            lines.append(f"- Blender 日志：{tick}{item['blender_log']}{tick}")
            for warning in item["warnings"]:
                lines.append(f"- {warning}")
            missing = item["textures"]["missing"]
            if missing:
                preview = ", ".join(missing[:50])
                suffix = f"（另有 {len(missing) - 50} 项）" if len(missing) > 50 else ""
                lines.append(f"- 缺失纹理：{preview}{suffix}")
            lines.append("")

    lines.append("")
    lines.extend(["## 环境与参数", "", tick * 3 + "json"])
    lines.extend(
        json.dumps(
            {"environment": report["environment"], "request": report["request"]},
            ensure_ascii=False,
            indent=2,
        ).splitlines()
    )
    lines.extend([tick * 3, "", "## 注意事项", ""])
    for note in report["notes"]:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## 报告文件",
            "",
            f"- 本次 Markdown：{tick}{report['reports']['history_markdown']}{tick}",
            f"- 本次 JSON：{tick}{report['reports']['history_json']}{tick}",
            f"- 最新报告：{tick}{report['reports']['latest_markdown']}{tick}",
            "",
        ]
    )
    return "\n".join(lines)


def write_model_render_execution_report(
    *,
    out_dir: Path,
    run_id: str,
    started_at: datetime,
    started_monotonic: float,
    input_path: Path,
    args,
    blender: Path | None,
    blender_label: str,
    jobs: list[VehicleJob],
    results: list[RenderJobResult],
    operations: list[dict[str, object]],
    status_override: str = "",
    error: str = "",
) -> dict[str, Path]:
    finished_at = datetime.now().astimezone()
    reports_dir = out_dir / "_reports"
    report_stem = f"model-render-{started_at.strftime('%Y%m%d-%H%M%S')}-{run_id}"
    paths = {
        "history_markdown": reports_dir / f"{report_stem}.md",
        "history_json": reports_dir / f"{report_stem}.json",
        "latest_markdown": out_dir / "_render_report.md",
        "latest_json": out_dir / "_render_report.json",
    }

    results_by_job = {id(result.job): result for result in results}
    ordered_results = []
    for job in jobs:
        result = results_by_job.get(id(job))
        if result is None:
            result = RenderJobResult(job, "failed", 1, 0.0, "任务未返回执行结果，请检查主进程日志。")
        ordered_results.append(result)
    textures_enabled = not bool(getattr(args, "skip_textures", False))
    result_records = [
        build_model_result_record(result, textures_enabled=textures_enabled) for result in ordered_results
    ]
    rendered = sum(item["status"] == "success" for item in result_records)
    skipped = sum(item["status"] == "skipped_existing" for item in result_records)
    failed = sum(item["status"] == "failed" for item in result_records)
    texture_issues = sum(
        bool(item["textures"]["missing"] or item["textures"]["error"]) for item in result_records
    )
    preprocess_incomplete = any(
        item.get("operation") in {"archive_unpack", "rpf_unpack"}
        and (
            item.get("status") == "failed"
            or (item.get("status") == "skipped" and int(item.get("detected", 0) or 0) > 0)
        )
        for item in operations
    )
    if status_override:
        status = status_override
    elif failed == 0 and jobs and not preprocess_incomplete:
        status = "success"
    elif rendered or skipped:
        status = "partial_success"
    else:
        status = "failed"

    notes = [
        "渲染器只读取输入资源；截图、日志、任务文件和报告均写入输出目录。",
        "“成功”表示最终 PNG 已生成；画面、构图和材质是否符合预期仍建议人工抽查。",
        "每次报告永久保存在 _reports；输出根目录的 _render_report.md/.json 会更新为最近一次。",
    ]
    if getattr(args, "force", False):
        notes.append("本次启用了强制渲染；同名旧截图会在任务开始前被替换。")
    if getattr(args, "skip_existing", False):
        notes.append("本次允许跳过已有截图；报告把这些模型单独标记为“跳过”，不计作新渲染。")
    if texture_issues:
        notes.append("贴图缺失不一定导致 Blender 失败，但可能出现白模、错色或材质不完整，请按逐模型明细补齐 YTD。")
    if failed:
        notes.append("失败模型没有被当作成功；优先查看逐模型 Blender 日志中的最后一条异常。")
    if getattr(args, "keep_work", False):
        notes.append("本次保留了 _work 中间目录，可用于复查压缩包、RPF 和贴图转换过程；确认无用后可手动删除。")
    if getattr(args, "cutout", False):
        notes.append("根目录 PNG 是裁边透明图；_alpha 是完整画布透明图；_greenscreen 是绿幕预览。")
    if any(item.get("status") in {"failed", "skipped"} for item in operations):
        notes.append("预处理存在失败或跳过项；未成功解包的压缩包/RPF 不会进入模型扫描。")

    report: dict[str, object] = {
        "report_type": "model_render_execution",
        "report_version": 1,
        "run_id": run_id,
        "status": status,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": round(max(0.0, time.monotonic() - started_monotonic), 3),
        "input": {
            "path": str(input_path),
            "kind": "file" if input_path.is_file() else "directory",
        },
        "output": {"path": str(out_dir)},
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "python_executable": sys.executable,
            "blender": str(blender) if blender else "",
            "blender_version": blender_label,
            "sollumz": str(getattr(args, "sollumz", "") or ""),
            "ytd_tool": str(getattr(args, "ytd_tool_path", "") or ""),
            "rpf_tool": str(getattr(args, "rpf_tool_path", "") or ""),
            "archive_tool": str(getattr(args, "archive_tool_path", "") or ""),
        },
        "request": {
            "selected_models": list(getattr(args, "model", []) or []),
            "asset_types": str(getattr(args, "asset_types", "")),
            "workers": max(1, int(getattr(args, "workers", 1))),
            "render": {
                "width": int(getattr(args, "width", 0)),
                "height": int(getattr(args, "height", 0)),
                "samples": int(getattr(args, "samples", 0)),
                "engine": str(getattr(args, "engine", "")),
                "engine_auto": bool(getattr(args, "engine_auto", False)),
                "model_tone": str(getattr(args, "model_tone", "")),
                "cutout": bool(getattr(args, "cutout", False)),
                "perspective": bool(getattr(args, "perspective", False)),
                "timeout_seconds": int(getattr(args, "timeout", 0)),
            },
            "textures": {
                "enabled": not bool(getattr(args, "skip_textures", False)),
                "format": str(getattr(args, "texture_format", "")),
                "ytd_mode": str(getattr(args, "ytd_mode", "")),
                "shared_ytd": [str(path) for path in getattr(args, "shared_ytd_paths", ())],
            },
            "input_processing": {
                "auto_unpack": not bool(getattr(args, "no_unpack", False)),
                "keep_work": bool(getattr(args, "keep_work", False)),
                "force": bool(getattr(args, "force", False)),
                "skip_existing": bool(getattr(args, "skip_existing", False)),
            },
        },
        "summary": {
            "jobs": len(jobs),
            "rendered": rendered,
            "skipped": skipped,
            "failed": failed,
            "texture_issues": texture_issues,
        },
        "operations": operations,
        "results": result_records,
        "artifacts": {
            "logs_directory": str(out_dir / "_logs"),
            "jobs_directory": str(out_dir / "_jobs"),
            "texture_report_json": str(out_dir / "_texture_report.json")
            if (out_dir / "_texture_report.json").is_file()
            else "",
            "texture_report_text": str(out_dir / "_texture_report.txt")
            if (out_dir / "_texture_report.txt").is_file()
            else "",
        },
        "notes": notes,
        "error": error,
        "reports": {name: str(path) for name, path in paths.items()},
    }
    json_text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    markdown_text = build_model_render_markdown(report)
    atomic_write_text(paths["history_json"], json_text)
    atomic_write_text(paths["history_markdown"], markdown_text)
    atomic_write_text(paths["latest_json"], json_text)
    atomic_write_text(paths["latest_markdown"], markdown_text)
    return paths


def emit_model_render_execution_report(**kwargs) -> dict[str, Path] | None:
    try:
        paths = write_model_render_execution_report(**kwargs)
    except Exception as exc:
        print(f"[report-error] 无法生成模型执行报告: {exc}", file=sys.stderr, flush=True)
        return None
    print(f"[report] markdown={paths['latest_markdown']}", flush=True)
    print(f"[report] json={paths['latest_json']}", flush=True)
    print(f"[report] history={paths['history_markdown']}", flush=True)
    return paths


def cleanup_run_workspace(
    temp_root: Path,
    temp_root_obj: tempfile.TemporaryDirectory | None,
    temp_parent: Path,
    keep_work: bool,
    operations: list[dict[str, object]],
) -> None:
    if keep_work and temp_root.exists():
        print(f"Work folder kept: {temp_root}")
        append_operation(operations, "temp_workspace", "kept", path=str(temp_root))
        return
    if temp_root_obj is None:
        return
    try:
        temp_root_obj.cleanup()
        try:
            temp_parent.rmdir()
        except OSError:
            pass
        append_operation(operations, "temp_workspace", "cleaned", path=str(temp_root))
    except OSError as exc:
        append_operation(operations, "temp_workspace", "failed", path=str(temp_root), reason=str(exc))


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
    run_started_at = datetime.now().astimezone()
    run_started_monotonic = time.monotonic()
    run_id = uuid.uuid4().hex[:10]
    args.engine_auto = args.engine is None
    args.yaw_auto = args.yaw is None
    args.exposure_auto = args.exposure is None
    args.world_strength_auto = args.world_strength is None
    args.light_scale_auto = args.light_scale is None
    apply_render_defaults(args)
    if args.key_green:
        try:
            blender = find_blender(args.blender)
            require_supported_blender(blender)
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"[environment] {exc}", file=sys.stderr, flush=True)
            return 1
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

    try:
        blender = find_blender(args.blender)
        blender_label = require_supported_blender(blender)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[environment] {exc}", file=sys.stderr, flush=True)
        return 1
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
    args.rpf_tool_path = None
    args.archive_tool_path = None
    operation_records: list[dict[str, object]] = []
    jobs: list[VehicleJob] = []
    job_results: list[RenderJobResult] = []

    def emit_report(status_override: str = "", error: str = "") -> dict[str, Path] | None:
        return emit_model_render_execution_report(
            out_dir=out_dir,
            run_id=run_id,
            started_at=run_started_at,
            started_monotonic=run_started_monotonic,
            input_path=input_dir,
            args=args,
            blender=blender,
            blender_label=blender_label,
            jobs=jobs,
            results=job_results,
            operations=operation_records,
            status_override=status_override,
            error=error,
        )


    try:
        require_free_disk_space(out_dir, "运行目录")
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        print(f"[disk] {exc}", file=sys.stderr, flush=True)
        emit_report("failed", str(exc))
        return 1

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
    temp_parent = out_dir / "_temp"
    if args.keep_work:
        temp_root = out_dir / "_work"
        if temp_root.exists():
            shutil.rmtree(temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
    else:
        temp_parent.mkdir(parents=True, exist_ok=True)
        temp_root_obj = tempfile.TemporaryDirectory(prefix="run_", dir=temp_parent)
        temp_root = Path(temp_root_obj.name)
    args.temp_root = temp_root.resolve()
    tempfile.tempdir = str(args.temp_root)
    for env_name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[env_name] = str(args.temp_root)
    print(f"[temp] {args.temp_root}", flush=True)

    scan_roots = [] if input_dir.is_file() else [input_dir]
    if not args.no_unpack:
        archive_tool = find_archive_tool(args.archive_tool)
        args.archive_tool_path = archive_tool
        scan_roots.extend(unpack_archives(input_dir, temp_root, archive_tool, operation_records))
        rpf_tool = find_rpf_tool(args.rpf_tool)
        args.rpf_tool_path = rpf_tool
        if rpf_tool:
            scan_roots.extend(unpack_rpfs(scan_roots, temp_root, rpf_tool, operation_records))
        else:
            rpf_files = sorted(
                {
                    str(path.resolve())
                    for root in scan_roots
                    for path in root.rglob("*.rpf")
                    if path.is_file()
                }
            )
            if rpf_files:
                print("[rpf] RpfTools.exe not found; skip .rpf unpack")
                append_operation(
                    operation_records,
                    "rpf_unpack",
                    "skipped",
                    detected=len(rpf_files),
                    reason="RpfTools.exe 不可用，未执行 RPF 解包。",
                )
            else:
                append_operation(
                    operation_records,
                    "rpf_unpack",
                    "not_needed",
                    detected=0,
                    note="扫描范围内未发现 RPF。",
                )
    else:
        append_operation(
            operation_records,
            "archive_unpack",
            "skipped",
            reason="本次启用了 --no-unpack，未检查或解包压缩包。",
        )
        append_operation(
            operation_records,
            "rpf_unpack",
            "skipped",
            reason="本次启用了 --no-unpack，未检查或解包 RPF。",
        )

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
        message = "No renderable assets found (.yft/.ydr/.ydd/.ymap)."
        print(message)
        append_operation(
            operation_records,
            "input_scan",
            "failed",
            scan_roots=len(scan_roots),
            discovered=len(assets),
            jobs=0,
            reason=message,
        )
        cleanup_run_workspace(temp_root, temp_root_obj, temp_parent, args.keep_work, operation_records)
        emit_report("failed", message)
        return 1

    unique_assets = [
        (asset, classify_drawable_asset(asset, asset_kind, args.asset_types))
        for asset, asset_kind in unique_assets
    ]
    unique_assets = filter_classified_assets(unique_assets, args.asset_types)
    if not unique_assets:
        message = f"No assets matched --asset-types {args.asset_types!r} after classification."
        print(message)
        append_operation(
            operation_records,
            "input_scan",
            "failed",
            scan_roots=len(scan_roots),
            discovered=len(assets),
            jobs=0,
            reason=message,
        )
        cleanup_run_workspace(temp_root, temp_root_obj, temp_parent, args.keep_work, operation_records)
        emit_report("failed", message)
        return 1

    jobs = [write_job_file(args, asset, asset_kind, jobs_dir, logs_dir, out_dir) for asset, asset_kind in unique_assets]
    append_operation(
        operation_records,
        "input_scan",
        "completed",
        scan_roots=len(scan_roots),
        discovered=len(assets),
        jobs=len(jobs),
        asset_types=sorted(asset_types),
    )
    workers = max(1, args.workers)

    print(f"Blender: {blender} ({blender_label})")
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

    failures: list[RenderJobResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_jobs = {executor.submit(run_blender_job, blender, job, args): job for job in jobs}
        for future in concurrent.futures.as_completed(future_jobs):
            job = future_jobs[future]
            try:
                result = future.result()
            except Exception as exc:
                message = f"\u6a21\u578b\u4efb\u52a1\u5f02\u5e38\u9000\u51fa\uff1a{exc}"
                result = RenderJobResult(job, "failed", 1, 0.0, message)
            job_results.append(result)
            if result.status == "success":
                print(f"[ok] {result.job.model} {result.elapsed_seconds:.1f}s")
            elif result.status == "skipped_existing":
                print(f"[skip] {result.job.model} existing output")
            else:
                suffix = f" - {result.message}" if result.message else ""
                print(
                    f"[fail] {result.job.model} rc={result.return_code} "
                    f"{result.elapsed_seconds:.1f}s{suffix}"
                )
                failures.append(result)
    append_operation(
        operation_records,
        "blender_render",
        "failed" if len(failures) == len(jobs) else "completed",
        success=sum(result.status == "success" for result in job_results),
        skipped=sum(result.status == "skipped_existing" for result in job_results),
        failed=len(failures),
    )

    texture_issue_count = 0
    auxiliary_error = ""
    if not args.skip_textures:
        try:
            texture_issue_count = write_texture_summary_report(jobs, out_dir)
            texture_report_path = out_dir / "_texture_report.txt"
            if texture_issue_count:
                print(f"[textures] issues={texture_issue_count}; report={texture_report_path}")
            else:
                print(f"[textures] report={texture_report_path}")
            append_operation(
                operation_records,
                "texture_report",
                "completed",
                issues=texture_issue_count,
                report=str(texture_report_path),
            )
        except Exception as exc:
            auxiliary_error = f"\u8d34\u56fe\u6c47\u603b\u62a5\u544a\u751f\u6210\u5931\u8d25\uff1a{exc}"
            print(f"[textures] {auxiliary_error}", file=sys.stderr, flush=True)
            append_operation(
                operation_records,
                "texture_report",
                "failed",
                issues=0,
                reason=auxiliary_error,
            )
    else:
        append_operation(
            operation_records,
            "texture_report",
            "skipped",
            issues=0,
            reason="\u672c\u6b21\u542f\u7528\u4e86 --skip-textures\u3002",
        )

    cleanup_run_workspace(temp_root, temp_root_obj, temp_parent, args.keep_work, operation_records)
    status_override = "partial_success" if auxiliary_error and not failures else ""
    report_paths = emit_report(status_override, auxiliary_error)
    report_failed = report_paths is None

    print(f"Done. OK={len(jobs) - len(failures)} FAIL={len(failures)}")
    if failures:
        print(f"Logs: {logs_dir}")
    if failures or auxiliary_error or report_failed:
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise
