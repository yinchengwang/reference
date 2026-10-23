# book-reference

本仓是 `book` 主仓的**参考资料库**，包含两类资产：

## `reference/` —— 第三方源码镜像

14 个技术分类、95 个 git submodule，覆盖向量库、关系型数据库、搜索引擎、
图数据库、时序数据库、消息队列等方向的上游实现。用于对照学习与源码检索。

| 分类 | 说明 |
|---|---|
| `ai/` | Agent 框架与 RAG 工具链 |
| `benchmark/` | 基准测试套件（ANN、TPC-H/DS、vectordb） |
| `columnar/` | 列式存储（ClickHouse、Doris、StarRocks…） |
| `distributed-sql/` | 分布式 SQL（CockroachDB、TiDB、YugabyteDB…） |
| `document/` | 文档数据库（MongoDB、CouchDB、RavenDB…） |
| `embedded/` | 嵌入式存储（SQLite、BoltDB、DuckDB、LMDB…） |
| `extension/` | 扩展组件（pgvector、Arrow、DataFusion、HNSWLib…） |
| `graph/` | 图数据库（Neo4j、JanusGraph、Kuzu…） |
| `key-value/` | 键值存储（Redis、RocksDB、Badger…） |
| `relational/` | 关系型数据库（PostgreSQL、MySQL、openGauss…） |
| `search/` | 搜索引擎（Elasticsearch、Meilisearch、Tantivy…） |
| `stream/` | 流处理（Kafka、NATS、Pulsar…） |
| `time-series/` | 时序数据库（InfluxDB、IoTDB、TDengine…） |
| `vector/` | 向量数据库（Faiss、Milvus、Qdrant、Weaviate…） |

目录清单见 `reference/catalog.yml`，拉取记录见 `reference/fetch-manifest.txt`。

## `docs/` —— 源码阅读笔记层

`db-wiki/`（75 篇）、`rag-wiki/`（13 篇）、`agent-wiki/`（15 篇），
是 `reference/` 源码的**阅读笔记**：每条结论都带精确的源码行号引用。

| 目录 | 内容 |
|---|---|
| `docs/db-wiki/` | 数据库源码笔记，含向量/关系/图/时序等 12 个模型分类 |
| `docs/rag-wiki/` | RAG 框架源码笔记 |
| `docs/agent-wiki/` | Agent 框架源码笔记 |

## 克隆

```bash
git clone --recurse-submodules https://github.com/yinchengwang/reference.git
# 或先克隆再初始化
git submodule update --init --recursive --depth 1
```

## 引用校验门禁

`scripts/check-wiki-refs.py` 校验 wiki 里的源码行号引用是否仍然有效。

```bash
# 模式 A：子模块已 init 时做精确行号校验
python scripts/check-wiki-refs.py docs/db-wiki/vector/faiss.md \
  --submodules vector=reference/vector/faiss --repo-root .

# 模式 B：子模块未 init 时的合规性校验
python scripts/check-wiki-refs.py --mode-b --repo-root .
```

模式 B 覆盖 `MODE_B_WIKIS` 清单里的 10 篇（boltdb/duckdb/lmdb/pklite/arrow/
datafusion/hnswlib/lance/pgvector/velox），要求这些文件不使用精确行号，
必须带 `approx` 标注。

## 许可

MIT（见 `LICENSE`）。各 submodule 遵循其上游项目自身的许可协议。
