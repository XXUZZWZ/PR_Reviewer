# PR Reviewer

AI 驱动的 Pull Request 代码评审 CLI 工具。

## 快速开始

```bash
# 1. 安装
cd PR_Reviewer
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. 配置（二选一）

## 方式A：配置文件
cp config.example.toml config.toml
# 编辑 config.toml，填入 GitHub token 和 DeepSeek API key

## 方式B：环境变量
export GITHUB_TOKEN="github_pat_xxxx"
export ANTHROPIC_API_KEY="sk-xxxx"

# 3. 使用
source .venv/bin/activate
pr-review review https://github.com/owner/repo/pull/123 -c config.toml
```

## 命令参考

```
pr-review review <PR_URL> [选项]
```

### PR URL 格式

支持三种写法，效果相同：

```
https://github.com/owner/repo/pull/123
owner/repo/123
owner/repo#123
```

### 常用选项

| 选项 | 说明 | 示例 |
|------|------|------|
| `-c, --config` | 指定配置文件 | `-c config.toml` |
| `-f, --format` | 输出格式 | `-f json` / `-f md` / `-f html` / `-f all`（默认） |
| `-o, --output` | 自定义输出目录 | `-o ./my-review/` |
| `-m, --model` | 切换模型 | `-m deepseek-v4-flash`（更快更便宜） |
| `-v, --verbose` | 显示详细日志 | `-v` |
| `--skip-linters` | 跳过 linter 检查 | `--skip-linters` |

### 示例

```bash
# 完整评审，输出所有格式到默认目录 reports/pr_123_日期/
pr-review review owner/repo/123 -c config.toml

# 只要 HTML 报告，保存到指定目录
pr-review review owner/repo/123 -c config.toml -f html -o ./review/

# 用 flash 模型（更快更便宜），跳过 linter
pr-review review owner/repo/123 -c config.toml -m deepseek-v4-flash --skip-linters
```

## 输出说明

每次评审默认生成到 `reports/pr_{编号}_{时间}/` 目录：

```
reports/pr_87882_20260529_135744/
├── report.json   ← 完整 JSON 数据（含中英文双语内容）
├── report.md     ← Markdown 格式，可直接贴到 GitHub issue
└── report.html   ← HTML 网页，浏览器打开查看
```

**报告内容**：
- 文件完整 diff（新增/删除行高亮）
- 每个 finding 含：严重度、分类、标题、描述、建议、置信度
- 中英双语（中文在上，英文在下）
- 行号可点击，直接跳转 GitHub 对应文件位置

## 配置文件

```toml
[github]
token = "github_pat_xxxx"

[llm]
provider = "deepseek"
model = "deepseek-v4-pro"       # deepseek-v4-pro 或 deepseek-v4-flash
api_key = "sk-xxxx"
base_url = "https://api.deepseek.com/anthropic"
max_output_tokens = 8192
temperature = 0.3

[analysis]
max_dependency_depth = 2        # 依赖链最大深度
include_test_files = true       # 是否评审测试文件

[linters]
enabled = true
timeout_seconds = 60

[report]
terminal_verbosity = "default"  # minimal / default / verbose
save_path = ""                  # 留空 = 自动保存到 reports/
```

## 支持的语言和 Linter

| 语言 | 自动调用的工具 |
|------|---------------|
| Python | pylint, mypy, bandit |
| JavaScript/TypeScript | eslint |
| Go | go vet |
| Rust | clippy |
| Shell | shellcheck |
| 其他 | 纯 LLM 分析 |

工具未安装时会自动跳过，不影响评审。

## 工作流程

```
输入 PR URL
  → 解析 (owner, repo, pr_number)
  → GitHub API 获取 PR 元数据和 diff
  → 浅克隆仓库
  → 构建依赖图（变更文件的 import 和被 import 关系）
  → 逐个文件：
      ├── 检测语言
      ├── 运行 linter（如有）
      ├── 组装依赖上下文（import 了什么 / 被谁 import）
      ├── 构建 prompt → 调用 LLM
      ├── 调用 flash 模型翻译为中文
      └── 解析结构化结果
  → 生成报告（JSON + MD + HTML）
  → 终端预览
```

## 视频地址 
【PR_Reviewer】 https://www.bilibili.com/video/BV1MMVo63EbY/?share_source=copy_web&vd_source=dd713f4998af3436a24379199c421d89