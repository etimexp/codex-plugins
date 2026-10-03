---
name: read-image
description: "Use when the user wants to read, view, describe, understand, or OCR an image file, or when image content needs to be extracted and returned to the main model as text. Uses the read_image tool: base64 encode -> pure vision model -> return text."
---

# Read Image

把图片变成主模型能直接使用的文字：先对图片做 base64 编码，再调用纯视觉模型，最后把视觉模型的文字输出返回给主模型。

## 何时使用

- 用户要求“看 / 读 / 识别 / 描述这张图片”
- 需要从图片中提取文字（OCR）、总结截图、识别 UI 或图表内容
- 主模型无法直接查看图片，需要一个独立视觉模型的结果

## 流程

1. 调用 MCP 工具 `read_image`，传入图片路径：
   - `image_path`：本地图片文件路径、公开图片的 http(s) 链接，或上传图片的 data URL（必填）
   - `prompt`：给视觉模型的指令（可选，默认是详细描述图片）
   - `model`：视觉模型 ID（可选，默认 `$READ_IMAGE_MODEL` 或 `gpt-5.6-terra`）
   - `max_output_tokens`：最大输出 token 数（可选，默认 1024）
2. 工具内部完成：本地图片先 base64 编码（URL 图片直接透传）→ 调用 OpenAI 兼容接口（智谱 `chat/completions` 或 OpenAI `/responses`）→ 返回文字。
3. 把返回的文字直接当作图片内容使用：总结、引用、翻译、转写代码等。

## 示例

- “读取 `C:\shots\login.png`，把里面的文字全部提取出来” →
  `read_image(image_path="C:\\shots\\login.png", prompt="Extract all text from this image verbatim.")`
- “看看这张设计稿并总结布局” →
  `read_image(image_path="...", prompt="Summarize the layout and design of this image in Chinese.")`

## 配置（环境变量）

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 调用视觉模型所需的 API Key（必填） | 读取 `config.env` |
| `READ_IMAGE_MODEL` | 视觉模型 ID | `glm-5v-turbo`（智谱 VLM） |
| `OPENAI_BASE_URL` | API 基础地址 | `https://open.bigmodel.cn/api/paas/v4` |
| `READ_IMAGE_MAX_TOKENS` | 最大输出 token 数 | `1024` |
| `READ_IMAGE_PROMPT` | 默认提示词 | 详细描述图片 |
| `READ_IMAGE_TIMEOUT` | 请求超时（秒） | `180` |
| `READ_IMAGE_API_STYLE` | `chat_completions`（智谱）或 `responses`（OpenAI） | 按 Base URL 自动判断 |
| `READ_IMAGE_IMAGE_URL_FORMAT` | `base64` 或 `data_url` | 智谱用 `base64` |
| `READ_IMAGE_THINKING` | `enabled` 开启深度思考 | 关闭 |

插件根目录的 `config.env` 已配置好智谱 Key、端点和模型，优先级：工具参数 > 环境变量 > `config.env`。

> **注意**：GLM-5.2 是纯文本旗舰模型，不支持图片输入。本插件做图片理解用的是智谱视觉模型（默认 `glm-5v-turbo`，可换成 `glm-4.6v` / `glm-4.6v-flash` / `glm-ocr`）。

## 备用：命令行直接调用

如果 MCP 工具不可用，可以直接运行脚本（结果输出到 stdout）：

```powershell
py -3 "<plugin root>/scripts/read_image.py" "C:\path\to\image.png" --prompt "Describe this image."
```

## 注意

- 支持三种输入：本地图片路径、公开图片 URL、上传/粘贴的图片数据（data URL）；网页链接（HTML 页面）不是图片，需先截图或用真实图片地址。
- 用户直接拖图上传到对话后，找到附件的本地路径或图片数据，调用 `read_image` 即可识别。
- 图片上限 50 MB。
- 图片内容只会发送给配置的视觉模型 API，不会写入对话历史之外的任何位置。
