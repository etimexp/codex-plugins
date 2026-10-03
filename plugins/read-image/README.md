# read-image 插件

一个给 Codex 用的本地插件：**读取图片 → base64 编码 → 调用纯视觉模型 → 把文字结果返回给主模型**。当前已配置为智谱（Zhipu）GLM 视觉模型。

## 原理

1. **图片 base64 编码**：读取本地图片文件，转成 `data:image/...;base64,...` 数据 URL。
2. **调用纯视觉模型**：通过 OpenAI 兼容接口发送图片给视觉模型。智谱走 `chat/completions`（`POST /chat/completions`），OpenAI 走 Responses API（`POST /responses`），按 Base URL 自动识别。
3. **结果发回主模型**：视觉模型的文字输出作为工具结果返回，主模型直接用它总结、OCR、翻译、写代码等。

## 目录结构

```text
read-image/
├── .codex-plugin/plugin.json    # 插件清单
├── .mcp.json                    # MCP 服务器配置（read_image 工具）
├── scripts/
│   ├── read_image.py            # 核心逻辑：base64 + 视觉模型调用（纯标准库）
│   └── mcp_server.py            # 极简 MCP stdio 服务器（纯标准库）
├── skills/read-image/SKILL.md   # 使用技能说明
└── README.md
```

## 安装（两种方式）

### 方式 A：安装到个人市场（推荐）

在真实用户终端（非沙箱）中执行：

```powershell
# 1. 把插件复制到个人插件目录
Copy-Item -Recurse "C:\Users\zhifu\Documents\Codex\2026-08-06\bang\plugins\read-image" "$HOME\plugins\read-image"

# 2. 把 marketplace 条目合并进个人市场
#    确保 $HOME\.agents\plugins\marketplace.json 存在后，将下列条目加入其 plugins 数组：
#    {"name":"read-image","source":{"source":"local","path":"./plugins/read-image"},
#     "policy":{"installation":"AVAILABLE","authentication":"ON_INSTALL"},"category":"Productivity"}
```

### 方式 B：注册工作区市场

```powershell
codex plugin marketplace add "C:\Users\zhifu\Documents\Codex\2026-08-06\bang"
codex plugin add read-image@local
```

安装后请新开一个 Codex 会话（MCP 工具和技能需要重新加载）。

## 配置（当前：智谱 GLM）

插件根目录的 `config.env` 已写入你的智谱 API Key、端点和模型，无需再设置环境变量：

| 变量 | 默认值 |
| --- | --- |
| `OPENAI_API_KEY` | 你的智谱 Key（在 `config.env` 中） |
| `READ_IMAGE_MODEL` | `glm-5v-turbo` |
| `OPENAI_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` |
| `READ_IMAGE_MAX_TOKENS` | `1024` |
| `READ_IMAGE_PROMPT` | 详细描述图片 |
| `READ_IMAGE_TIMEOUT` | `180` |

> **重要**：GLM-5.2 是纯文本旗舰模型（官方文档标注输入/输出均为文本），不支持图片输入。图片理解请使用智谱 VLM 系列：`glm-5v-turbo`（默认）、`glm-4.6v`、`glm-4.6v-flash`（免费）或 `glm-ocr`。如需更换，改 `config.env` 里的 `READ_IMAGE_MODEL` 一行即可。

`config.env` 已加入 `.gitignore`，不会进入版本库；请勿把 Key 外传。

## 使用

在对话里直接说“读取这张图片 / 提取截图里的文字”，主模型会自动调用 `read_image` 工具。

`image_path` 支持三种输入：本地图片路径、公开图片的 http(s) 链接、上传/粘贴的图片数据（`data:image/...;base64,...`）。网页链接不行，那是 HTML 页面，需要先截图。

也可以命令行直接调用：

```powershell
py -3 "C:\Users\zhifu\Documents\Codex\2026-08-06\bang\plugins\read-image\scripts\read_image.py" "C:\path\to\image.png" --prompt "Extract all text."
```

## 说明

- 零第三方依赖，Python 3.7+ 标准库即可运行。
- 优先级：工具参数 > 环境变量 > `config.env` > 内置默认值。
- MCP 服务器使用 `py -3` 启动；如果机器没有 `py` 启动器，请把 `.mcp.json` 里的 `command` 改为实际 Python 可执行文件路径。
