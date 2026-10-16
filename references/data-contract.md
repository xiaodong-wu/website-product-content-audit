# 数据契约与执行命令

Python 工具仅使用标准库（Python 3.10+）；导出工具需要 Node.js 20+ 与运行环境提供的 `@oai/artifact-tool`。所有报告、HTML 与预览保存到独立运行目录，不放进技能仓库。

## 1. 留存实时响应

```bash
python3 scripts/probe_urls.py --url https://example.com/products/item-a --out run/probes --timezone Asia/Shanghai
python3 scripts/probe_urls.py --url-file run/urls.txt --out run/probes
```

URL 文件每行一个完整 HTTP(S) 地址。默认每次请求后等待 0.5 秒；404、429、5xx 或网络失败最多再试一次。`--timeout` 控制单次等待，`--max-bytes` 限制下载大小。脚本保存响应正文、SHA-256、每次状态/跳转、标题、H1、canonical 和链接；不会自动认定页面属于某产品，也不会自动发现全站产品。

大型或动态站点可用当前浏览工具补查；保留同样的证据字段。只验证了主图或部分尺寸图时，在 limitations 写明。不要把 HTTP 200 直接填写为内容已核查。

## 2. audit.json

必须为 UTF-8 JSON。最小可导出示例见 [example-audit.json](example-audit.json)，全部域名与内容均为合成数据。

顶层字段：

| 字段 | 含义 |
| --- | --- |
| schema_version | 固定 1 |
| site.name / site.url / site.checked_at | 站名、首页、此次报告截止时间（含时区的 ISO 8601） |
| coverage.scope | site 或 selected，说明全站还是指定页面 |
| coverage.discovery_complete | 是否已完成所选范围的产品发现，布尔值 |
| coverage.sources | 目录/分类/网站地图对象列表，每项 url、kind、checked_at |
| coverage.limitations | 字符串列表，具体记录遗漏分页、未读图片文字等 |
| products | 当前产品列表；没有 P1 的已查产品也保留，用于覆盖统计 |
| retired_urls | 可选，已替换旧地址及证据；不导出为当前问题 |

产品字段：

| 字段 | 含义 |
| --- | --- |
| id | 唯一稳定字符串，例如 P001；修订时不要无故重排 |
| name / model / category | 名称必填；后两项没有则填空字符串 |
| current_url | 经核对的当前 URL；保留有意义的查询参数，片段不参与去重 |
| http_status | 最近的 HTTP 整数状态；未知为 null |
| checked_at | 此产品最近核查时间，含时区 |
| review_status | reviewed：正文已读；unavailable：仅完成访问核查；pending：尚未完成 |
| access_checks | 实时访问记录列表，见下方 |
| issues | 问题列表，无问题为 [] |

访问记录：`url`、`final_url`、`status`（整数或 null）、`checked_at`、`live`（布尔）、`body_matches_product`（布尔或 null）。`body_matches_product` 由页面核查者判断，不来自 probe 脚本本身。

问题字段：

| 字段 | 含义 |
| --- | --- |
| id | 全站唯一稳定问题编号 |
| priority | P1、P2 或 P3 |
| state | open、resolved 或 needs_review |
| confirmed | 是否有足够证据确认；待确认项不能以 open P1 导出 |
| kind | content 或 access |
| title / location / impact / recommendation | 具体问题、所在章节、实际影响和修改建议，均必填 |
| evidence | 非空列表，每项 url、location、text；至少一项来自当前产品地址 |
| catalog_evidence | access 问题必填：url、href、checked_at；href 是当前目录实际指向的产品完整地址 |

导出的 content 问题要求 `review_status=reviewed`，有实时成功访问且正文对应产品的记录。仅访问类产品不能伪装成正文已读。

导出的 access 问题要求当前地址有两次不同时间的实时 404 或 410，最近一次检查也应为 404/410，且当前目录 href 仍指向它。403/超时/伪 404 页需人工补查；此脚本不会自动把它们升级为 P1。

退休地址对象：`url`、`replacement_url`、`checked_at`、`catalog_url`、`catalog_href`、`identity_confirmed`、`new_status`、`new_body_matches_product`。只有确认同产品、新页 200、正文匹配、目录已更新，才标记退休。`replacement_url` 必须属于当前产品列表；`catalog_href` 必须指向它。

退休前将旧产品合并到新产品，删除已解决的旧链接访问问题；新页仍存在的内容问题须使用新页面证据。若尚不能核实，不要伪造字段来通过校验。

## 3. 准备报告

```bash
python3 scripts/prepare_report.py run/audit.json --output run/report.json
```

默认仅保留 `priority=P1, state=open, confirmed=true`。显式其他范围：

```bash
python3 scripts/prepare_report.py run/audit.json --output run/report.json --priorities P1 P2
```

脚本拒绝重复 ID、重复当前 URL、仍在问题中引用已退休地址、证据缺项、未确认的 open P1 及不充分的访问故障证据。它输出覆盖统计、每产品问题数和扁平问题明细；不判断技术内容是否真实。

## 4. Excel 与交付验证

在 Codex 使用可用的 workspace dependency 工具读取 Node/Python 路径。若 Spreadsheet 技能适用，先遵循其 authoring marker、渲染与交付要求。

```bash
node scripts/export_xlsx.mjs run/report.json run/report.xlsx --node-modules /path/to/runtime/node_modules --preview-dir run/previews
python3 scripts/verify_xlsx.py run/report.json run/report.xlsx
```

导出器使用运行环境的 artifact-tool，不安装未知 npm 包。省略 `--node-modules` 时尝试正常 Node 模块解析；不可用时明确报错，不将 CSV 冒充 XLSX。

查看两个 PNG 预览，必要时调整导出器的列宽和行高。覆盖缺口及发现未完成会显示在工作簿顶部，零问题不会遮盖未核查产品。

验收脚本检查 ZIP、工作表数、记录数量、产品/问题编号、证据、当前 URL、问题级别、公式缓存、筛选及冻结。文件验证成功仅证明输出与结构化清单一致。
