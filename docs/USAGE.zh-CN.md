# 使用文档

作者：JACK  
联系方式：QQ 2518926462

## 1. 工具目标

`vehicle_renderer` 用于把 FiveM/GTA V 车辆资源批量渲染成 PNG。它会自动处理常见资源包格式，流程是：

1. 解包 `.zip` / `.rar` / `.7z`。
2. 解包找到的 `.rpf`。
3. 扫描 `.yft` 车辆模型。
4. 从车辆 `.ytd` 和 `vehshare.ytd` 提取贴图。
5. 调用 Blender/Sollumz 导入模型、绑定贴图并渲染。
6. 可选输出绿幕预览和透明裁切 PNG，透明图保留车漆高光、环境反射和半透明地面阴影。

## 效果样图

| 车型 | 白底样图 | 抠像后透明 PNG |
| --- | --- | --- |
| fordc72 | ![fordc72 white](images/fordc72_white.png) | ![fordc72 cutout](images/fordc72_cutout.png) |
| 10ttrsscpd | ![10ttrsscpd white](images/10ttrsscpd_white.png) | ![10ttrsscpd cutout](images/10ttrsscpd_cutout.png) |
| 16MANDBS111 | ![16MANDBS111 white](images/16MANDBS111_white.png) | ![16MANDBS111 cutout](images/16MANDBS111_cutout.png) |
| zondarevob | ![zondarevob white](images/zondarevob_white.png) | ![zondarevob cutout](images/zondarevob_cutout.png) |

白底样图用于 GitHub/文档直接预览，抠像后透明 PNG 用于实际贴图、网页展示或后期合成。

## 2. 推荐命令

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" ".\[Tool]\TestVeh" --workers 2 --force --cutout
```

最终 PNG：

```text
[Tool]\TestVeh\_vehicle_renders\*.png
```

`--cutout` 开启后，根目录 PNG 是已经裁切空白的透明图。

文档里的样图文件：

```text
docs\images\*_white.png     # 白底样图
docs\images\*_cutout.png    # 抠像后透明 PNG
```

## 3. 输入目录

支持直接放解包后的车辆资源：

```text
vehicle_pack/
  car_a/
    stream/
      car_a.yft
      car_a_hi.yft
      car_a.ytd
```

也支持把包直接丢进去：

```text
vehicle_pack/
  car_pack.zip
  another_pack.rar
  dlc.rpf
```

默认会自动解包。需要禁止时加：

```powershell
--no-unpack
```

## 4. 内置依赖

工具优先使用本仓库的运行文件：

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

这几个是运行必需文件。不要把 CodeWalker/RpfTools/YtdTools 的源码工程、调试文件、临时工程目录放进仓库。

## 5. 多线程

`--workers` 表示并发启动几个 Blender 后台进程：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --workers 4 --cutout
```

建议：

- 普通机器：`--workers 2`
- CPU/内存较强：`--workers 3` 或 `--workers 4`
- 内存不够或 Blender 崩溃时降低 workers

## 6. 常用参数

指定输出目录：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --out "D:\vehicle_images" --cutout
```

只渲染指定车型：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --model police --model sultan --cutout
```

强制重渲染：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --force --cutout
```

跳过已有 PNG：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --skip-existing --cutout
```

指定分辨率：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --width 1600 --height 1000 --cutout
```

调整角度：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --yaw 135 --elevation 26 --cutout
```

`--cutout` 默认已经使用偏亮 studio 灯光。需要微调曝光和灯光：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --cutout --exposure 0.75 --world-strength 0.78 --light-scale 1.85
```

降低地面，避免轮子被平面挡住：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --floor-gap 0.2
```

## 7. 绿幕和抠图

### 车辆渲染时直接输出透明 PNG

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" "D:\cars" --cutout
```

输出：

```text
_vehicle_renders/
  car_a.png          # 最终透明裁切 PNG
  _alpha/car_a.png   # 原始透明渲染
  _greenscreen/car_a.png
```

当前实现会用 Cycles studio 灯光渲染透明背景，再生成绿幕预览图。最终 PNG 会保留车漆高光、环境反射和半透明地面阴影，同时避免真正绿色背景反射到车漆、玻璃和镀铬材质上。

### 单独处理已有绿幕图片

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" --key-green "D:\green_pngs" --key-out "D:\cutout_pngs"
```

可调参数：

```powershell
--key-threshold 70
--key-padding 12
```

## 8. 输出结构

```text
_vehicle_renders/
  fordc72.png
  10ttrsscpd.png
  _alpha/
    fordc72.png
  _greenscreen/
    fordc72.png
  _textures/
    fordc72/
      *.png
  _jobs/
    fordc72.json
  _logs/
    fordc72.log
    fordc72.textures.log
```

## 9. 常见问题

### 图片发紫/发红

贴图没绑定成功。先确认：

- 车辆同目录有 `.ytd`。
- `vehicle_renderer\vehshare.ytd` 存在。
- `_logs\车型名.textures.log` 里没有 YtdTools 或 texconv 报错。

### 图片发白/过曝

`--cutout` 默认是偏亮 studio 灯光。如果某些白色车辆还是太亮，降低：

```powershell
--exposure 0.45 --world-strength 0.6 --light-scale 1.5
```

如果太暗，升高：

```powershell
--exposure 1.05 --world-strength 1.0 --light-scale 2.4
```

### 车轮少一边

部分车的 `.yft` 只导入单侧车轮。脚本会根据右侧碰撞体自动镜像补齐右侧车轮。

### 车轮被地面挡住

普通白底模式可以加：

```powershell
--floor-gap 0.2
```

`--cutout` 模式不使用实体地面，最终透明图不会被平面挡住。

### 解包失败

确认 `tools\7z.exe`、`tools\RpfTools.exe` 存在。也可以手动指定：

```powershell
--archive-tool "D:\tools\7z.exe" --rpf-tool "D:\tools\RpfTools.exe"
```

## 10. 测试结果

已用 `[Tool]\TestVeh` 验证：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" ".\[Tool]\TestVeh" --workers 2 --force --cutout
```

结果：

```text
[ok] fordc72
[ok] 10ttrsscpd
[ok] zondarevob
[ok] 16MANDBS111
Done. OK=4 FAIL=0
```
