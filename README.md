# Codex Plugins

etimexp 的个人 Codex 插件市场。两个插件成对使用：一个生图，一个读图。

| 插件 | 作用 |
| --- | --- |
| **gen-image** | 文本生图：默认走千问 \qwen-image-plus\（阿里云百炼 DashScope 原生接口），兼容智谱 GLM 等 OpenAI 兼容端点，图片存本地并返回路径 |
| **read-image** | 读图：把本地图片 base64 后交给视觉模型，返回文字描述，适用于看图、OCR、截图分析 |

## 安装

把本仓库加为插件市场，再按需安装：

\\\ash
codex plugin marketplace add etimexp/codex-plugins
codex plugin add gen-image@personal
codex plugin add read-image@personal
\\\

装完请**新开一个会话**，Codex 才会加载新的 MCP 工具。

也可以直接把 \plugins/<名字>\ 目录拷到本地，按自己的方式注册。

## 配置

两个插件都从各自的 \config.env\ 读密钥，该文件已被 \.gitignore\ 忽略，**不会进入版本库**。
克隆后请自行创建：

\\\ash
# gen-image
cp plugins/gen-image/config.env.example plugins/gen-image/config.env

# read-image
cp plugins/read-image/config.env.example plugins/read-image/config.env
\\\

环境变量优先级：工具参数 > 环境变量 > \config.env\。各插件的 README 里有完整的变量表。

## 目录结构

\\\
.
├── .agents/plugins/marketplace.json   插件市场清单
└── plugins/
    ├── gen-image/                     文本生图
    └── read-image/                    读图
\\\

## License

MIT