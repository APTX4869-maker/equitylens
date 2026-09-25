# 公司建档维护者指南

维护者负责把自动候选转换为可审查的发行人 profile，并只批准完全通过质量门槛的固定候选。CLI 与页面都调用本地 API；API 不可用时不得直接改 DuckDB。

## 运行前检查

确认 API 和前端依赖已按锁文件安装，并设置包含真实联系方式的 SEC User-Agent。

终端 A：

```bash
export EQUITYLENS_USER_AGENT='EquityLens/0.1 (your-name; your-email@example.com)'
uv run uvicorn equitylens.api.main:app --port 8000
```

终端 B：

```bash
pnpm --dir apps/web dev
```

不要原样使用示例地址。隔离验收推荐只设置 `EQUITYLENS_DATA_DIR`，它同时改变 raw 根目录和默认数据库；`EQUITYLENS_DB_PATH` 仅覆盖数据库路径，优先于 `EQUITYLENS_DATA_DIR` 派生的默认库。配置在进程导入时读取，修改变量后必须重启 API。例如：

```bash
isolated_dir="$(mktemp -d /tmp/equitylens-onboarding.XXXXXX)"
EQUITYLENS_DATA_DIR="$isolated_dir" \
EQUITYLENS_USER_AGENT='EquityLens/0.1 (your-name; your-email@example.com)' \
uv run python -c 'from equitylens.config import DATA_DIR, RAW_DIR, DB_PATH; print(DATA_DIR, RAW_DIR, DB_PATH)'
EQUITYLENS_DATA_DIR="$isolated_dir" \
EQUITYLENS_USER_AGENT='EquityLens/0.1 (your-name; your-email@example.com)' \
uv run uvicorn equitylens.api.main:app --port 8000
```

先核对打印路径都在 `$isolated_dir` 下，再启动页面。正式迁移前用 `lsof data/equitylens.duckdb` 确认没有进程持有文件，并为数据库和 `data/raw` 建立已校验备份。

## Profile 适配

profile 位于 `config/issuers/<10位CIK>/<version>.yaml`，必须通过严格 data-only schema；版本一经入库不可改写。至少核对：

- CIK、法定名称、ticker、交易所、股类、币种和证券类型；
- 财年末、52/53 周口径、核心指标 concept、期间类型和单位；
- 现金/受限现金定义、非重叠债务组件和明确 EPS 方法；
- 分部 axis、成员、抵销或“不披露/不适用”的原始证据；
- 每项证据的 source document、SHA-256 和可人工复核 locator。

新增通用解析行为必须进入具名、版本化的 mapping 或 resolver，并用所有已支持发行人回归；不得在主业务路径加入 ticker 特例。自动候选永远只是起点。如果导入报不可变版本冲突，不要覆盖原文件：增加 version，并创建新的 `<version>.yaml` 后重新导入。

## CLI 复核闭环

```bash
uv run equitylens onboarding show TASK_ID
uv run equitylens onboarding profile-import TASK_ID \
  --file config/issuers/CIK/VERSION.yaml --revision REVISION
uv run equitylens onboarding export TASK_ID --output /tmp/review-package.json
uv run equitylens onboarding review TASK_ID \
  --fingerprint FINGERPRINT --revision REVISION --reviewer NAME \
  --decision APPROVE \
  --note '已逐项核对 SEC 报表、单位、期间、分部抵销和证券身份'
```

`TASK_ID` 来自建档中心地址/任务详情或任务列表 API；当前 `revision` 来自 `onboarding show`，`fingerprint` 来自刚导出的审查包。导出后检查 dataset/profile/quality 三个哈希、全部来源、关键数值和 BLOCKER。批准必须提交当前 revision 与 review package fingerprint，并显式选择 `--decision APPROVE`；API 只把任务原子转为 `PUBLISHING`，随后由持久化执行器作为唯一发布者完成 publication，页面会继续轮询。任何候选或质量重跑都会使旧 revision/fingerprint 失效。质量结果不是 PASS 时 API 必须拒绝批准。拒绝时改用 `--decision REJECT` 并写明证据缺口。

## Golden 与验收

KO、COST、AAPL、MSFT 的固定入口为：

```bash
uv run pytest tests/golden/test_onboarding_issuers.py -q
```

manifest 中的预期值由 10-K 报表人工转录，不由待测解析器生成；测试同时检查官方快照哈希、身份、期间、单位、accession、raw lineage 和 profile 证据绑定。完整发布前还要执行[主计划第 15 节](superpowers/plans/2026-09-11-company-onboarding.md#15-验证命令审查和交付)的 `uv sync --frozen`、全量 pytest、冻结前端安装、TypeScript、lint、build 和串行浏览器测试，并用真实后端加隔离库走一遍页面。

## 迁移、故障和恢复

脚本把来源当作只读输入，先复制数据库与 raw，再只在演练副本上迁移。明确指定输出根目录便于审计：

```bash
uv run python scripts/rehearse_real_db_migration.py \
  --source-db /absolute/path/to/equitylens.duckdb \
  --source-raw /absolute/path/to/raw \
  --output-root /absolute/path/to/migration-rehearsals
```

每次运行会生成时间戳目录，以及 `report.json` 和 `failure-recovery.json`。只有在报告中数据库/原始证据备份哈希一致、两次 material table 回放一致、source identity 一致且历史估值保真时才可安排正式迁移。故障演练需在副本事务中注入异常，确认回滚后业务值不变，再从备份恢复并比较完整数据库 SHA-256。不要覆盖包含用户新增数据的库；恢复目标必须是明确的单个备份路径。

SEC 若返回 403，不要更换身份、代理或绕过限制。确认 User-Agent 合规后等待官方访问恢复，通过正常 FETCH 流程把文档保存到 `DATA_DIR/raw/sec/<CIK>/`，记录 URL、locator、获取时间与 SHA-256，再重跑 profile/quality 并导出新的审查包。

## 当前真实接入状态（2026-09-12）

KO 与 COST 的官方 submissions/companyfacts 快照、身份和 2025 10-K 核心数值已经固定并通过 golden。通用映射 v3 已补齐负债、投资/融资现金流、受限现金桥，完整 Company Facts 的派生季度也已保留 raw lineage。

两家公司目前仍不能批准发布：当前网络环境对 SEC Archives iXBRL 文档返回 403，无法固定并解析报表行级 context 与分部维度原件。Company Facts 能证明数值、期间、单位和 accession，但没有真实 filing context/locator，质量报告因此保留 `LINEAGE.filing_context` 与 `SEGMENTS.reconciliation` 两个 BLOCKER，生产任务停在 `NEEDS_ADAPTATION`。在线页面验收时 SEC ticker registry 也返回 403，系统会显示可重试的 503 错误而不会创建候选。AAPL/MSFT 已建立 profile v2，已固定指标通过 golden，旧 fixture 缺失的必需项被显式记为 gap；正式库仍保留 `LEGACY_UNREVIEWED`，本次演练没有写入正式库。取得并核验 iXBRL 报表及分部证据后，应补全 source document、raw fact context/locator、axes/segment rows，重跑质量、导出新审查包，再由维护者批准；不得手工改为 PASS。
