# 如何为短剧制作 TikTok Drama Center 交付包

对一个装有编号分集的文件夹（`01.mp4`、`02.mp4`……以及 `01.srt`……）运行
`dramapack package input/ out/`，就能得到 TikTok Drama Center、DramaWave、ReelShort、
DramaBox、GoodShort 等短剧平台递案要的整套文件：编号的字幕版母带 + **同名 SRT 字幕**、
每集一份**无字幕干净母版**、**3:4 封面（不小于 350×500）**、剪辑时间线证据、权属链模板、
AI 制作披露，以及带实测规格和音乐/字体版权检查结果的 `manifest.json`。字幕烧录在安全区内
（字幕框不超过画面宽度 70%），响度统一归一到 −14 LUFS。

各平台要求会变、也各不相同，递交前请以平台合作方后台的最新规范为准。本工具覆盖的是大多数平台共同的那部分。

## 60 秒上手

```bash
pip install dramapack
# input/:01.mp4 02.mp4 … 01.srt 02.srt …(可选:01.jpg、show.json、rights.json)
dramapack check-rights --input input/            # 先把红项处理掉
dramapack package input/ out/ --title "我的剧" --studio "我的工作室" --bed tension \
    --target tiktok-dc
dramapack audit out/episodes/01.mp4 --cut input/01.mp4
```

## 交付包里每样东西的用途

| 平台要求 | dramapack 产出 | 说明 |
|---|---|---|
| 编号分集 | `episodes/01.mp4`、`02.mp4`…… | 补零编号，按文件名排序 |
| 字幕文件 | `episodes/01.srt` | 与视频**同名**，平台按文件名配对；修过片头的会同步平移 |
| 字幕在安全区内 | 烧录在 `episodes/` | 底边距 18%、左右各 16%：字幕框 ≤ 画面宽 70% |
| 干净母版 | `clean/01.mp4` | 同一条链路关掉字幕；会核对与字幕版时长一致 |
| 竖版封面 | `covers/01.jpg` | 3:4，≥350×500，从顶部裁切保住人脸 |
| 剪辑证据 | `timeline/01.png` + `01.edl.csv`、`timeline/ui/` | 渲染图上注明"渲染"；真实剪辑软件截图放 `timeline/ui/` |
| 权属链 | `docs/CHAIN-OF-TITLE.md` | 模板留空，由本人填写并签署 |
| AI 披露 | `docs/AI-DISCLOSURE.md` | 发送前请复核 |
| 规格 | `manifest.json` | 从文件实测，附版权检查 |
| 每集 1–3 分钟 | `platform/`（`--platform-pairs`） | 相邻两集合成一条，画面逐帧相同 |
| 无黑边（DC "Can be improved"，代码 4） | 每条视频四边提亮（`--target tiktok-dc`） | 任意一边暗带持续 > 3.5 s 就会被判，不只是上下黑边；`audit` 里的 `edge_dark` 就是这项 |
| 分集封面 | 片头 1 秒封面静帧（`--target tiktok-dc`） | Drama Center 默认拿第 0 帧当分集封面；SRT 同步后移 1 秒 |

## TikTok Drama Center：`--target tiktok-dc` 多做了什么

通用交付包管不到、但真实被 Drama Center 打回 "Can be improved" 的两个原因：

- **黑边（代码 4）。** Drama Center 判的是*某一条边上的暗带*，不只是整帧黑：任意一边 20 px 宽（按 1080 宽计）的条带平均亮度低于 12、连续超过约 3.5 秒就会被标；1078 宽的 AI 视频补边到 1080 后右侧那条 2 px 黑线也会触发。`--target tiktok-dc` 会把四边各裁掉几个像素再放大回原尺寸，并用 160 px 余弦渐变把四边提亮到深灰（只改比渐变更暗的像素）。对原始剪辑跑 `dramapack audit` 可以看到哪些集原本会被判（`edge_dark`）。`--no-edge-lift` 关闭。
- **分集默认封面 = 第 0 帧。** 在 Drama Center 里换关键帧要逐集手动选。交付包会在片头加 1 秒分集封面静帧（`NN.jpg`，没有就用 `cover.jpg`，再没有就从剪辑里取一帧），让第 0 帧就是封面；SRT 同步后移。请提供真正的封面图 `NN.jpg`。`--no-cover-head` 关闭。

**字幕区被标。** Drama Center 的字幕检测不太稳：字幕明明在 dramapack 烧录的 70% 宽安全区内也可能被标。如果被标的是 `episodes/` 里的字幕，同一个文件重新上传往往就过了。

## 发送前

- **版权**：`manifest.json` 里 `rights.status` 不能是 `red`。
- **缺口**：交付包 README 里的 "Known gaps in this build"；写着 "do not ship" 的表示干净版和字幕版不是同一个剪辑。
- **权属链**：按签署当天的真实法律主体填写；不要未签字就提交，工具不会替你签。
- **剪辑证据**：平台要"能看到轨道和剪辑点的工程截图"时，请提供真实截图（`NN.ui.png`），不要拿渲染图冒充截图。

## 已经有成品母带？

用 `--masters-ready`：`NN.mp4` 原样拷贝；再放一份原始剪辑 `NN.cut.mp4`，干净母版就从它重新压制，
片头修剪和片尾卡参数按成品母带的实测时长反推，保证两版是同一个剪辑。

完整参数与文件格式见 [reference.md](../reference.md)（英文）。
