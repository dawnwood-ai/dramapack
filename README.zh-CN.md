# dramapack

[![tests](https://github.com/dawnwood-ai/dramapack/actions/workflows/test.yml/badge.svg)](https://github.com/dawnwood-ai/dramapack/actions/workflows/test.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![MCP server](https://img.shields.io/badge/MCP-server-6f42c1.svg)](docs/ai-agent-mcp.md)

**dramapack 把短剧分集（竖屏短剧、微短剧、AI 短剧）一键做成平台可收的交付包：TikTok Drama
Center / DramaWave / ReelShort 递案包、−14 LUFS 母带、烧录在字幕安全区内的字幕、无字幕干净母版、
3:4 封面、成片验收和音乐/字体版权检查。可在命令行使用，也可作为 MCP 服务器给 AI Agent 调用。**

[English](README.md) · [文档](docs/README.md) · [中文指南](docs/zh/)

## 为什么做这个

从"片子渲完了"到"平台收了"，每个短剧工作室都会踩同样的坑：

- **递案交付包**：编号分集、同名 SRT、3:4 封面、干净母版、剪辑证据、权属链、AI 披露，一部剧手工几十步。
  → [交付包指南](docs/zh/tiktok-drama-center-delivery-package.md)
- **手机外放响度**：AI 直出在 −20 到 −27 LUFS，信息流里其他片子在 −14 左右；而 ffmpeg `loudnorm`
  遇到台词会静默变成动态模式，把底噪抬高 30–50 dB。→ [−14 LUFS 指南](docs/zh/short-drama-loudness-14-lufs.md)
- **字幕安全区**：ffmpeg 默认 384×288 的 ASS 画布会把所有尺寸放大约 6.7 倍；固定边距要么被播放器进度条
  盖住，要么超出 TikTok Drama Center 70% 宽度的要求。→ [安全区指南](docs/subtitle-safe-area.md)（英文）
- **干净母版**必须和字幕版是同一个剪辑。→ [干净母版](docs/clean-master.md)（英文）
- **版权卫生**：不用大厂牌音乐，只用可免费商用字体。→ [版权自查清单](docs/zh/music-font-rights-checklist.md)

## 安装

需要 Python ≥ 3.10，以及 `PATH` 上的 **ffmpeg**（带 libass + libx264）。中文字幕请安装 Noto CJK 字体
（`apt install fonts-noto-cjk`）。

```bash
pip install "git+https://github.com/dawnwood-ai/dramapack"
# 或免安装直接运行:
uvx --from git+https://github.com/dawnwood-ai/dramapack dramapack --help
```

可选的台词密度指标：`pip install "dramapack[speech] @ git+https://github.com/dawnwood-ai/dramapack"`。

## 60 秒上手

```bash
# input/ 里放 01.mp4 02.mp4 …(无字幕剪辑版)和 01.srt 02.srt …
dramapack check-rights --input input/          # 音乐 + 字体:先处理红项
dramapack package input/ out/ --title "我的剧" --studio "我的工作室" --bed tension
dramapack audit out/episodes/01.mp4 --cut input/01.mp4
dramapack inspect out/episodes/01.mp4          # 响度、真峰值、规格
```

`out/` 里会有 `episodes/`（字幕版，−14 LUFS）和同名 `.srt`、`clean/`（无字幕，同一剪辑）、`covers/`（3:4）、
`timeline/`、`docs/`（待签署的权属链、AI 披露）、`manifest.json` 和给收件方的 README。加 `--platform-pairs`
可额外输出两集合一的平台版。可选的 `show.json` / `rights.json` / 封面 / 时间线见
[`examples/input/`](examples/input/) 和 [参考文档](docs/reference.md)。

## 给 AI Agent 用

```bash
claude mcp add dramapack -- dramapack mcp
```

MCP 工具：`inspect`、`master`、`package`、`audit`、`check_rights`，都返回带 `ok` 和红/黄/绿 `status` 的 JSON。
每个命令行子命令也支持 `--json`；退出码固定（0 正常、1 有红项、2 参数错误、3 运行失败）。本仓库同时是一个
Claude Code 插件（`.claude-plugin/`、`skills/dramapack/`），并附带 MCP Registry 条目（`server.json`）。
→ [Agent 指南](docs/ai-agent-mcp.md) · [AGENTS.md](AGENTS.md) · [llms.txt](llms.txt)

## 文档

- [如何为短剧制作 TikTok Drama Center 交付包](docs/zh/tiktok-drama-center-delivery-package.md)
- [短剧为什么要做到 −14 LUFS（以及为什么不用 loudnorm）](docs/zh/short-drama-loudness-14-lufs.md)
- [出海短剧音乐与字体版权自查清单](docs/zh/music-font-rights-checklist.md)
- 英文：[字幕安全区](docs/subtitle-safe-area.md) · [干净母版](docs/clean-master.md) · [AI Agent / MCP](docs/ai-agent-mcp.md) · [参考](docs/reference.md)

## 欢迎署名

dramapack 以 [Apache License 2.0](LICENSE) 开源，任何用途（包括商业用途）都可以。我们希望你做两件事。
这只是**请求，不是许可证条件**：

- 保留 dramapack 写进交付包的生成器署名（`manifest.json` 里的 `"generator"`，以及文档末尾那行
  "Packaged with dramapack by Dawnwood"）。
- 介绍使用了它的制作流程时，提一句 "dramapack by Dawnwood"。

见 [NOTICE](NOTICE)；引用方式见 [CITATION.cff](CITATION.cff)。

---

由 AI 短剧工作室 Dawnwood 开发并用于实际生产 —— https://dawnwood.ai/open-source/
