from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path


VEHICLE_META_FILES = ("vehicles.meta", "handling.meta", "carvariations.meta", "carcols.meta")
XML_COMMENT_PATTERN = re.compile(r"<!--[\s\S]*?-->")
XML_DECLARATION_PATTERN = re.compile(r"<\?xml[\s\S]*?\?>", re.IGNORECASE)
XML_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
MODEL_NAME_PATTERN = re.compile(r"<modelName(?:\s[^>]*)?>([\s\S]*?)</modelName>", re.IGNORECASE)
HANDLING_NAME_PATTERN = re.compile(r"<handlingName(?:\s[^>]*)?>([\s\S]*?)</handlingName>", re.IGNORECASE)
STANDARD_WHEEL_KEYS = ("lf", "rf", "lr", "rr")


def clean_model_name(name: str) -> str:
    lower = name.lower()
    if lower.endswith("_hi") or lower.endswith("+hi"):
        return name[:-3]
    return name


def plan_missing_wheel_clones(
    existing_keys: set[str], target_keys: tuple[str, ...] = STANDARD_WHEEL_KEYS
) -> list[tuple[str, str, bool]]:
    available = {key.lower() for key in existing_keys}
    plans: list[tuple[str, str, bool]] = []
    for target in target_keys:
        target = target.lower()
        if target in available or len(target) != 2:
            continue
        side, axle = target
        other_side = "r" if side == "l" else "l"
        other_axle = "r" if axle == "f" else "f"
        candidates = (
            f"{side}{other_axle}",
            f"{other_side}{axle}",
            f"{other_side}{other_axle}",
        )
        source = next((candidate for candidate in candidates if candidate in available), None)
        if source is None:
            continue
        plans.append((source, target, source[0] != target[0]))
        available.add(target)
    return plans


@lru_cache(maxsize=None)
def vehicle_resource_roots(stream_dir: Path) -> tuple[Path, ...]:
    stream_dir = stream_dir.resolve()
    candidates: list[Path] = []

    def add_candidate(candidate: Path) -> None:
        candidate = candidate.resolve()
        if candidate not in candidates and any((candidate / name).is_file() for name in VEHICLE_META_FILES):
            candidates.append(candidate)

    add_candidate(stream_dir)
    if stream_dir.name.lower() == "stream":
        add_candidate(stream_dir.parent)

    stream_root = next(
        (candidate for candidate in (stream_dir, *stream_dir.parents) if candidate.name.lower() == "stream"),
        None,
    )
    if stream_root is not None:
        resource_root = stream_root.parent
        relative_stream = stream_dir.relative_to(stream_root)
        data_root = resource_root / "data"
        exact_metadata = data_root if str(relative_stream) == "." else data_root / relative_stream
        add_candidate(exact_metadata)
        if data_root.is_dir():
            metadata_directories = sorted(
                {
                    path.parent.resolve()
                    for path in data_root.rglob("*")
                    if path.is_file() and path.name.lower() in VEHICLE_META_FILES
                },
                key=lambda path: str(path).lower(),
            )
            for metadata_directory in metadata_directories:
                add_candidate(metadata_directory)
    return tuple(candidates)


def vehicle_resource_root(
    stream_dir: Path, model: str = "", extra_roots: tuple[Path, ...] = ()
) -> Path | None:
    roots = list(vehicle_resource_roots(stream_dir))
    for root in extra_roots:
        resolved = root.resolve()
        if resolved not in roots:
            roots.append(resolved)
    if model:
        model_key = model.lower()
        for root in roots:
            if model_key in {name.lower() for name in parse_vehicle_models(root, stream_dir)}:
                return root
        for root in roots:
            if model_key in {name.lower() for name in parse_declared_vehicle_models(root, stream_dir)}:
                return root
    for root in roots:
        if parse_vehicle_models(root, stream_dir):
            return root
    return roots[0] if roots else None


@lru_cache(maxsize=None)
def read_xml(path: Path) -> ET.Element | None:
    if not path.is_file():
        return None
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        data = path.read_bytes()
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = data.decode("utf-16", errors="replace")
        else:
            text = data.decode("utf-8-sig", errors="replace")
        sanitized = XML_CONTROL_PATTERN.sub("", XML_DECLARATION_PATTERN.sub("", XML_COMMENT_PATTERN.sub("", text)))
        for candidate in (sanitized, f"<ck_metadata_root>{sanitized}</ck_metadata_root>"):
            try:
                root = ET.fromstring(candidate)
                print(f"[metadata] repaired malformed XML in memory: {path}", flush=True)
                return root
            except ET.ParseError:
                pass

        if path.name.lower() in {"vehicles.meta", "handling.meta", "carvariations.meta", "carcols.meta"}:
            model_names = []
            seen: set[str] = set()
            name_pattern = HANDLING_NAME_PATTERN if path.name.lower() == "handling.meta" else MODEL_NAME_PATTERN
            for match in name_pattern.finditer(text):
                model = match.group(1).strip()
                key = model.lower()
                if model and key not in seen:
                    seen.add(key)
                    model_names.append(model)
            if model_names:
                root = ET.Element("ck_metadata_root")
                if path.name.lower() == "handling.meta":
                    container = ET.SubElement(root, "HandlingData")
                elif path.name.lower() == "carcols.meta":
                    kits = ET.SubElement(root, "Kits")
                    kit = ET.SubElement(kits, "Item")
                    container = ET.SubElement(kit, "visibleMods")
                else:
                    container = ET.SubElement(
                        root, "variationData" if path.name.lower() == "carvariations.meta" else "InitDatas"
                    )
                for model in model_names:
                    item = ET.SubElement(container, "Item")
                    ET.SubElement(item, "handlingName" if path.name.lower() == "handling.meta" else "modelName").text = model
                print(f"[metadata] recovered {len(model_names)} model names from malformed XML: {path}", flush=True)
                return root

        print(f"[metadata] skipped malformed XML: {path}: {exc}", flush=True)
        return None


def text_of(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    return (node.findtext(name) or "").strip()


def item_values(node: ET.Element | None, name: str) -> list[str]:
    if node is None:
        return []
    return [
        (item.text or "").strip()
        for item in node.findall(f"./{name}/Item")
        if (item.text or "").strip()
    ]


def bool_value(node: ET.Element | None, name: str) -> bool:
    if node is None:
        return False
    value_node = node.find(name)
    if value_node is None:
        return False
    value = (value_node.get("value") or value_node.text or "").strip().lower()
    return value in {"1", "true", "yes"}


def normalize_extra_name(value: str) -> str:
    value = value.strip().lower().replace("-", "_")
    if not value:
        return ""
    if value.isdigit():
        return f"extra_{int(value)}"
    if value.startswith("extra"):
        suffix = value[5:].lstrip("_ ")
        if suffix.isdigit():
            return f"extra_{int(suffix)}"
    return value


@lru_cache(maxsize=None)
def _stream_yft_items(stream_dir: Path) -> tuple[tuple[str, str], ...]:
    by_model: dict[str, str] = {}
    for path in sorted(stream_dir.glob("*.yft")):
        model = clean_model_name(path.stem).lower()
        existing = by_model.get(model)
        if existing is None:
            by_model[model] = path.name
            continue
        existing_hi = Path(existing).stem.lower().endswith(("_hi", "+hi"))
        current_hi = path.stem.lower().endswith(("_hi", "+hi"))
        if existing_hi and not current_hi:
            by_model[model] = path.name
    return tuple(by_model.items())


def stream_yft_map(stream_dir: Path) -> dict[str, str]:
    return dict(_stream_yft_items(stream_dir.resolve()))


@lru_cache(maxsize=None)
def _parse_declared_vehicle_models(resource_root: Path, stream_dir: Path) -> tuple[str, ...]:
    available = stream_yft_map(stream_dir)
    vehicles_root = read_xml(resource_root / "vehicles.meta")
    if vehicles_root is None:
        return ()
    vehicle_models = tuple(
        (node.text or "").strip()
        for node in vehicles_root.findall(".//InitDatas/Item/modelName")
        if (node.text or "").strip() and (node.text or "").strip().lower() in available
    )
    return vehicle_models


def parse_declared_vehicle_models(resource_root: Path, stream_dir: Path) -> list[str]:
    return list(_parse_declared_vehicle_models(resource_root.resolve(), stream_dir.resolve()))


@lru_cache(maxsize=None)
def _parse_handling_names(resource_root: Path) -> tuple[str, ...]:
    handling_root = read_xml(resource_root / "handling.meta")
    if handling_root is None:
        return ()
    return tuple(
        dict.fromkeys(
            (node.text or "").strip().lower()
            for node in handling_root.findall(".//HandlingData/Item/handlingName")
            if (node.text or "").strip()
        )
    )


def parse_handling_names(resource_root: Path) -> list[str]:
    return list(_parse_handling_names(resource_root.resolve()))


@lru_cache(maxsize=None)
def _parse_vehicle_models(resource_root: Path, stream_dir: Path) -> tuple[str, ...]:
    vehicle_models = parse_declared_vehicle_models(resource_root, stream_dir)
    handling_names = set(parse_handling_names(resource_root))
    models = [model for model in vehicle_models if model.lower() in handling_names]

    out: list[str] = []
    seen: set[str] = set()
    for model in models:
        key = model.lower()
        if key not in seen:
            seen.add(key)
            out.append(model)
    return tuple(out)


def parse_vehicle_models(resource_root: Path, stream_dir: Path) -> list[str]:
    return list(_parse_vehicle_models(resource_root.resolve(), stream_dir.resolve()))


def parse_kits(resource_root: Path) -> dict[str, dict[str, object]]:
    root = read_xml(resource_root / "carcols.meta")
    if root is None:
        return {}

    kits: dict[str, dict[str, object]] = {}
    for kit_node in root.findall(".//Kits/Item"):
        kit_name = text_of(kit_node, "kitName")
        if not kit_name:
            continue
        visible_mods: list[dict[str, object]] = []
        for item in kit_node.findall("./visibleMods/Item"):
            model = text_of(item, "modelName")
            if not model:
                continue
            visible_mods.append(
                {
                    "model": model,
                    "type": text_of(item, "type"),
                    "bone": text_of(item, "bone") or "chassis",
                    "linked": [
                        (link.text or "").strip()
                        for link in item.findall("./linkedModels/Item")
                        if (link.text or "").strip()
                    ],
                    "turn_off_bones": item_values(item, "turnOffBones"),
                    "turn_off_extra": bool_value(item, "turnOffExtra"),
                }
            )

        link_bones: dict[str, str] = {}
        for item in kit_node.findall("./linkMods/Item"):
            model = text_of(item, "modelName")
            bone = text_of(item, "bone")
            if model and bone:
                link_bones[model.lower()] = bone
        kits[kit_name.lower()] = {
            "name": kit_name,
            "visible_mods": visible_mods,
            "link_bones": link_bones,
        }
    return kits


def kit_names_for_model(resource_root: Path, model: str) -> list[str]:
    root = read_xml(resource_root / "carvariations.meta")
    if root is None:
        return []
    for item in root.findall(".//variationData/Item"):
        if text_of(item, "modelName").lower() != model.lower():
            continue
        return [
            (kit.text or "").strip()
            for kit in item.findall("./kits/Item")
            if (kit.text or "").strip()
        ]
    return []


def extras_for_model(resource_root: Path, model: str) -> dict[str, list[str]]:
    root = read_xml(resource_root / "vehicles.meta")
    if root is None:
        return {"included": [], "required": []}
    for item in root.findall(".//InitDatas/Item"):
        if text_of(item, "modelName").lower() != model.lower():
            continue
        return {
            "included": [normalize_extra_name(value) for value in item_values(item, "extraIncludes")],
            "required": [normalize_extra_name(value) for value in item_values(item, "requiredExtras")],
        }
    return {"included": [], "required": []}


def resolve_kit(resource_root: Path, model: str, requested_kit: str):
    kits = parse_kits(resource_root)
    if not kits:
        return "", [], {}
    if requested_kit:
        kit = kits.get(requested_kit.lower())
        if kit is None:
            raise RuntimeError(f"Vehicle assembly kit not found: {requested_kit}")
        return kit["name"], kit["visible_mods"], kit["link_bones"]
    for kit_name in kit_names_for_model(resource_root, model):
        kit = kits.get(kit_name.lower())
        if kit is not None:
            return kit["name"], kit["visible_mods"], kit["link_bones"]
    first = next(iter(kits.values()))
    return first["name"], first["visible_mods"], first["link_bones"]


def mod_exists(mod: dict[str, object], available: dict[str, str]) -> bool:
    names = [str(mod["model"]), *[str(item) for item in mod.get("linked", [])]]
    return any(name.lower() in available for name in names)


def select_showcase_mods(visible_mods, available):
    chosen = []
    used_types: set[str] = set()
    for mod in visible_mods:
        mod_type = str(mod.get("type", "")).lower()
        if mod_type in used_types or not mod_exists(mod, available):
            continue
        used_types.add(mod_type)
        chosen.append(mod)
    return chosen


def select_explicit_mods(visible_mods, available, specs: list[str]):
    by_model = {str(mod["model"]).lower(): mod for mod in visible_mods}
    by_type: dict[str, list[dict[str, object]]] = {}
    for mod in visible_mods:
        by_type.setdefault(str(mod.get("type", "")).lower(), []).append(mod)

    chosen = []
    for spec in specs:
        raw = spec.strip()
        if not raw:
            continue
        key = raw.lower()
        index = 1
        if ":" in raw:
            left, right = raw.rsplit(":", 1)
            key = left.strip().lower()
            try:
                index = max(1, int(right.strip()))
            except ValueError:
                raise RuntimeError(f"Invalid vehicle mod selector: {raw}") from None
        mod = by_model.get(key)
        if mod is None:
            matches = [item for item in by_type.get(key, []) if mod_exists(item, available)]
            if matches:
                if index > len(matches):
                    raise RuntimeError(f"Vehicle mod selector out of range: {raw}")
                mod = matches[index - 1]
        if mod is None and key in available:
            mod = {
                "model": raw,
                "type": "EXPLICIT",
                "bone": "chassis",
                "linked": [],
                "turn_off_bones": [],
                "turn_off_extra": False,
            }
        if mod is not None and mod_exists(mod, available):
            chosen.append(mod)
    return chosen


def build_assembly_plan(
    resource_root: Path,
    stream_dir: Path,
    base_model: str,
    mode: str = "auto",
    requested_kit: str = "",
    mod_specs: list[str] | None = None,
) -> dict[str, object]:
    available = stream_yft_map(stream_dir)
    base_key = base_model.lower()
    if base_key not in available:
        raise RuntimeError(f"Vehicle assembly base YFT not found: {base_model}")

    specs = list(mod_specs or [])
    effective_mode = "showcase" if mode == "auto" and ((resource_root / "carcols.meta").is_file() or specs) else mode
    if effective_mode == "auto":
        effective_mode = "none"
    if effective_mode == "none":
        kit_name, visible_mods, link_bones = "", [], {}
        selected_mods = []
    else:
        kit_name, visible_mods, link_bones = resolve_kit(resource_root, base_model, requested_kit)
        if specs:
            selected_mods = select_explicit_mods(visible_mods, available, specs)
        elif effective_mode == "all":
            selected_mods = [mod for mod in visible_mods if mod_exists(mod, available)]
        elif effective_mode == "showcase":
            selected_mods = select_showcase_mods(visible_mods, available)
        else:
            raise RuntimeError(f"Unknown vehicle assembly mode: {mode}")

    parts: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(model: str, bone: str, mod_type: str) -> None:
        key = model.lower()
        filename = available.get(key)
        if not filename or key in seen:
            return
        seen.add(key)
        parts.append(
            {
                "model": clean_model_name(Path(filename).stem),
                "file": filename,
                "bone": bone or link_bones.get(key, "chassis"),
                "type": mod_type,
            }
        )

    add(base_model, "chassis", "BASE")
    for mod in selected_mods:
        mod_type = str(mod.get("type", ""))
        bone = str(mod.get("bone", "")) or "chassis"
        add(str(mod["model"]), bone, mod_type)
        for linked in mod.get("linked", []):
            linked_name = str(linked)
            add(linked_name, link_bones.get(linked_name.lower(), bone), mod_type)

    disabled_bones: list[str] = []
    seen_disabled: set[str] = set()
    for mod in selected_mods:
        for bone in mod.get("turn_off_bones", []):
            name = str(bone).strip()
            key = name.lower()
            if name and key not in seen_disabled:
                seen_disabled.add(key)
                disabled_bones.append(name)

    extras = extras_for_model(resource_root, base_model)

    return {
        "enabled": len(parts) > 1,
        "mode": effective_mode,
        "kit": str(kit_name),
        "base_model": base_model,
        "parts": parts,
        "disabled_bones": disabled_bones,
        "turn_off_extra": any(bool(mod.get("turn_off_extra")) for mod in selected_mods),
        "included_extras": extras["included"],
        "required_extras": extras["required"],
    }
