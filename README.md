# Model Renderer

[![Build](https://github.com/ch-jack/CK-model_renderer/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/ch-jack/CK-model_renderer/actions/workflows/build.yml)

作者：JACK
联系方式：QQ 2518926462

基于 Blender、Sollumz 和 CodeWalker 运行工具的 FiveM/GTA V 资源批量渲染器。指定一个资源目录后，工具会自动解包 `.zip` / `.rar` / `.7z` / `.rpf`，提取 `.ytd` 贴图，导入模型并输出 PNG 图片。

支持所有模型，包括载具、武器、饰品、普通物品和地图资源。一个压缩包里有多个模型时，不传 `--model` 会把能导入的模型全部渲染出来；同名 `_hi` / `+hi` 高模会优先使用高模版本。

## 效果示例

### 模型示例

| 模型 | 灰模 | 灰模 PNG | 默认黑模 | 黑模 PNG | 白模 | 白模 PNG | 绿幕 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 16MANDBS111 | ![16MANDBS111 gray model](docs/images/vehicle_16MANDBS111_gray_model.png) | ![16MANDBS111 gray png](docs/images/vehicle_16MANDBS111_gray_png.png) | ![16MANDBS111 black model](docs/images/vehicle_16MANDBS111_black_model.png) | ![16MANDBS111 black png](docs/images/vehicle_16MANDBS111_black_png.png) | ![16MANDBS111 white model](docs/images/vehicle_16MANDBS111_white_model.png) | ![16MANDBS111 white png](docs/images/vehicle_16MANDBS111_white_png.png) | ![16MANDBS111 greenscreen](docs/images/vehicle_16MANDBS111_greenscreen.png) |
| fordc72 | ![fordc72 gray model](docs/images/vehicle_fordc72_gray_model.png) | ![fordc72 gray png](docs/images/vehicle_fordc72_gray_png.png) | ![fordc72 black model](docs/images/vehicle_fordc72_black_model.png) | ![fordc72 black png](docs/images/vehicle_fordc72_black_png.png) | ![fordc72 white model](docs/images/vehicle_fordc72_white_model.png) | ![fordc72 white png](docs/images/vehicle_fordc72_white_png.png) | ![fordc72 greenscreen](docs/images/vehicle_fordc72_greenscreen.png) |
| zondarevob | ![zondarevob gray model](docs/images/vehicle_zondarevob_gray_model.png) | ![zondarevob gray png](docs/images/vehicle_zondarevob_gray_png.png) | ![zondarevob black model](docs/images/vehicle_zondarevob_black_model.png) | ![zondarevob black png](docs/images/vehicle_zondarevob_black_png.png) | ![zondarevob white model](docs/images/vehicle_zondarevob_white_model.png) | ![zondarevob white png](docs/images/vehicle_zondarevob_white_png.png) | ![zondarevob greenscreen](docs/images/vehicle_zondarevob_greenscreen.png) |
| LD_Bolide | ![LD_Bolide gray model](docs/images/vehicle_LD_Bolide_gray_model.png) | ![LD_Bolide gray png](docs/images/vehicle_LD_Bolide_gray_png.png) | ![LD_Bolide black model](docs/images/vehicle_LD_Bolide_black_model.png) | ![LD_Bolide black png](docs/images/vehicle_LD_Bolide_black_png.png) | ![LD_Bolide white model](docs/images/vehicle_LD_Bolide_white_model.png) | ![LD_Bolide white png](docs/images/vehicle_LD_Bolide_white_png.png) | ![LD_Bolide greenscreen](docs/images/vehicle_LD_Bolide_greenscreen.png) |

### 武器示例

| 模型 | 白底样图 | 透明 PNG |
| --- | --- | --- |
| w_ar_kajszs | ![w_ar_kajszs white](docs/images/weapon_w_ar_kajszs_white.png) | ![w_ar_kajszs cutout](docs/images/weapon_w_ar_kajszs_cutout.png) |
| w_ar_kajszs_mag1 | ![w_ar_kajszs_mag1 white](docs/images/weapon_w_ar_kajszs_mag1_white.png) | ![w_ar_kajszs_mag1 cutout](docs/images/weapon_w_ar_kajszs_mag1_cutout.png) |
| w_sg_beanbagshotgun | ![w_sg_beanbagshotgun white](docs/images/weapon_w_sg_beanbagshotgun_white.png) | ![w_sg_beanbagshotgun cutout](docs/images/weapon_w_sg_beanbagshotgun_cutout.png) |

### 饰品示例

| 模型 | 棚拍样图 | 透明 PNG |
| --- | --- | --- |
| labubu_clap | ![labubu_clap studio](docs/images/accessory_labubu_clap_white.png) | ![labubu_clap cutout](docs/images/accessory_labubu_clap_cutout.png) |
| shibanita | ![shibanita white](docs/images/accessory_shibanita_white.png) | ![shibanita cutout](docs/images/accessory_shibanita_cutout.png) |
| keroppi | ![keroppi white](docs/images/accessory_keroppi_white.png) | ![keroppi cutout](docs/images/accessory_keroppi_cutout.png) |

## 功能

- 递归扫描指定文件夹，支持 `.yft`、`.ydr`、`.ydd`、`.ymap`。
- 自动解包 `.zip`、`.rar`、`.7z` 和 `.rpf`，支持压缩包里再套 RPF。
- 一个压缩包内多个模型会全部生成任务；`--model` 只用于手动过滤指定模型。
- 自动提取本地 `.ytd` 和共享 `vehshare.ytd`，绑定材质贴图。
- 正确识别 YDR 内嵌 `color_d/color_n/color_s` 贴图，不再误报缺失或用外部颜色覆盖。
- 饰品自动使用 Cycles、AgX Punchy 色彩、柔和棚拍光和灰色背景；带同名 YCD 动画的姿态模型自动使用正面特写，普通饰品与透明 PNG 保持完整安全取景。
- DDS 转 PNG 时遇到损坏 DDS 会跳过坏图，不会让整个模型失败。
- Blender 后台导入模型、绑定贴图、补齐模型缺失车轮、修正玻璃/车轮基础材质。
- `--workers` 多进程并发渲染。
- `--cutout` 输出透明 PNG，保留模型高光、反光和半透明材质。
- 不会创建额外点光源补光；明确的警灯/自发光材质只按原材质颜色写入 emission，不按名字强制改成红/橙。
- 根目录透明 PNG 按 8 位 PNG 中所有非零 alpha 像素精确裁切，效果等同 Photoshop“裁切透明像素”；`_alpha` 仍保持 `--width/--height` 完整画布。
- 所有模型统一按实际投影边界自适应取景，不再按资源类型使用固定最小画幅。
- 同时保留 `_greenscreen` 绿幕预览和 `_alpha` 归一化透明图。
- 每次渲染生成 `_texture_report.txt/.json`，列出贴图命中和缺失情况。

## 快速使用

直接把文件夹交给入口，默认扫描全部类型并使用黑模输出透明裁切图：

```cmd
render_folder.cmd "D:\fivem\TestVeh"
```

等价的 Python 命令：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --asset-types all --workers 2 --force --cutout
```

只渲染一个武器压缩包里的所有武器模型：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --asset-types weapon --workers 2 --force --cutout
```

只渲染一个饰品压缩包里的所有饰品模型：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --asset-types accessory --workers 2 --force --cutout
```

只渲染指定模型：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --model w_ar_kajszs --cutout
```

## 资源类型

```text
all            全部支持资源
vehicle        .yft 模型
weapon         武器 .ydr
accessory      饰品/背包/挂件 .ydr
prop           普通物品 .ydr
drawable       所有 .ydr
drawable-dict  .ydd
map            .ymap
```

`weapon/accessory/prop` 会先扫描 `.ydr`，再按路径和模型名分类过滤。`drawable` / `all` 不过滤 `.ydr` 类型。

## 输出结构

```text
_vehicle_renders/
  model.png                    # 最终裁边透明 PNG
  _alpha/model.png             # 完整画布透明渲染
  _greenscreen/model.png       # 绿幕预览
  _textures/model/*.png        # 提取出来的贴图
  _jobs/model.json             # 单模型任务
  _logs/model.log              # Blender 日志
  _logs/model.textures.log     # 贴图提取日志
  _logs/model.textures.bind.json
  _texture_report.txt
  _texture_report.json
```

## 贴图报告

如果模型引用了贴图但资源包里没有对应 `.ytd`，报告会列出缺失纹理名，例如：

```text
missing: color_d, color_n, color_s
note: no local YTD textures were extracted; add the correct .ytd next to the model or pass --shared-ytd.
```

处理方式：把正确 `.ytd` 放到模型同目录，或指定共享贴图：

```powershell
--shared-ytd "D:\path\textures.ytd"
```

## 常用参数

```powershell
--workers 4
--force
--skip-existing
--width 1600 --height 1000
--cutout-width 1920 --cutout-height 1080
--yaw 135 --elevation 26
--model-tone black
--model-tone gray
--model-tone white
--no-special-lights
--key-padding 0
```

未传 `--yaw` 时，带同名 YCD 动画的饰品姿态模型使用 155 度正面特写，普通饰品和其他模型保持 135 度；显式传入 `--yaw` 会覆盖自动值。

`--model-tone black` 是默认值；`gray/white/black` 都只调整模型原生主色、副色、珠光和明确的车漆材质，不覆盖或暗化漫反射贴图。玻璃、灯光、轮胎、轮毂、金属、碳纤维、塑料、内饰和贴花不参与改色。

Cycles 渲染前会把 Sollumz 数值参数烘焙为标准 Blender 节点常量，已有 Base Color 上游贴图链不会被补图逻辑覆盖。武器材质若把 `_dpal` / palette / tint 调色板误接到 Base Color，会改用本地漫反射贴图（例如 `map.png`）；`_nm` / `_spec` 按 Non-Color 数据读取。

`--key-padding 0`（默认）等同 Photoshop“裁切透明像素”；大于 0 时才会在透明 PNG 周围增加指定像素留边。`_alpha` 始终保留 `--width/--height` 完整画布。
`--cutout-width/--cutout-height` 设置根目录裁切 PNG 的最小分辨率；任一边不足时等比放大，已达到尺寸时不缩小。`_alpha` 和 `_greenscreen` 仍保持渲染画布分辨率。

## 内置运行资源

仓库只需要带运行必需文件，不要提交 CodeWalker/RpfTools/YtdTools 的源码工程：

```text
vehicle_renderer/
  vehshare.ytd
  tools/
    7z.exe
    7z.dll
    RpfTools.exe
    RpfTools.exe.config
    YtdTools.exe
    YtdTools.exe.config
    CodeWalker.Core.dll
    SharpDX.dll
    SharpDX.Mathematics.dll
    texconv.exe
```

## 自动构建与发布

- 推送任意分支、提交 Pull Request 或手动运行 `Build` 工作流时，会生成 Windows ZIP 和 SHA256 校验文件，可在该次 Actions 的 Artifacts 中下载。
- 推送 `v*` 标签（例如 `v1.0.0`）时，会自动创建对应的 GitHub Release，并上传 ZIP 和 SHA256 文件。
- 发布包包含固定版本的 Sollumz 2.8.3 和全部运行脚本、文档、共享贴图及工具，但不包含 Blender、Python 和 .NET Framework。
- 运行环境需要 Windows、Python、Blender 4.2+（推荐 5.1）和 .NET Framework 4.8。

本地生成同样的发布包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release.ps1 -OutputDirectory dist -SollumzSource Sollumz -Version local
```

## 参考
- [dexyfex/CodeWalker](https://github.com/dexyfex/CodeWalker)
- [Sollumz/Sollumz](https://github.com/Sollumz/Sollumz)

## 载具自动拼装

当资源目录包含 `vehicles.meta`、`carvariations.meta` 和 `carcols.meta` 时，渲染器会识别基车模型，读取改装套件，把分离的 `.yft` 部件导入同一场景并按骨骼挂接。改装件不会再被当成独立载具重复截图。

默认 `--vehicle-assembly auto`：检测到可用改装套件时使用 `showcase`，每种 `VMT_*` 类型只选择第一个可用方案，关联件会一起显示。渲染器同时应用所选方案的 `turnOffBones`，关闭同一部位被替换的基车零件；其他可显示 extras 保留。带贴图、特效或发光的零件和图案全部保留；特效壳和投影平面按透明 PNG 图层显示，使用原 Alpha 或贴图亮度去除黑底，整车覆盖层最大不透明度为 0.15。原生发光保留并限制最高强度为 2.4，避免覆盖车漆纹理。与主 `bodyshell` 尺寸和中心都重叠的实体 `extra_N` 按“同部位只显示一套”去重；`requiredExtras` 和改件正在使用的 extra 不隐藏。普通单体模型仍按原流程渲染。

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh\LD_Bolide.zip" --model LD_Bolide --asset-types vehicle --cutout --force --save-blend
```

![LD_Bolide assembled](docs/images/vehicle_LD_Bolide_assembled.png)

常用拼装参数：

```text
--vehicle-assembly auto       自动检测，默认
--vehicle-assembly showcase  每种改装类型选择第一个可用方案
--vehicle-assembly all       导入套件中所有存在的改装模型
--vehicle-assembly none      只渲染基车
--vehicle-mod VMT_GRILL:2    选择某类改装的第 2 个方案
--vehicle-mod LD_Bolide_cb   直接指定改装模型名
--vehicle-kit <kitName>      指定 carcols.meta 套件
--vehicle-attach preserve    按基车骨骼挂接并保留资源坐标
```

加 `--save-blend` 后，拼装场景保存在 `_jobs\模型名.blend`。
