# 出海短剧音乐与字体版权自查清单

把短剧交给海外分发方之前：**不用大厂牌音乐**（Sony、Universal、Warner 及其旗下厂牌，这些曲库在各平台都有
指纹自动认领）；音乐只用 **AI 生成或程序化生成、公有领域（发表超过 50 年，且录音本身也是公有领域）、
或有书面授权的小众/独立音乐人作品**；凡是烧进画面的字体，**只用可免费商用的**（或有商业授权证明的）。
`dramapack check-rights` 会对你声明的每段音乐和每个烧录字体打红/黄/绿，结果写进交付包的 `manifest.json`。

```bash
dramapack check-rights input/rights.json --input input/
```

这是卫生检查，不是法律意见：它只看得到你声明的内容和 dramapack 自己渲染的字体。

## 清单

- [ ] 每一集的每段音乐都在 `rights.json` 里声明（确实没有音乐就写 `"music": []`）。
- [ ] 没有任何一段音乐的出版方、厂牌或权利人是大厂牌或其旗下厂牌。
- [ ] 授权音乐有授权文件（`proof`：文件路径或 URL），覆盖同步使用、发行地区和投放平台。
- [ ] 公有领域音乐写明发表年份（超过 50 年），**并且**录音也是公有领域或自己演奏的。
- [ ] AI 生成的音乐写明工具名称，并保存好该工具的商用条款。
- [ ] 字幕、标题卡、片尾卡里的每个字体都可免费商用或有授权证明。ffmpeg 默认字幕字体是 Arial，不可免费商用。
- [ ] 字幕字体在渲染的机器上确实装了，否则渲染器会换成别的字体，视频里实际用的是替代字体。

## 判级规则

| 等级 | 情形 |
|---|---|
| 红 | 没有 `rights.json` 或没有 `music` 列表；来源为 `unknown`/缺失；出版方/厂牌/权利人命中大厂牌；"公有领域"但发表不满 50 年；字体不在白名单且没有免费协议或授权证明；母带里用了未声明的音乐文件 |
| 黄 | `licensed` 但没有证明或证明文件找不到；`public_domain` 没写年份；烧录字体本机未安装（替代字体也会被检查） |
| 绿 | 其余；dramapack 自带的程序化配乐床自动声明为 `procedural` |

## 字体白名单

内置（前缀匹配，不区分大小写）：Noto、思源黑体/思源宋体（Source Han Sans/Serif）、Source Sans/Serif/Code、
DejaVu、Liberation、Roboto、Open Sans、Lato、Montserrat、Inter、Poppins、Oswald、Bebas Neue、Anton、Fira、
IBM Plex、Ubuntu、霞鹜文楷、得意黑。可在 `rights.json` 里用
`"font_allowlist": [...]` 或命令行 `--allow-font` 扩展；用 `"blocked_publishers": [...]` 增加要拦的出版方。

## 稳妥的默认选择

程序化配乐床（`--bed tension|warm|suspense|dread|hope`）由 ffmpeg 振荡器生成：没有采样、没有曲库，
无需清权。它会在台词出现时自动让位，并盖住拼接缝。

字段说明见 [reference.md](../reference.md#rightsjson)（英文）。
