# 使用文档

作者：JACK
联系方式：QQ 2518926462

## 1. 工具目标

`vehicle_renderer` 用于把 FiveM/GTA V 资源批量渲染成 PNG。它会自动处理常见资源包格式，流程是：

1. 解包 `.zip` / `.rar` / `.7z`。
2. 解包找到的 `.rpf`。
3. 扫描 `.yft`、`.ydr`、`.ydd`、`.ymap`。
4. 从本地 `.ytd` 和共享 `vehshare.ytd` 提取贴图。
5. 调用 Blender/Sollumz 导入模型、绑定贴图并渲染。
   YDR 内嵌贴图会直接保留；饰品自动使用 Cycles 和 AgX Punchy 柔光棚拍，只有带同名 YCD 动画的姿态模型使用正面特写。
6. 输出棚拍/白底预览、绿幕预览、裁边透明 PNG、完整画布 `_alpha` PNG 和贴图报告。

所有解包和纹理中间文件都写入本次输出目录的 `_temp`，不再占用系统临时目录；正常结束自动删除，使用 `--keep-work` 时保留为 `_work`。开始处理前会检查 Blender 版本和运行目录空间，要求 Blender 4.2+（推荐 5.1）且至少剩余 1 GB。

不传 `--model` 时，一个压缩包里有多少可导入模型就渲染多少个；传 `--model` 才会只渲染指定模型。

## 2. 效果样图

### 模型示例

| 模型 | 灰模 | 灰模 PNG | 默认黑模 | 黑模 PNG | 白模 | 白模 PNG | 绿幕 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 16MANDBS111 | ![16MANDBS111 gray model](images/vehicle_16MANDBS111_gray_model.png) | ![16MANDBS111 gray png](images/vehicle_16MANDBS111_gray_png.png) | ![16MANDBS111 black model](images/vehicle_16MANDBS111_black_model.png) | ![16MANDBS111 black png](images/vehicle_16MANDBS111_black_png.png) | ![16MANDBS111 white model](images/vehicle_16MANDBS111_white_model.png) | ![16MANDBS111 white png](images/vehicle_16MANDBS111_white_png.png) | ![16MANDBS111 greenscreen](images/vehicle_16MANDBS111_greenscreen.png) |
| fordc72 | ![fordc72 gray model](images/vehicle_fordc72_gray_model.png) | ![fordc72 gray png](images/vehicle_fordc72_gray_png.png) | ![fordc72 black model](images/vehicle_fordc72_black_model.png) | ![fordc72 black png](images/vehicle_fordc72_black_png.png) | ![fordc72 white model](images/vehicle_fordc72_white_model.png) | ![fordc72 white png](images/vehicle_fordc72_white_png.png) | ![fordc72 greenscreen](images/vehicle_fordc72_greenscreen.png) |
| zondarevob | ![zondarevob gray model](images/vehicle_zondarevob_gray_model.png) | ![zondarevob gray png](images/vehicle_zondarevob_gray_png.png) | ![zondarevob black model](images/vehicle_zondarevob_black_model.png) | ![zondarevob black png](images/vehicle_zondarevob_black_png.png) | ![zondarevob white model](images/vehicle_zondarevob_white_model.png) | ![zondarevob white png](images/vehicle_zondarevob_white_png.png) | ![zondarevob greenscreen](images/vehicle_zondarevob_greenscreen.png) |
| LD_Bolide | ![LD_Bolide gray model](images/vehicle_LD_Bolide_gray_model.png) | ![LD_Bolide gray png](images/vehicle_LD_Bolide_gray_png.png) | ![LD_Bolide black model](images/vehicle_LD_Bolide_black_model.png) | ![LD_Bolide black png](images/vehicle_LD_Bolide_black_png.png) | ![LD_Bolide white model](images/vehicle_LD_Bolide_white_model.png) | ![LD_Bolide white png](images/vehicle_LD_Bolide_white_png.png) | ![LD_Bolide greenscreen](images/vehicle_LD_Bolide_greenscreen.png) |

### 武器示例

| 模型 | 白底样图 | 透明 PNG |
| --- | --- | --- |
| w_ar_kajszs | ![w_ar_kajszs white](images/weapon_w_ar_kajszs_white.png) | ![w_ar_kajszs cutout](images/weapon_w_ar_kajszs_cutout.png) |
| w_ar_kajszs_mag1 | ![w_ar_kajszs_mag1 white](images/weapon_w_ar_kajszs_mag1_white.png) | ![w_ar_kajszs_mag1 cutout](images/weapon_w_ar_kajszs_mag1_cutout.png) |
| w_sg_beanbagshotgun | ![w_sg_beanbagshotgun white](images/weapon_w_sg_beanbagshotgun_white.png) | ![w_sg_beanbagshotgun cutout](images/weapon_w_sg_beanbagshotgun_cutout.png) |

### 饰品示例

| 模型 | 棚拍样图 | 透明 PNG |
| --- | --- | --- |
| labubu_clap | ![labubu_clap studio](images/accessory_labubu_clap_white.png) | ![labubu_clap cutout](images/accessory_labubu_clap_cutout.png) |
| shibanita | ![shibanita white](images/accessory_shibanita_white.png) | ![shibanita cutout](images/accessory_shibanita_cutout.png) |
| keroppi | ![keroppi white](images/accessory_keroppi_white.png) | ![keroppi cutout](images/accessory_keroppi_cutout.png) |

每类只放 3 个例子，实际输出会按输入目录内所有可导入模型生成。

## 3. 推荐命令

直接把文件夹交给入口，默认扫描全部类型并使用黑模输出透明裁切图：

```cmd
render_folder.cmd "D:\fivem\TestVeh"
```

等价的 Python 命令：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --asset-types all --workers 2 --force --cutout
```

只渲染武器包里的全部武器模型：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --asset-types weapon --workers 2 --force --cutout
```

只渲染饰品包里的全部饰品模型：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --asset-types accessory --workers 2 --force --cutout
```

只渲染指定模型：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --model w_ar_kajszs --cutout
```

## 4. 支持资源类型

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

说明：

- `.yft` / `.ydr` 遇到同名 `_hi` 或 `+hi` 时优先使用高模。
- 一个压缩包里多个 `.ydr` 会全部生成任务，例如武器主体、弹匣、饰品模型都会输出 PNG。
- `weapon/accessory/prop` 会按路径和模型名分类过滤；`drawable/all` 不过滤 `.ydr`。

## 5. 透明图输出

`--cutout` 模式的根目录 PNG 会像 Photoshop“裁切透明像素”一样，按 8 位 PNG 中所有非零 alpha 像素精确裁切：

```text
_vehicle_renders\model.png
```

默认 `--key-padding 0` 不保留任何透明边距，完整画布保存在 `_alpha`。需要给裁剪结果留边时可加：

```powershell
--key-padding 12
```
需要设定裁切 PNG 的最小分辨率时使用 `--cutout-width` 和 `--cutout-height`；任一边不足会等比放大，不会缩小已有大图。

所有模型统一按实际投影边界自适应取景，只保留防止零尺寸的极小下限。

同时保留：

```text
_vehicle_renders\_alpha\model.png        # 完整画布透明渲染
_vehicle_renders\_greenscreen\model.png  # 绿幕预览
```

## 6. 贴图和缺失报告

每次渲染后生成：

```text
_vehicle_renders\_texture_report.txt
_vehicle_renders\_texture_report.json
```

报告会列出每个模型的贴图命中、缺失纹理名、本地 `.ytd` 是否存在。例子：

```text
missing: color_d, color_n, color_s
note: no local YTD textures were extracted; add the correct .ytd next to the model or pass --shared-ytd.
```

如果出现这种情况，把正确 `.ytd` 放到模型同目录，或加：

```powershell
--shared-ytd "D:\path\textures.ytd"
```

损坏 DDS 会被跳过，其他贴图和模型继续渲染，日志里会显示 `skipped corrupt DDS`。

如果日志显示 `磁盘空间不足` 或 `No space left on device`，请清理工具箱所在盘/输出盘，至少保留 1 GB 后重试。新版不会再把 RPF 和 YTD 临时文件写入 `C:\Users\...\Temp`。

工具不会创建额外点光源补光；明确的警灯/自发光材质只按原材质颜色写入 emission，不按名字强制改成红/橙。

## 7. 常用参数

```powershell
--workers 4
--force
--skip-existing
--width 1600 --height 1000
--cutout-width 1920 --cutout-height 1080
--yaw 135 --elevation 26
--floor-gap 0.2
--model-tone black
--model-tone gray
--model-tone white
--no-special-lights
--key-padding 0
```

未传 `--yaw` 时，带同名 YCD 动画的饰品姿态模型使用 155 度正面特写，普通饰品和其他模型保持 135 度；显式传入 `--yaw` 会覆盖自动值。

`--model-tone black` 是默认值；`gray/white/black` 都只调整模型原生主色、副色、珠光和明确的车漆材质，不覆盖或暗化漫反射贴图。玻璃、灯光、轮胎、轮毂、金属、碳纤维、塑料、内饰和贴花不参与改色。

Cycles 渲染前会把 Sollumz 数值参数烘焙为标准 Blender 节点常量，已有 Base Color 上游贴图链不会被补图逻辑覆盖。武器材质若把 `_dpal` / palette / tint 调色板误接到 Base Color，会改用本地漫反射贴图（例如 `map.png`）；`_nm` / `_spec` 按 Non-Color 数据读取。

## 8. 输出结构

```text
_vehicle_renders/
  model.png
  _alpha/model.png
  _greenscreen/model.png
  _textures/model/*.png
  _jobs/model.json
  _logs/model.log
  _logs/model.textures.log
  _logs/model.textures.bind.json
  _texture_report.txt
  _texture_report.json
```

## 9. 常见问题

### 一个压缩包里多个模型，只出了一张怎么办

不要传 `--model`。`--model` 是过滤条件，会只渲染指定模型。要渲染武器包内所有武器：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --asset-types weapon --force --cutout
```

### PNG 四周还有透明边

正常 `--cutout` 的根目录 PNG 会精确裁掉完全透明像素，`_alpha` 保留完整画布；`--key-padding` 大于 0 时才增加留边。旧版本结果请使用 `--force` 重跑。

### 模型导入失败

看 `_logs\模型名.log`。如果是 Sollumz `[DECOMPRESS_FAILED]`，说明该 `.ydr` 格式当前导入器读不了；工具会记录失败，不会影响其他模型继续渲染。

### 贴图缺失

看 `_texture_report.txt`，按缺失的贴图名补 `.ytd`。

## 10. 内置依赖

```text
vehicle_renderer\
  vehshare.ytd
  tools\
    7z.exe
    7z.dll
    RpfTools.exe
    YtdTools.exe
    CodeWalker.Core.dll
    texconv.exe
```

只提交运行必需文件，不提交 CodeWalker/RpfTools/YtdTools 的源码工程。

## CK免费工具箱客户端入口

如果不想手写命令，可以直接打开客户端工具箱：

```powershell
D:\fivem\ck_free_toolbox\start_toolbox.cmd
```

工具箱不使用后端服务。它在本机客户端里扫描所有模型资源，启动 `render_all_vehicles.py`、读取日志并更新进度。第一页签是“模型自动截图”，渲染命令使用 `--asset-types all`；默认输入为 `D:\fivem\TestVeh`，默认输出为 `D:\fivem\TestVeh\_vehicle_renders`。

## 载具自动拼装

载具资源同时包含 `vehicles.meta`、`carvariations.meta`、`carcols.meta` 和多个分离 `.yft` 时，默认 `--vehicle-assembly auto` 会：

1. 从元数据确认基车，避免把轮拱、Logo、内饰和改装件当成独立载具截图。
2. 从 `carvariations.meta` 找到对应 kit。
3. 从 `carcols.meta` 读取 `visibleMods`、`linkedModels`、`type`、`bone` 和 `turnOffBones`。
4. 每种 `VMT_*` 部位只选择一个方案，关联件一起显示；被该方案替换的基车零件关闭，其他可显示 extras 保留。带贴图、特效或发光的零件和图案全部保留；特效壳和投影平面按透明 PNG 图层显示，使用原 Alpha 或贴图亮度去除黑底，整车覆盖层最大不透明度为 0.15。原生发光保留并限制最高强度为 2.4，避免覆盖车漆纹理。与主 `bodyshell` 尺寸和中心都重叠的实体 `extra_N` 按“同部位只显示一套”去重；`requiredExtras` 和改件正在使用的 extra 不隐藏。
5. 逐件导入 Sollumz，按基车骨骼挂接，再进入现有贴图、材质、灯光、取景和 PNG 裁切流程。

`LD_Bolide` 实测命令：

```powershell
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh\LD_Bolide.zip" --model LD_Bolide --asset-types vehicle --cutout --force --save-blend
```

![LD_Bolide assembled](images/vehicle_LD_Bolide_assembled.png)

模式和选择参数：

```text
--vehicle-assembly auto       检测到 kit 时自动使用 showcase，默认
--vehicle-assembly showcase  每种 VMT_* 类型选择第一个可用方案
--vehicle-assembly all       导入套件中所有存在的改装模型
--vehicle-assembly none      不拼装，只渲染基车
--vehicle-mod VMT_GRILL:2    选择某类改装的第 2 个方案，可重复
--vehicle-mod LD_Bolide_cb   直接指定模型名，可重复
--vehicle-kit <kitName>      覆盖 carvariations.meta 中的 kit
--vehicle-attach preserve    按骨骼挂接并保留资源世界坐标，默认
--vehicle-attach none        导入部件但不建立骨骼父级
```

`--save-blend` 会同时输出 `_jobs\模型名.blend`，用于继续在 Blender 中检查或编辑拼装场景。
