# Vehicle Renderer

作者：JACK
联系方式：QQ 2518926462

基于 Blender、Sollumz 和 CodeWalker 运行工具的 FiveM/GTA V 资源批量渲染器。指定一个资源目录后，工具会自动解包 `.zip` / `.rar` / `.7z` / `.rpf`，提取 `.ytd` 贴图，导入模型并输出 PNG 图片。

支持车辆、武器、饰品、普通物品和地图资源。一个压缩包里有多个模型时，不传 `--model` 会把能导入的模型全部渲染出来；同名 `_hi` / `+hi` 高模会优先使用高模版本。

## 效果示例

### 车辆示例

| 模型 | 默认灰模 | 灰模 PNG | 黑模 | 黑模 PNG | 白模 | 白模 PNG | 绿幕 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 16MANDBS111 | ![16MANDBS111 gray model](docs/images/vehicle_16MANDBS111_gray_model.png) | ![16MANDBS111 gray png](docs/images/vehicle_16MANDBS111_gray_png.png) | ![16MANDBS111 black model](docs/images/vehicle_16MANDBS111_black_model.png) | ![16MANDBS111 black png](docs/images/vehicle_16MANDBS111_black_png.png) | ![16MANDBS111 white model](docs/images/vehicle_16MANDBS111_white_model.png) | ![16MANDBS111 white png](docs/images/vehicle_16MANDBS111_white_png.png) | ![16MANDBS111 greenscreen](docs/images/vehicle_16MANDBS111_greenscreen.png) |
| fordc72 | ![fordc72 gray model](docs/images/vehicle_fordc72_gray_model.png) | ![fordc72 gray png](docs/images/vehicle_fordc72_gray_png.png) | ![fordc72 black model](docs/images/vehicle_fordc72_black_model.png) | ![fordc72 black png](docs/images/vehicle_fordc72_black_png.png) | ![fordc72 white model](docs/images/vehicle_fordc72_white_model.png) | ![fordc72 white png](docs/images/vehicle_fordc72_white_png.png) | ![fordc72 greenscreen](docs/images/vehicle_fordc72_greenscreen.png) |
| zondarevob | ![zondarevob gray model](docs/images/vehicle_zondarevob_gray_model.png) | ![zondarevob gray png](docs/images/vehicle_zondarevob_gray_png.png) | ![zondarevob black model](docs/images/vehicle_zondarevob_black_model.png) | ![zondarevob black png](docs/images/vehicle_zondarevob_black_png.png) | ![zondarevob white model](docs/images/vehicle_zondarevob_white_model.png) | ![zondarevob white png](docs/images/vehicle_zondarevob_white_png.png) | ![zondarevob greenscreen](docs/images/vehicle_zondarevob_greenscreen.png) |

### 武器示例

| 模型 | 白底样图 | 透明裁切 PNG |
| --- | --- | --- |
| w_pi_fn509t | ![w_pi_fn509t white](docs/images/weapon_w_pi_fn509t_white.png) | ![w_pi_fn509t cutout](docs/images/weapon_w_pi_fn509t_cutout.png) |
| w_sg_beanbagshotgun | ![w_sg_beanbagshotgun white](docs/images/weapon_w_sg_beanbagshotgun_white.png) | ![w_sg_beanbagshotgun cutout](docs/images/weapon_w_sg_beanbagshotgun_cutout.png) |
| w_pi_c17s | ![w_pi_c17s white](docs/images/weapon_w_pi_c17s_white.png) | ![w_pi_c17s cutout](docs/images/weapon_w_pi_c17s_cutout.png) |

### 饰品示例

| 模型 | 白底样图 | 透明裁切 PNG |
| --- | --- | --- |
| labubu_clap | ![labubu_clap white](docs/images/accessory_labubu_clap_white.png) | ![labubu_clap cutout](docs/images/accessory_labubu_clap_cutout.png) |
| shibanita | ![shibanita white](docs/images/accessory_shibanita_white.png) | ![shibanita cutout](docs/images/accessory_shibanita_cutout.png) |
| keroppi | ![keroppi white](docs/images/accessory_keroppi_white.png) | ![keroppi cutout](docs/images/accessory_keroppi_cutout.png) |

## 功能

- 递归扫描指定文件夹，支持 `.yft`、`.ydr`、`.ydd`、`.ymap`。
- 自动解包 `.zip`、`.rar`、`.7z` 和 `.rpf`，支持压缩包里再套 RPF。
- 一个压缩包内多个模型会全部生成任务；`--model` 只用于手动过滤指定模型。
- 自动提取本地 `.ytd` 和共享 `vehshare.ytd`，绑定材质贴图。
- DDS 转 PNG 时遇到损坏 DDS 会跳过坏图，不会让整个模型失败。
- Blender 后台导入模型、绑定贴图、补齐车辆缺失车轮、修正玻璃/车轮基础材质。
- `--workers` 多进程并发渲染。
- `--cutout` 输出透明 PNG，保留车漆高光、反光和半透明阴影。
- 不会创建额外点光源补光；明确的警灯/自发光材质只按原材质颜色写入 emission，不按名字强制改成红/橙。
- 最终 PNG 默认裁掉所有透明空白像素；需要保留边距时加 `--key-padding 12`。
- 同时保留 `_greenscreen` 绿幕预览和 `_alpha` 原始透明图。
- 每次渲染生成 `_texture_report.txt/.json`，列出贴图命中和缺失情况。

## 快速使用

渲染目录内所有支持资源：

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
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --model w_pi_fn509t --cutout
```

## 资源类型

```text
all            全部支持资源
vehicle        .yft 车辆
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
  model.png                    # 最终透明裁切 PNG
  _alpha/model.png             # Blender 原始透明渲染
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
--yaw 135 --elevation 26
--model-tone gray
--model-tone white
--model-tone black
--no-special-lights
--key-padding 0
```

`--model-tone gray/white` 只调整车辆原生主色、副色和珠光车漆层，不覆盖漫反射贴图；`black` 保留旧版黑模的纹理明暗乘算。玻璃、灯光、轮胎、轮毂、内饰和贴花不参与白/灰改色。

`--key-padding` 默认是 `0`，表示裁掉所有透明空白像素；如果文档或网页展示需要留边，可以设为 `8` 或 `12`。

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

## 参考

- [dexyfex/CodeWalker](https://github.com/dexyfex/CodeWalker)
- [Sollumz/Sollumz](https://github.com/Sollumz/Sollumz)
