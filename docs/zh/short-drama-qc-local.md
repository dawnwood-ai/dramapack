# 交付前如何在本地给短剧做质检

每集成片上传前跑一遍 `dramapack audit`。它在你自己的机器上、不用注册账号，检查平台审核和观众最先发现的问题：**黑屏、字幕和台词对不上、节奏和响度是否达到市场基准**；如果你接上自己的视觉模型，还能查 **AI 画面瑕疵和内容合规风险**。每项给出绿 / 黄 / 红，红表示"上线前要有人看一眼"。

```bash
pip install "dramapack[speech]"        # speech 扩展 = faster-whisper，字幕检查要用
dramapack audit out/episodes/01.mp4 --cut input/01.mp4
dramapack audit out/episodes/*.mp4 --json > qc.json     # 整部剧，机器可读
```

默认**不发出任何网络请求**：只有同时加了 `--vlm` **并且**配置了模型端点（端点本身也可以是本地模型）才会联网。

## 查什么

| 检查项 | 做法 | 分级 |
|---|---|---|
| 黑屏 | ffmpeg `blackdetect`（和镜头检测同一遍解码） | 片中黑屏 >= 0.5 s 红，更短的片中黑屏黄；片头/片尾 <= 1 s 绿（淡入淡出），更长黄 |
| 字幕时间轴 | SRT 字幕条对 whisper 语音段：起点偏移中位数（`sub_drift`）、90 分位偏移（`sub_offset_p90`） | 偏移 <= 0.3 s 绿，> 0.8 s 红；p90 <= 0.5 s 绿，> 1.0 s 红 |
| 有字幕无人声 | `sub_orphan_share`：剪掉了台词却没删字幕。`[音效]`/`(音乐)` 类字幕不算 | <= 5% 绿，> 20% 红 |
| 有人声无字幕 | `sub_uncovered_s`：没人打字幕的台词秒数 | <= 1.5 s 绿，> 4 s 红 |
| 错别字 / 字幕和台词不符 | 逐条字幕与该时段听到的词做归一化编辑距离，外加逐词近似比对（如 `rihgt` 与 `right`；中日韩字幕只做整句比对），仅在字幕语言与配音语言一致时进行 | 整句相似度 < 0.6 或单词差 1-2 个字母：标黄（语音识别会听错人名，永不判红） |
| 节奏、台词密度、响度、拼接点、片尾卡 | 原有基准指标（见 [reference](../reference.md#audit-thresholds)） | 见阈值表 |
| 画面瑕疵（可选，`--vlm`） | 你的视觉模型看抽帧：脸/手畸变、多肢、画面文字乱码、伪影、同一角色在帧间换脸 | 畸变 / 乱码 / 换脸红；伪影黄 |
| 内容合规（可选，`--vlm`） | 色情、血腥暴力、未成年人处于危险情境、自残 | `mild` 黄，`explicit` 红。只是提示复核，不是法律意见 |
| 首帧钩子（可选，`--vlm`） | 第 0 帧有没有人、文字是否清晰 | 最多黄（建议） |

字幕来源：`--srt 文件`，或视频旁同名 `.srt`（`episodes/01.mp4` + `episodes/01.srt`，正是 `dramapack package` 的输出）。加 `--cut` 时，字幕、钩子和 VLM 检查都在母带上跑，因为交付出去的是母带的画面和字幕时间轴。

**不覆盖：口型同步。** 静帧看不出嘴型和声音是否对上，dramapack 不声称能查。对白特写请自己过一遍。

## 本地工具 vs 云端质检服务

短剧云端质检服务已经出现，例如昆仑万维的 SkyProduction 短剧质检（[2026-09 发布报道](https://www.qbitai.com/2026/09/494043.html)），上传成片后检查字幕、音画和内容合规并出报告。两种方式各有用处，区别在于活在哪里干：

| | dramapack 0.2（本地） | 云端质检服务（如 SkyProduction） |
|---|---|---|
| 有声无字幕 / 有字幕无声 | 有（需 `[speech]` 扩展） | 有 |
| 字幕时间轴偏移 | 有 | 有 |
| 错别字 | 部分：仅同语言字幕，黄色提示 | 有 |
| 字幕格式 / 拆轴规范 | 无 | 有 |
| 黑屏 | 有 | 有 |
| 黑边、掉帧、色调一致性、水印 | 无（只查片尾定格） | 有 |
| 响度 | 有：-14 LUFS 测量、平均音量、拼接点跳变 | 音频检查（音量稳定、单声道） |
| AI 画面瑕疵（手、脸、换脸、乱码） | 自带视觉模型（`--vlm`） | 画面文字异常、AI 标识 |
| 内容合规提示 | 自带视觉模型（`--vlm`） | 有 |
| 口型同步 | **无** | 以该服务当前说明为准 |
| 市场基准（创作者激励时长、镜头长度、台词密度、片尾卡时长） | 有 | 未宣传 |
| 费用 | 免费（Apache-2.0）；VLM 调用由你的模型服务商计费，本地模型免费 | 按时长计费（据报道三项全开约每 100 分钟 12.4 元） |
| 账号 / 上传 | 不需要；文件留在本地（抽帧只发给你配置的 VLM 端点） | 需要账号、上传成片 |
| 自动化 | CLI `--json`、Python API、给 AI Agent 用的 MCP 服务 | 网页流程、可下载报告 |

## 自带视觉模型

VLM 检查走 OpenAI 兼容的 Chat Completions 协议，图片用 base64 `data:` URI，只用 Python 标准库。每次运行用 `--vlm`（CLI）或 `vlm=True`（Python / MCP）开启，端点写在环境变量里：

```bash
export DRAMAPACK_VLM_BASE_URL=...   # OpenAI 兼容 base URL（不含 /chat/completions）
export DRAMAPACK_VLM_API_KEY=...    # 服务商密钥；本地服务填任意非空字符串
export DRAMAPACK_VLM_MODEL=...      # 支持图片输入的模型
# 可选：DRAMAPACK_VLM_TIMEOUT=120（每次请求秒数），DRAMAPACK_VLM_RETRIES=2
dramapack audit ep01.mp4 --vlm --vlm-max-frames 12
```

加了 `--vlm` 但三个变量没配齐时，审片照常进行，`skipped` 里会写 `VLM checks skipped: set ...`。密钥只放在发往你的 base URL 的 `Authorization` 头里，所有报错和日志都会把它抹掉。

模型名变化很快：请从服务商的模型列表里选当前**支持图片输入**的模型。

**OpenAI**

```bash
export DRAMAPACK_VLM_BASE_URL=https://api.openai.com/v1
export DRAMAPACK_VLM_API_KEY="$OPENAI_API_KEY"
export DRAMAPACK_VLM_MODEL=<支持视觉的 GPT 模型>
```

**Anthropic（Claude，OpenAI SDK 兼容端点）**

```bash
export DRAMAPACK_VLM_BASE_URL=https://api.anthropic.com/v1
export DRAMAPACK_VLM_API_KEY="$ANTHROPIC_API_KEY"
export DRAMAPACK_VLM_MODEL=<Claude 模型名>
```

Anthropic 说明该兼容层主要用于测试和对比。请用绑定了 workspace 的密钥（dramapack 不发额外请求头）。dramapack 不传 `temperature` 和 `response_format`，该端点对这两个参数有限制或会忽略。

**Google Gemini（OpenAI 兼容）**

```bash
export DRAMAPACK_VLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
export DRAMAPACK_VLM_API_KEY="$GEMINI_API_KEY"
export DRAMAPACK_VLM_MODEL=<支持图片输入的 Gemini 模型>
```

**阿里云百炼 / DashScope（通义千问 VL，compatible-mode）**

```bash
# 国际（新加坡）：
export DRAMAPACK_VLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
# 中国内地（北京）：
# export DRAMAPACK_VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export DRAMAPACK_VLM_API_KEY="$DASHSCOPE_API_KEY"
export DRAMAPACK_VLM_MODEL=<Qwen-VL 模型，如 qwen3-vl 系列>
```

百炼的密钥只能在创建它的地域使用。新账号控制台可能显示按 workspace 区分的端点（`https://{WorkspaceId}.<地域>.maas.aliyuncs.com/compatible-mode/v1`），以控制台为准。

**火山方舟（豆包视觉模型）**

```bash
export DRAMAPACK_VLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
export DRAMAPACK_VLM_API_KEY="$ARK_API_KEY"
export DRAMAPACK_VLM_MODEL=<豆包视觉模型 ID，或你的推理接入点 ID ep-...>
```

哪些豆包模型支持图片输入，请以服务商文档为准。

**Ollama（完全离线）**

```bash
ollama pull qwen3-vl:8b
export DRAMAPACK_VLM_BASE_URL=http://localhost:11434/v1
export DRAMAPACK_VLM_API_KEY=ollama          # Ollama 不校验，但不能为空
export DRAMAPACK_VLM_MODEL=qwen3-vl:8b
```

**vLLM（完全离线）**

```bash
vllm serve <视觉语言模型>                      # 服务地址 http://localhost:8000/v1
export DRAMAPACK_VLM_BASE_URL=http://localhost:8000/v1
export DRAMAPACK_VLM_API_KEY=EMPTY           # 或 vllm serve --api-key 的值
export DRAMAPACK_VLM_MODEL=<所服务的模型名>
```

### 费用与发送内容

每集抽：第 0 帧、6 张均匀分布的帧、每个检测到的剪切点后 0.3 s 一张，总数受 `--vlm-max-frames`（默认 12）限制，长边缩到 640 px（每张约 40-60 KB JPEG）。每集三次请求：画面瑕疵和合规各看全部抽帧，钩子只看第 0 帧。调用模型前会在 stderr 打印请求数和帧数估算，JSON 结果的 `vlm` 字段里也有。

### 视觉模型按什么标准判

提示词来自 AI 短剧生产中实际使用的验片器，保留了它的校准：

- 答 `yes` 必须有具体证据（哪一帧、画面哪里、看到了什么）；`unsure` 只用于"相关部位太小、虚焦或不在画面内"。`unsure` 永不判红。
- 光照、角度、表情、妆容变化不算换脸；只换了衣服不能证明换了人；过肩镜头里的肩膀不算多出来的人；运动模糊、颗粒和风格化不算伪影；清晰的招牌和正确的字幕不算乱码。
- 合规只看画面上看得见的，不脑补剧情：一巴掌是 `mild` 暴力，可见伤口或血腥是 `explicit`。
- 回复必须是严格 JSON，每个问题都要有合法答案。格式不对会重问一次，仍不对就记到 `vlm_errors`、不评级：坏掉的检查器既不卡交付，也不会悄悄放行。

视觉模型两个方向都可能出错。VLM 判红的意思是"看一下这一帧"，合规决定要有人拍板。

## 给 AI Agent 用

MCP 的 `audit` 工具支持 `speech`、`align`、`srt`、`srt_lang`、`vlm`、`vlm_max_frames` 参数。VLM 端点和密钥只从 MCP 服务的环境变量读取，Agent 能开关检查，但不能把它指向别处。见 [ai-agent-mcp.md](../ai-agent-mcp.md) 和 [reference](../reference.md)。
