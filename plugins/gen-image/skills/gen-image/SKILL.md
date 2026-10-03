---
name: gen-image
description: Use when the user asks to generate an image from a text description, or wants a picture/illustration created from a prompt. Calls the generate_image MCP tool (default model qwen-image-plus / 千问, switchable to qwen-image or qwen-image-3.0-pro), then shows the saved image in chat and provides a download link.
---

# gen-image:文本生成图片

当用户要求"生成一张图片 / 画一个 / 做一张配图"等时,按以下流程操作。

## 1. 整理 prompt

把用户的需求整理成清晰、可执行的描述,尽量包含:

- 主体:画什么(人、物、场景)
- 场景与背景:环境、氛围
- 风格:写实、插画、3D、扁平、科技风等
- 构图与比例:横幅、竖幅、居中、留白
- 色彩与光线:色调、明暗
- 文字要求:如果需要画面中出现文字,明确写出具体文字与位置

中文或英文均可(千问模型对中文支持良好)。

## 2. 调用工具

调用 `generate_image` 工具:

- `prompt`(必填):整理好的描述
- `size`(可选):`1024x1024`、`1536x1024`(横幅)、`1024x1536`(竖幅)、`auto`
  (千问/DashScope 端点内部会自动把 `1024x1024` 转成 `1024*1024` 形式)
- `filename`(可选):期望的文件名
- `output_dir`(可选):保存目录,默认 `~/.codex/generated_images`
- `model`(可选):临时指定模型,默认 `qwen-image-plus`(千问);
  可选 `qwen-image`(更快更便宜)、`qwen-image-3.0`、`qwen-image-3.0-pro`
- `watermark`(可选):是否加水印,默认 `false`(不加)

示例:

```json
generate_image(
  prompt = "科技风插画:蓝色数据中心中一座发光的芯片,背景是上升的折线图,16:9 横幅构图,深蓝与青色配色,无文字",
  size = "1536x1024"
)
```

## 3. 展示与下载

工具会返回:

1. 文本摘要:本地绝对路径、模型、输出目录
2. 内嵌图片内容块

在回复中:

- 用 Markdown 展示图片:`![图片](本地绝对路径)`
- 给出可点击的下载/查看链接(绝对路径)
- 简要说明模型与保存位置

## 4. 失败处理

- 报错"model ... not supported / 4xx":说明当前模型不支持文生图
  (千问端点若提示 `InvalidParameter: url error`,说明该模型不在当前端点上,
  可改用 `qwen-image-plus` / `qwen-image`;插件会自动回退到多模态端点
  重试 `qwen-image-3.0` 这类模型),提示把 `config.env` 中的
  `GEN_IMAGE_MODEL` 改成可用模型,改完需要重新加载插件
- 报错缺少 API Key:提示设置 `DASHSCOPE_API_KEY`(或 `GEN_IMAGE_API_KEY`)
- 报错 `Throttling.RateQuota`:千问侧并发/速率限制,等几秒后重试即可
- 网络/超时:提示检查网络后重试,或调大 `GEN_IMAGE_TIMEOUT`
- 画面文字乱码或构图不满意:根据结果做单点修改,重新生成一次
