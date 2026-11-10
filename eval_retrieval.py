"""检索评测：只测"该命中的文档有没有被检索到"，不调用 LLM。

指标：
    - 命中率 = 期望文档出现在返回结果前 top-k 的题目占比
    - 平均命中排名 = 命中题目中，期望文档排在第几位（越小越好）

用法：
    python eval_retrieval.py --rebuild                    # 纯向量召回 top-5（基线）
    python eval_retrieval.py --rebuild --rerank           # 向量召回 top-5 + 重排后 top-3
    python eval_retrieval.py --rebuild --chunk-size 1000 --chunk-overlap 150
    python eval_retrieval.py --rebuild --reranker-model BAAI/bge-reranker-base

说明：
    - 每次运行默认重建 chroma_eval_db（评测库只是缓存，删了可重建）
    - --rerank 首次运行会下载 reranker 模型（v2-m3 约 2GB+，base 约 1GB）
    - 新增评测题：直接编辑 eval_questions.json，字段说明见该文件顶部
"""

import argparse
import json
import os

from cpp_base_rag_main import (
    BASE_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DOC_DIR,
    RERANKER_MODEL,
    TOP_K,
    TOP_N,
    build_vector_db,
    get_base_retriever,
    get_rerank_retriever,
)

DEFAULT_QUESTIONS = os.path.join(BASE_DIR, "eval_questions.json")
DEFAULT_EVAL_DB = os.path.join(BASE_DIR, "chroma_eval_db")


def parse_args():
    parser = argparse.ArgumentParser(description="检索命中率评测（不调用 LLM）")
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS, help="评测题 JSON 路径")
    parser.add_argument("--doc-dir", default=DOC_DIR, help="知识库目录")
    parser.add_argument("--db-path", default=DEFAULT_EVAL_DB, help="评测向量库目录")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=CHUNK_OVERLAP)
    parser.add_argument("--k", type=int, default=TOP_K, help="向量粗召回条数（不重排时即评测 top-k）")
    parser.add_argument("--top-n", type=int, default=TOP_N, help="重排后保留条数")
    parser.add_argument("--rerank", action="store_true", help="启用 CrossEncoder 重排")
    parser.add_argument("--reranker-model", default=RERANKER_MODEL)
    parser.add_argument("--reuse-db", action="store_true", help="复用已有评测向量库，不重建")
    parser.add_argument("--rebuild", action="store_true", help="重建评测向量库（默认行为，显式写出更直观）")
    return parser.parse_args()


def main():
    args = parse_args()

    with open(args.questions, encoding="utf-8") as f:
        cases = json.load(f)
    if not cases:
        print(f"评测题为空：{args.questions}")
        return

    db, n_docs, n_chunks = build_vector_db(
        doc_dir=args.doc_dir,
        persist_dir=args.db_path,
        force_rebuild=not args.reuse_db,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    if args.rerank:
        retriever = get_rerank_retriever(
            db, k=args.k, top_n=args.top_n, model_name=args.reranker_model
        )
        eval_k = args.top_n
        mode = f"向量召回 top-{args.k} + 重排 top-{args.top_n}"
    else:
        retriever = get_base_retriever(db, k=args.k)
        eval_k = args.k
        mode = f"纯向量召回 top-{args.k}"

    print(f"文档 {n_docs} 篇，切片 {n_chunks} 条 | {mode}")
    print(f"评测题 {len(cases)} 条 | chunk_size={args.chunk_size}, overlap={args.chunk_overlap}")
    print("=" * 72)

    hits = 0
    hit_ranks = []
    per_category = {}

    for case in cases:
        question = case["question"]
        expected = case["expected"]
        acceptable = {expected, *case.get("also_ok", [])}
        category = case.get("category", "未分类")

        docs = retriever.invoke(question)

        rank = None
        for i, doc in enumerate(docs[:eval_k], 1):
            source = os.path.basename(doc.metadata.get("source", ""))
            if source in acceptable:
                rank = i
                break

        stat = per_category.setdefault(category, [0, 0])
        stat[1] += 1
        if rank is not None:
            hits += 1
            hit_ranks.append(rank)
            stat[0] += 1
            print(f"  [命中] [{category}] rank {rank}  {question}")
        else:
            got = ", ".join(
                os.path.basename(doc.metadata.get("source", "?")) for doc in docs[:eval_k]
            )
            print(f"  [未命中] [{category}]  {question}")
            print(f"       期望: {expected}")
            print(f"       实际: {got}")

    total = len(cases)
    print("=" * 72)
    print(f"总命中率: {hits}/{total} = {hits / total:.1%}  (top-{eval_k})")
    if hit_ranks:
        print(f"平均命中排名: {sum(hit_ranks) / len(hit_ranks):.2f}")
    for category in sorted(per_category):
        hit, n = per_category[category]
        print(f"  [{category}] {hit}/{n} = {hit / n:.0%}")


if __name__ == "__main__":
    main()
