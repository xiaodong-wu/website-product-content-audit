# 网站产品详情内容核查

可安装的 Codex Skill：`website-product-content-audit`。

核查公开产品网站的目录、分类和网站地图，逐页阅读产品详情，默认仅将有证据、影响选型/订货/安装/访问的 **P1 问题**导出为 Excel。适用于任何产品网站，不绑定特定品牌或行业。

## 使用

安装后，在 Codex 输入：

```text
使用 $website-product-content-audit 核查 https://example.com/products/ 的全部产品详情，只保留 P1 问题并导出 Excel。
```

也可指定单个产品，或更新已有报告：

```text
使用 $website-product-content-audit 复核这份报告中的产品链接。对已迁移且目录已更新的产品，统一新地址、合并重复产品、删除旧链接404项，保留新页仍存在的P1内容问题后重新导出。
```

## 安装

在尚未存在同名技能目录的环境中：

```bash
git clone https://github.com/xiaodong-wu/website-product-content-audit.git "${CODEX_HOME:-$HOME/.codex}/skills/website-product-content-audit"
```

或者下载仓库 `releases/` 中的 ZIP，解压后将 `website-product-content-audit` 文件夹放入 Codex 的 `skills` 目录。需要时新开会话或重新加载技能列表。

## 能力与边界

- 产品发现：目录分页、分类和网站地图交叉核对，记录实际覆盖和缺口。
- 内容审查：关键规格、型号、图文、用途、安装、包装与 FAQ 的明确矛盾。
- 链接复核：实时 GET、有限重试、跳转链和响应证据；不把缓存、403 或超时当成失效事实。
- 报告修订：退休旧链接并保留仍成立的内容问题；稳定编号、防重复统计。
- Excel：问题产品汇总与逐条明细，包含来源、证据、影响和建议，支持零问题及不完整覆盖的如实说明。

**语义核查由执行技能的智能体完成。** 脚本只负责抓取、结构验证、筛选、计数和导出，不会自动证明参数正确、认证真实或实物性能。技能不会修改网站或提交询盘。

## 运行环境

- Python 3.10+，脚本只使用标准库。
- 联网搜索/网页或浏览器工具，用于产品发现和内容阅读。
- Excel 导出使用 Node.js 20+ 与宿主环境提供的 `@oai/artifact-tool`。在 Codex 中读取 workspace dependencies 后传入 `--node-modules`；该依赖不随 ZIP 分发。
- 若导出依赖不可用，应说明限制并保留结构化结果，不能把其他格式伪装为 `.xlsx`。

具体命令及字段见 [数据契约](references/data-contract.md)，判定边界见 [P1规则](references/p1-rubric.md)。

## 验证

```bash
python3 scripts/test_workflow.py
python3 scripts/prepare_report.py references/example-audit.json --output /tmp/product-audit-demo/report.json
node scripts/export_xlsx.mjs /tmp/product-audit-demo/report.json /tmp/product-audit-demo/report.xlsx --node-modules /path/to/runtime/node_modules
python3 scripts/verify_xlsx.py /tmp/product-audit-demo/report.json /tmp/product-audit-demo/report.xlsx
```

示例为合成数据；测试仅访问本地临时 HTTP 服务，不访问生产网站。发布包不包含客户报告、网站抓取结果、账号凭据或机器专属路径。
