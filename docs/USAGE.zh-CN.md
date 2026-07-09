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
6. 输出白底预览、绿幕预览、透明裁切 PNG 和贴图报告。

不传 `--model` 时，一个压缩包里有多少可导入模型就渲染多少个；传 `--model` 才会只渲染指定模型。

## 2. 效果样图

### 车辆示例

| 模型 | 默认灰模 | 灰模 PNG | 黑模 | 黑模 PNG | 白模 | 白模 PNG | 绿幕 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 16MANDBS111 | ![16MANDBS111 gray model](images/vehicle_16MANDBS111_gray_model.png) | ![16MANDBS111 gray png](images/vehicle_16MANDBS111_gray_png.png) | ![16MANDBS111 black model](images/vehicle_16MANDBS111_black_model.png) | ![16MANDBS111 black png](images/vehicle_16MANDBS111_black_png.png) | ![16MANDBS111 white model](images/vehicle_16MANDBS111_white_model.png) | ![16MANDBS111 white png](images/vehicle_16MANDBS111_white_png.png) | ![16MANDBS111 greenscreen](images/vehicle_16MANDBS111_greenscreen.png) |
| fordc72 | ![fordc72 gray model](images/vehicle_fordc72_gray_model.png) | ![fordc72 gray png](images/vehicle_fordc72_gray_png.png) | ![fordc72 black model](images/vehicle_fordc72_black_model.png) | ![fordc72 black png](images/vehicle_fordc72_black_png.png) | ![fordc72 white model](images/vehicle_fordc72_white_model.png) | ![fordc72 white png](images/vehicle_fordc72_white_png.png) | ![fordc72 greenscreen](images/vehicle_fordc72_greenscreen.png) |
| zondarevob | ![zondarevob gray model](images/vehicle_zondarevob_gray_model.png) | ![zondarevob gray png](images/vehicle_zondarevob_gray_png.png) | ![zondarevob black model](images/vehicle_zondarevob_black_model.png) | ![zondarevob black png](images/vehicle_zondarevob_black_png.png) | ![zondarevob white model](images/vehicle_zondarevob_white_model.png) | ![zondarevob white png](images/vehicle_zondarevob_white_png.png) | ![zondarevob greenscreen](images/vehicle_zondarevob_greenscreen.png) |

### 武器示例

| 模型 | 白底样图 | 透明裁切 PNG |
| --- | --- | --- |
| w_pi_fn509t | ![w_pi_fn509t white](images/weapon_w_pi_fn509t_white.png) | ![w_pi_fn509t cutout](images/weapon_w_pi_fn509t_cutout.png) |
| w_sg_beanbagshotgun | ![w_sg_beanbagshotgun white](images/weapon_w_sg_beanbagshotgun_white.png) | ![w_sg_beanbagshotgun cutout](images/weapon_w_sg_beanbagshotgun_cutout.png) |
| w_pi_c17s | ![w_pi_c17s white](images/weapon_w_pi_c17s_white.png) | ![w_pi_c17s cutout](images/weapon_w_pi_c17s_cutout.png) |

### 饰品示例

| 模型 | 白底样图 | 透明裁切 PNG |
| --- | --- | --- |
| labubu_clap | ![labubu_clap white](images/accessory_labubu_clap_white.png) | ![labubu_clap cutout](images/accessory_labubu_clap_cutout.png) |
| shibanita | ![shibanita white](images/accessory_shibanita_white.png) | ![shibanita cutout](images/accessory_shibanita_cutout.png) |
| keroppi | ![keroppi white](images/accessory_keroppi_white.png) | ![keroppi cutout](images/accessory_keroppi_cutout.png) |

每类只放 3 个例子，实际输出会按输入目录内所有可导入模型生成。

## 3. 推荐命令

渲染全部支持资源：

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
python "D:\fivem\vehicle_renderer\render_all_vehicles.py" "D:\fivem\TestVeh" --model w_pi_fn509t --cutout
```

## 4. 支持资源类型

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

说明：

- `.yft` / `.ydr` 遇到同名 `_hi` 或 `+hi` 时优先使用高模。
- 一个压缩包里多个 `.ydr` 会全部生成任务，例如武器主体、弹匣、饰品模型都会输出 PNG。
- `weapon/accessory/prop` 会按路径和模型名分类过滤；`drawable/all` 不过滤 `.ydr`。

## 5. 透明图裁切

`--cutout` 模式会输出透明 PNG：

```text
_vehicle_renders\model.png
```

最终 PNG 默认 `--key-padding 0`，会根据 alpha 边界裁掉所有透明空白像素。需要给图片留边时再加：

```powershell
--key-padding 12
```

同时保留：

```text
_vehicle_renders\_alpha\model.png        # 原始透明渲染
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

工具不会创建额外点光源补光；明确的警灯/自发光材质只按原材质颜色写入 emission，不按名字强制改成红/橙。

## 7. 常用参数

```powershell
--workers 4
--force
--skip-existing
--width 1600 --height 1000
--yaw 135 --elevation 26
--floor-gap 0.2
--model-tone gray
--model-tone white
--model-tone black
--no-special-lights
--key-padding 0
```

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

默认已经是 `--key-padding 0`。如果之前用旧版本生成过，使用 `--force` 重跑。

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

工具箱不使用后端服务。它在本机客户端里扫描载具、武器、饰品、道具等模型资源，启动 `render_all_vehicles.py`、读取日志并更新进度。第一页签是“模型自动截图”，渲染命令使用 `--asset-types all`；默认输入为 `D:\fivem\TestVeh`，默认输出为 `D:\fivem\TestVeh\_vehicle_renders`。
