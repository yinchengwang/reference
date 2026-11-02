# reference

本仓是**与 StillEvolving 平级的独立仓**（`origin = https://github.com/yinchengwang/reference.git`），
**不是** StillEvolving 的 submodule，**不在** StillEvolving 的目录树内。

> 旧称「`book` 主仓的参考资料库」已废弃。现行四仓关系以父仓
> [`../StillEvolving/README.md`](../StillEvolving/README.md)、
> [`../StillEvolving/docs/architecture.md`](../StillEvolving/docs/architecture.md)（目录规范）与
> [`../StillEvolving/repos.yaml`](../StillEvolving/repos.yaml)（机器可读清单）为准。

本仓包含两类资产：

| 目录 | 内容 |
|---|---|
| `reference/` | 第三方源码镜像（清单驱动、按需拉取） |
| `docs/` | 源码阅读笔记层（带精确行号引用） |

## 口径：95 与 97 分别是多少

| 数字 | 含义 | 权威来源 |
|---|---|---|
| **95** | 已注册为 submodule 的第三方库数（= `reference/` 下实际库目录数） | `.gitmodules`（95 条） |
| **97** | 清单条目数（含无源码镜像的条目） | `reference/catalog.yml`（97 条）＝ `reference/fetch-manifest.txt`（97 行数据 + 1 行表头 = 98 行） |

两者相差 **2 条**：`oceanbase`（`distributed-sql/`）与 `pklite`（`embedded/`）——
`pin_status: unresolvable` / `source: none`，没有源码镜像，因此既无库目录、也未注册为 submodule，
但仍保留在 catalog 与 manifest 中留档。

`pin_status` 分布（97 条）：`valid` 91 / `broken` 4 / `unresolvable` 2；
`source` 分布：`mirror` 95 / `none` 2。

## `reference/` —— 第三方源码镜像

15 个技术分类、95 个库目录（每个库是一个 submodule），覆盖向量库、关系型数据库、搜索引擎、
图数据库、时序数据库、消息队列等方向的上游实现，用于对照学习与源码检索。

| 分类 | 库数 | 说明 |
|---|---:|---|
| `ai/agent/` | 13 | Agent 框架（多智能体编排、工具调用） |
| `ai/rag/` | 11 | RAG 检索增强生成工具链 |
| `benchmark/` | 5 | 基准测试套件（ANN、TPC-H/DS、vectordb） |
| `columnar/` | 5 | 列式存储（ClickHouse、Doris、StarRocks…） |
| `distributed-sql/` | 3 | 分布式 SQL（CockroachDB、TiDB、YugabyteDB…） |
| `document/` | 5 | 文档数据库（MongoDB、CouchDB、RavenDB…） |
| `embedded/` | 3 | 嵌入式存储（DuckDB、BoltDB、LMDB…） |
| `extension/` | 6 | 扩展组件（pgvector、Arrow、DataFusion、HNSWLib…） |
| `graph/` | 6 | 图数据库（Neo4j、JanusGraph、Kuzu…） |
| `key-value/` | 7 | 键值存储（Redis、RocksDB、Badger…） |
| `relational/` | 7 | 关系型数据库（PostgreSQL、MySQL、openGauss…） |
| `search/` | 6 | 搜索引擎（Elasticsearch、Meilisearch、Tantivy…） |
| `stream/` | 4 | 流处理（Kafka、NATS、Pulsar…） |
| `time-series/` | 5 | 时序数据库（InfluxDB、IoTDB、TDengine…） |
| `vector/` | 9 | 向量数据库（Faiss、Milvus、Qdrant、Weaviate…） |
| **合计** | **95** | 15 个分类（`ai/` 是二级分类，含 `agent` 与 `rag`） |

> 表中「库数」为已落盘的库目录数（对应 `source: mirror` 的 95 条）。
> `oceanbase` / `pklite` 只在清单里留档，不占目录。

### 清单、lockfile 与审计记录

| 文件 | 作用 |
|---|---|
| `reference/catalog.yml` | 权威清单，97 条；每条带 `commit` / `clone_url` / `pin_status` / `source` 四个字段 |
| `reference/fetch-manifest.txt` | 由 catalog 生成的 **5 列 pin lockfile**（`model` / `name` / `clone_url` / `commit` / `pin_status`，TAB 分隔，97 行数据 + 1 行表头 = 98 行） |
| `reference/AUDIT.md` | 候选项目审核表 ＋ **实际拉取 / 校验记录**（幂等跳过、pin 失效跳过、无源码镜像、失败数） |
| `reference/README.md` | 源码层目录语义与 `catalog.yml` 元数据字段规范 |

> ⚠ `fetch-manifest.txt` 是 **pin lockfile，不是拉取日志**；
> 拉取与校验的实际过程记录见 `reference/AUDIT.md`。

### 失效 pin（`pin_status: broken`，4 条）

重选 commit 会让已写好的行号引用全体漂移，因此只标注、不重选：

| 条目 | 分类 | 失效原因 | 受影响笔记 |
|---|---|---|---|
| `druid` | `columnar/` | gitlink pin `fa8dc991…` 在上游不存在 | `docs/db-wiki/columnar/druid.md`（当前 0 处行号引用） |
| `pebble` | `key-value/` | gitlink pin `68315f17…` 在上游不存在 | `docs/db-wiki/key-value/pebble.md`（4 处引用） |
| `tdengine` | `time-series/` | gitlink pin `62385b1e…` 在上游不存在 | `docs/db-wiki/time-series/tdengine.md`（75 处引用） |
| `dragonfly` | `key-value/` | gitlink pin `dafb825b…` 在上游不存在 | `docs/db-wiki/key-value/dragonfly.md`（2 处引用） |

## `docs/` —— 源码阅读笔记层

| 目录 | 篇数 | 内容 |
|---|---:|---|
| `docs/db-wiki/` | 68 | 数据库源码笔记，含向量 / 关系 / 图 / 时序等 12 个模型分类 |
| `docs/rag-wiki/` | 12 | RAG 框架源码笔记 |
| `docs/agent-wiki/` | 14 | Agent 框架源码笔记 |

（篇数不含各自的 `README.md`。）

笔记多数结论带精确的源码行号引用；少数因 gitlink pin 失效或无源码镜像而**无法校验**，
这类笔记顶部带 ⚠ 警示（各 wiki 的「无对应源码镜像的笔记」一节有清单）。

## 克隆

```bash
git clone https://github.com/yinchengwang/reference.git
```

克隆下来只有**清单层与笔记层**；源码层一律按需拉取（见下节）。

### ⚠ 禁止 `git submodule update --init --recursive`

本仓的 95 个第三方库都是 submodule，递归初始化会一次性拉取约 25 GB / 53.6 万文件。
**不要**执行 `git clone --recurse-submodules`，也不要执行带 `--recursive` 的 submodule 初始化。

按需拉取脚本在**父仓** `StillEvolving/scripts/` 里，**不在本仓**：

```bash
cd ../StillEvolving          # 本仓与父仓平级
bash scripts/fetch-reference.sh --name faiss      # 拉单个
bash scripts/fetch-reference.sh --model vector    # 拉某个分类
bash scripts/fetch-reference.sh --tier core       # 拉核心集
bash scripts/fetch-reference.sh --check           # 只校验，不拉取
```

脚本入口：[`../StillEvolving/scripts/fetch-reference.sh`](../StillEvolving/scripts/fetch-reference.sh)
（父仓 `scripts/` 另有 `bootstrap.sh` / `bootstrap.ps1` / `check_consistency.py` 及其测试）。

拉取地址与 pin 由 `reference/catalog.yml` 声明（`commit` / `clone_url` / `pin_status`），
**拉取与校验过程记录见 `reference/AUDIT.md`**。

## 本仓脚本

| 脚本 | 作用 |
|---|---|
| `scripts/check-wiki-refs.py` | 引用校验门禁：模式 A（子模块已 init，精确行号）/ 模式 B（未 init，禁精确行号）/ README 标记一致性 |
| `scripts/sync_catalog.py` | `catalog.yml` ↔ `fetch-manifest.txt` ↔ `.gitmodules` 三方同步与校验 |
| `scripts/test_sync_catalog.py` | `sync_catalog.py` 的单元测试 |

```bash
# 清单一致性校验（通过时输出：97 entries, 91 valid, 4 broken, 2 unresolvable）
python scripts/sync_catalog.py --check
```

## 引用校验门禁

`scripts/check-wiki-refs.py` 校验 wiki 里的源码行号引用是否仍然有效。

```bash
# 模式 A：子模块已 init 时做精确行号校验
python scripts/check-wiki-refs.py docs/db-wiki/vector/faiss.md \
  --submodules vector=reference/vector/faiss --repo-root . [--show]

# 模式 B：子模块未 init 时的合规性校验
python scripts/check-wiki-refs.py --mode-b --repo-root .

# README「深化」标记与 wiki 文件实际内容的一致性
python scripts/check-wiki-refs.py --mode-readme --repo-root .
```

参数说明：

- `--mode-b`：强制对全部模式 B 篇目做合规校验（零精确行号 ＋ 必须带「行号需校对」/「未 init」标注）。
- `--submodules <分类名>=<子模块路径>`：把 wiki 里的引用前缀映射到真实文件系统路径。
- `--repo-root`：指定仓库根目录（默认 `.`）。
- `--show`：打印命中行的内容，供人工做语义比对（脚本只能验「存在 / 越界 / 非空」）。

模式 B 覆盖 `MODE_B_WIKIS` 清单里的 10 篇（`boltdb` / `duckdb` / `lmdb` / `pklite` /
`arrow` / `datafusion` / `hnswlib` / `lance` / `pgvector` / `velox`）。

## 跨仓关系

本仓**不属于** StillEvolving 的 submodule 树，只通过相对路径引用父仓文档：

| 目标 | 相对路径 |
|---|---|
| 父仓 README | [`../StillEvolving/README.md`](../StillEvolving/README.md) |
| 目录规范 | [`../StillEvolving/docs/architecture.md`](../StillEvolving/docs/architecture.md) |
| 机器可读清单 | [`../StillEvolving/repos.yaml`](../StillEvolving/repos.yaml) |
| 按需拉取脚本 | [`../StillEvolving/scripts/fetch-reference.sh`](../StillEvolving/scripts/fetch-reference.sh) |

## 许可

MIT（见 `LICENSE`）。各 submodule 遵循其上游项目自身的许可协议。
