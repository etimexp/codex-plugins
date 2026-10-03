# gen-image 插件(千问版)

根据文本描述生成图片的 Codex 个人插件。它通过 MCP 暴露一个
`generate_image` 工具:默认调用**千问图像模型**(阿里云百炼 DashScope
原生接口,默认 `qwen-image-plus`),把生成的图片保存到本地,并把
"内嵌图片 + 本地路径"一起返回给主模型,便于在对话中直接展示和下载。
同时兼容智谱 GLM 等任意 OpenAI 兼容端点。

## 特性

- 文本 → 图片:传入 prompt(可带尺寸、文件名、输出目录、水印)
- 模型可配置:默认千问 `qwen-image-plus`,可切 `qwen-image` /
  `qwen-image-3.0` / `qwen-image-3.0-pro`,或智谱 `glm-image`
- 兼容同步与异步(任务轮询)两种接口响应:千问走原生异步任务
  (`text2image/image-synthesis` + `/tasks/<id>` 轮询),
  `qwen-image-3.x` 这类模型自动回退到多模态端点
- 兼容接口返回 URL 或 base64 两种图片格式
- 图片自动保存到 `~/.codex/generated_images`(可用环境变量改目录)
- 零第三方依赖,纯 Python 标准库

## 安装

插件已注册到个人 marketplace(`~/.agents/plugins/marketplace.json`)。
在 Codex 中使用:

```bash
codex plugin add gen-image@personal
```

安装后请**新开一个会话**,Codex 才会加载新的 MCP 工具。

MCP 服务由 `scripts/launch_mcp.cmd` 启动。它按顺序**逐个探测、只使用能真正跑起来的**
解释器:`py -3` → `python` → `python3` → 用户目录安装的 Python
(如 `%LOCALAPPDATA%\Programs\Python\Python314\python.exe`)→ Codex 内置运行时
`%USERPROFILE%\.cache\codex-runtimes\...\python.exe`。
所以即使 Python 没有加入 PATH、也没有注册到 py 启动器,插件依然能启动。

## 配置

优先级:工具参数 > 环境变量 > `config.env`。

| 环境变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 千问/DashScope API Key(也可用 `GEN_IMAGE_API_KEY`) | 无 |
| `GEN_IMAGE_MODEL` | 生图模型 | `qwen-image-plus` |
| `GEN_IMAGE_BASE_URL` | 千问原生端点 | `https://dashscope.aliyuncs.com/api/v1` |
| `GEN_IMAGE_SIZE` | 默认尺寸 | `1024x1024` |
| `GEN_IMAGE_OUTPUT_DIR` | 输出目录 | `~/.codex/generated_images` |
| `GEN_IMAGE_TIMEOUT` | 请求超时(秒) | `180` |
| `GEN_IMAGE_WATERMARK` | 是否加水印 | `false` |

可以直接编辑插件根目录的 `config.env`(该文件已在 `.gitignore` 中)。

## 模型说明

默认使用千问图像模型,端点固定为 DashScope 原生接口
`https://dashscope.aliyuncs.com/api/v1`:

| 模型 | 说明 |
| --- | --- |
| `qwen-image-plus` | 默认,质量更好 |
| `qwen-image` | 基础版,更快、更便宜 |
| `qwen-image-3.0` / `qwen-image-3.0-pro` | 最新一代;不在 text2image 端点,插件自动改用多模态端点(同步,较慢) |

注意:DashScope 的 OpenAI 兼容端点(`/compatible-mode/v1`)目前不提供
`/images/generations`(实测 404),所以这里走原生端点。尺寸按 `1024*1024`
传参,插件会把 `1024x1024` 自动转成 `1024*1024`。

如需切回智谱:`config.env` 中把 `GEN_IMAGE_MODEL` 设为 `glm-image`、
`GEN_IMAGE_BASE_URL` 设为 `https://open.bigmodel.cn/api/paas/v4`,并保留
`ZHIPU_API_KEY` 即可,代码无需改动。

## 使用

在对话中直接说"生成一张 XXX 的图片",主模型会调用 `generate_image`。
工具参数:

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `prompt` | 是 | 图片描述:主体、场景、风格、构图、颜色、文字等 |
| `size` | 否 | 尺寸,如 `1024x1024`、`1536x1024`、`auto` |
| `filename` | 否 | 输出文件名 |
| `output_dir` | 否 | 输出目录 |
| `model` | 否 | 临时覆盖模型 |
| `watermark` | 否 | 是否加水印,默认 `false` |

命令行方式(调试用):

```bash
py -3 scripts/gen_image.py "一只戴着宇航员头盔的橘猫" --model qwen-image-plus
```

## 输出与安全

- 图片保存在 `GEN_IMAGE_OUTPUT_DIR`(默认 `~/.codex/generated_images`)
- `config.env` 包含 API Key,已被 `.gitignore` 忽略,请勿提交到版本库
- 工具返回结果包含本地绝对路径,主模型用 Markdown 展示并提供下载
