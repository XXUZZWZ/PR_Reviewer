# PR Reviewer

AI 驱动的命令行工具，用于自动化 GitHub Pull Request 代码评审。

## 功能

- **PR 变更总结** — 归纳概括代码变更，帮助 reviewer 快速理解改动范围和意图
- **风险代码识别** — 自动检测安全漏洞、性能问题、逻辑错误、代码规范违规等风险点
- **Review 建议生成** — 生成具体、可操作的 review 建议，附带严重程度、分类和置信度评分
- **依赖感知分析** — 结合依赖链上下文（imports + importers）分析每个变更文件，实现跨文件理解
- **Linter 集成** — 运行语言专用 linter（pylint、eslint、clippy 等），将结果作为信号提供给 LLM
- **富文本终端输出** — 彩色表格、严重度树形图、结构化发现展示

## 安装

需要 Python 3.11+。

```bash
git clone https://github.com/XXUZZWZ/PR_Reviewer.git
cd PR_Reviewer
pip install -e .
```

带开发依赖安装：

```bash
pip install -e ".[dev]"
```

## 配置

创建 `config.toml`（参考 `config.example.toml`）：

```toml
[github]
token = "ghp_xxxx"          # GitHub 个人访问令牌

[llm]
model = "deepseek-v4-pro"    # LLM 模型
api_key = "sk-xxxx"          # API 密钥
base_url = "https://api.deepseek.com/anthropic"
```

或使用环境变量：

```bash
export GITHUB_TOKEN="ghp_xxxx"
export ANTHROPIC_API_KEY="sk-xxxx"
```

## 用法

```bash
# 评审一个 PR
pr-review https://github.com/owner/repo/pull/123

# 使用自定义配置
pr-review https://github.com/owner/repo/pull/123 -c config.toml

# 保存报告到文件
pr-review https://github.com/owner/repo/pull/123 -o report.json

# 跳过 linter（仅 LLM 分析）
pr-review https://github.com/owner/repo/pull/123 --skip-linters

# 详细输出模式
pr-review https://github.com/owner/repo/pull/123 -v
```

也支持简写 PR URL 格式：

```bash
pr-review owner/repo/123
pr-review owner/repo#123
```

## 支持语言

| 语言 | Linter |
|------|--------|
| Python | pylint, mypy, bandit |
| JavaScript / TypeScript | eslint, tsc |
| Java | javac -Xlint, checkstyle |
| Go | go vet, golint, staticcheck |
| Rust | clippy |
| Shell | shellcheck |

无 linter 支持的语言仍可进行纯 LLM 分析。

## 架构

```
pr-review <url>
  ├── 1. 解析 PR URL → (owner, repo, pr_number)
  ├── 2. 获取 PR 元数据（文件列表、diff、统计） via GitHub API
  ├── 3. 浅克隆仓库至 PR head SHA
  ├── 4. 构建依赖图（imports → 文件, importers → 文件）
  ├── 5. 逐文件分析循环：
  │     ├── 检测语言
  │     ├── 运行 linter（缺失时优雅降级）
  │     ├── 收集依赖上下文（deps + dependents）
  │     ├── 构建 prompt（diff + 上下文 + linter 信号）
  │     └── 调用 LLM → 解析结构化 JSON 响应
  ├── 6. 生成报告（逐文件分析 + 跨文件发现）
  └── 7. 格式化输出（终端 + 可选 JSON 保存）
```

## 关键设计决策

- **模型选择**：使用 DeepSeek 兼容的 Anthropic API，支持 prompt 缓存。共享的 prompt 部分（系统提示词、PR 概览）被缓存，在多文件 PR 上可降低约 5 倍成本。
- **逐文件分析而非全量 PR**：每个文件独立分析，同时携带其依赖上下文，在保持 token 预算可控的前提下实现跨文件感知。
- **混合分析**：Linter 提供结构化、确定性的信号（语法错误零误报），LLM 负责语义理解、上下文推理和跨文件关注点。
- **依赖链上下文**：对每个变更文件，提取被 import 符号的函数/类签名，以及依赖方文件的调用点——给 LLM 足够的上下文来发现破坏性变更，同时不超出 token 预算。

## 未来扩展方向

- 支持更多代码托管平台（GitLab、Bitbucket）
- 自定义规则引擎，支持项目级评审策略
- 增量评审模式（同一 PR 的后续 commit 增量分析）
- Reviewer 反馈回路，持续提升分析准确度

## License

MIT
