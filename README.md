# cpp_base_rag

基于本地知识库 + DeepSeek 的 C/C++ 底层工程 RAG 问答 Demo。

- **知识库**：[cpp_base_knowledge/](cpp_base_knowledge/)，Markdown 按主题分类
- **Embedding**：`BAAI/bge-small-zh-v1.5`（本地推理，有 GPU 自动用）
- **向量库**：Chroma（本地持久化）
- **检索**：向量召回 top-5 → CrossEncoder 重排 top-3
- **LLM**：DeepSeek（temperature 0.01，强约束只依据知识库回答）
- **评测**：`eval_retrieval.py` 统计检索命中率（不调用 LLM，免费且快）

## 安装

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

> 国内网络下载 HuggingFace 模型慢或失败时，可设置镜像（Git Bash）：
> `export HF_ENDPOINT=https://hf-mirror.com`

### 离线使用（本地模型）

模型放在项目内 `models/bge-small-zh-v1.5/` 时，代码会**自动优先使用本地目录**，无需设置环境变量。
也可以把模型放到任意位置，用环境变量指定：

```bash
# Git Bash / Linux / macOS
export RAG_EMBEDDING_MODEL=/path/to/bge-small-zh-v1.5
export RAG_RERANKER_MODEL=/path/to/bge-reranker-v2-m3

# PowerShell
$env:RAG_EMBEDDING_MODEL="D:\models\bge-small-zh-v1.5"
$env:RAG_RERANKER_MODEL="D:\models\bge-reranker-v2-m3"
```

暂时不下载 reranker（约 2GB）时，可以用纯向量召回跑问答：

```bash
RAG_RERANK=0 python cpp_base_rag_main.py "你的问题"
```

## 配置 API Key

```bash
# Git Bash / Linux / macOS
export DEEPSEEK_API_KEY=sk-xxx

# PowerShell
$env:DEEPSEEK_API_KEY="sk-xxx"
```

## 问答

```bash
python cpp_base_rag_main.py "multiple definition 的底层成因与解决方案"
```

不传问题时使用内置测试问题。

## 检索评测（不调用 LLM）

评测题在 [eval_questions.json](eval_questions.json)：每题标注「应该命中哪篇文档」，
脚本统计 **top-k 命中率** 和 **平均命中排名**。

```bash
# 基线：纯向量召回 top-5
python eval_retrieval.py --rebuild

# 加重排：召回 top-5 → 重排 top-3（首次运行会下载 reranker 模型）
python eval_retrieval.py --rebuild --rerank

# 重排换小模型，下载量和显存占用更小
python eval_retrieval.py --rebuild --rerank --reranker-model BAAI/bge-reranker-base

# 对比实验：调 chunk 大小
python eval_retrieval.py --rebuild --chunk-size 1000 --chunk-overlap 150
```

新增知识文档后，向量库需要重建：

```bash
# 问答时强制重建
RAG_REBUILD=1 python cpp_base_rag_main.py "你的问题"     # PowerShell: $env:RAG_REBUILD="1"

# 或评测时加 --rebuild（评测库独立于问答库）
python eval_retrieval.py --rebuild
```

## 目录结构

```
cpp_base_rag_main.py     # 问答主流程：加载 → 切分 → 向量化 → 检索重排 → LLM
eval_retrieval.py        # 检索命中率评测（不调用 LLM）
eval_questions.json      # 评测题：问题 + 期望命中的文档
cpp_base_knowledge/      # 知识库（01 源码层、02 编译工具链……）
models/                  # 本地模型（bge-small-zh-v1.5 等，可选）
chroma_cpp_base_db/      # 问答向量库（自动生成，可删）
chroma_eval_db/          # 评测向量库（自动生成，可删）
```

## 扩展知识库

1. 在 `cpp_base_knowledge/` 对应分类下新增 `.md`
2. 在 `eval_questions.json` 补 1–2 条对应评测题
3. `python eval_retrieval.py --rebuild` 看命中率有没有下降

> 提示：新增文档后如果不重建向量库，新文档不会生效。
> 注意 `tmp.txt` 是目录索引，代码里已排除，不会入库。
