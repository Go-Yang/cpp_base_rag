"""C/C++ 底层工程知识库 RAG 问答入口。

依赖：见 requirements.txt（LangChain 0.3.x 系列）。

用法：
    # 1. 设置 DeepSeek API Key
    #    Git Bash:  export DEEPSEEK_API_KEY=sk-xxx
    #    PowerShell: $env:DEEPSEEK_API_KEY="sk-xxx"

    # 2. 提问（不传问题则使用内置测试问题）
    python cpp_base_rag_main.py "multiple definition 的底层成因与解决方案"

    # 3. 新增知识文档后重建向量库
    #    Git Bash:  RAG_REBUILD=1 python cpp_base_rag_main.py
    #    PowerShell: $env:RAG_REBUILD="1"; python cpp_base_rag_main.py
"""

import os
import shutil
import sys
from typing import Any

import torch
from chromadb.config import Settings as ChromaSettings
from langchain.chains import RetrievalQA
from langchain.retrievers import ContextualCompressionRetriever
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===================== 【全局配置 - 纯通用C/C++工程RAG】 =====================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DOC_DIR = os.path.join(BASE_DIR, "cpp_base_knowledge")      # 纯底层C/C++通用知识库目录
VECTOR_DB_PATH = os.path.join(BASE_DIR, "chroma_cpp_base_db")

def _resolve_model(env_var, local_rel_path, default_name):
    """模型路径优先级：环境变量 > 项目内 models/ 本地目录 > HuggingFace 模型名。"""
    override = os.getenv(env_var)
    if override:
        return override
    local_dir = os.path.join(BASE_DIR, local_rel_path)
    return local_dir if os.path.isdir(local_dir) else default_name


EMBEDDING_MODEL = _resolve_model(
    "RAG_EMBEDDING_MODEL", os.path.join("models", "bge-small-zh-v1.5"), "BAAI/bge-small-zh-v1.5"
)
RERANKER_MODEL = _resolve_model(
    "RAG_RERANKER_MODEL", os.path.join("models", "bge-reranker-v2-m3"), "BAAI/bge-reranker-v2-m3"
)
CHUNK_SIZE = 700
CHUNK_OVERLAP = 120
TOP_K = 5     # 向量粗召回条数
TOP_N = 3     # 重排后保留条数

# 目录索引文件，不作为知识文档入库
EXCLUDED_FILE_NAMES = {"tmp.txt"}


# ===================== 1. 加载通用底层知识库文档 =====================
def load_base_cpp_docs(doc_dir=DOC_DIR):
    """只加载通用C/C++底层md/txt/pdf原理、工具链、调试文档。"""
    if not os.path.isdir(doc_dir):
        raise FileNotFoundError(f"知识库目录不存在：{doc_dir}")
    docs = []
    for root, _, file_names in os.walk(doc_dir):
        for file_name in sorted(file_names):
            if file_name in EXCLUDED_FILE_NAMES:
                continue
            path = os.path.join(root, file_name)
            lower = file_name.lower()
            if lower.endswith((".md", ".txt")):
                # 显式指定 utf-8：Windows 默认编码是 GBK，中文文档会读成乱码或直接报错
                loader = TextLoader(path, encoding="utf-8", autodetect_encoding=True)
            elif lower.endswith(".pdf"):
                loader = PyPDFLoader(path)
            else:
                continue
            docs.extend(loader.load())
    return docs


# ===================== 2. C/C++底层工程专属切分策略（核心） =====================
def split_base_cpp_text(docs, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP):
    """
    适配：源码片段、Make/CMake脚本、汇编代码、报错日志、底层原理段落
    避免切碎函数、编译命令、堆栈日志、链接规则
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[
            "\n## ", "\n### ",
            "\n```cpp", "\n```c", "\n```asm", "\n```make", "\n```bash", "\n```log", "\n```",
            "\n\n", "\n", "。",
        ],
    )
    return splitter.split_documents(docs)


# ===================== 3. 本地通用Embedding（GPU自动加速） =====================
def get_local_embedding(device=None):
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    try:
        return HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True},
        )
    except Exception as exc:
        raise RuntimeError(
            f"加载 Embedding 模型失败：{EMBEDDING_MODEL}\n"
            "如果无法联网下载，请先手动获取模型，然后设置环境变量指向本地目录：\n"
            "  Git Bash:  export RAG_EMBEDDING_MODEL=/path/to/bge-small-zh-v1.5\n"
            "  PowerShell: $env:RAG_EMBEDDING_MODEL=\"D:\\models\\bge-small-zh-v1.5\""
        ) from exc


# ===================== 4. 向量库持久化 =====================
def init_vector_database(split_docs, embedding, persist_dir=VECTOR_DB_PATH, force_rebuild=False):
    """已有向量库直接加载；force_rebuild=True 时删除旧库重建（新增/修改文档后使用）。"""
    if force_rebuild and os.path.isdir(persist_dir):
        shutil.rmtree(persist_dir)
    client_settings = ChromaSettings(anonymized_telemetry=False)
    if os.path.isdir(persist_dir) and os.listdir(persist_dir):
        # 已有向量库直接加载，无需全量重建
        return Chroma(
            persist_directory=persist_dir,
            embedding_function=embedding,
            client_settings=client_settings,
        )
    # langchain-chroma 会自动持久化，不需要再调用 persist()
    return Chroma.from_documents(
        documents=split_docs,
        embedding=embedding,
        persist_directory=persist_dir,
        collection_metadata={"hnsw:space": "cosine"},
        client_settings=client_settings,
    )


def build_vector_db(doc_dir=DOC_DIR, persist_dir=VECTOR_DB_PATH, force_rebuild=False,
                    chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP):
    """加载文档 → 切分 → 向量化，返回 (db, 文档数, 切片数)。"""
    docs = load_base_cpp_docs(doc_dir)
    split_docs = split_base_cpp_text(docs, chunk_size, chunk_overlap)
    embedding = get_local_embedding()
    db = init_vector_database(split_docs, embedding, persist_dir, force_rebuild)
    return db, len(docs), len(split_docs)


# ===================== 5. 检索+重排（解决底层术语误召回） =====================
class CrossEncoderReranker(BaseDocumentCompressor):
    """基于 sentence-transformers CrossEncoder 的文档重排器。

    说明：LangChain 自带的 CrossEncoderReranker 在不同版本中构造参数不一致
    （model / model_name），这里直接封装 sentence-transformers，
    行为稳定，也方便自己换模型、改打分逻辑做实验。
    """

    reranker_model: str = RERANKER_MODEL
    top_n: int = TOP_N
    encoder: Any = None

    def __init__(self, model_name=RERANKER_MODEL, top_n=TOP_N, device=None, **data):
        super().__init__(reranker_model=model_name, top_n=top_n, **data)
        from sentence_transformers import CrossEncoder

        device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        try:
            self.encoder = CrossEncoder(self.reranker_model, device=device)
        except Exception as exc:
            raise RuntimeError(
                f"加载重排模型失败：{self.reranker_model}\n"
                "可以设置 RAG_RERANKER_MODEL 指向本地模型目录；\n"
                "暂时不需要重排时，可设置 RAG_RERANK=0 跳过（评测时也可不加 --rerank）。"
            ) from exc

    def compress_documents(self, documents, query, callbacks=None):
        if not documents:
            return []
        pairs = [(query, doc.page_content) for doc in documents]
        scores = self.encoder.predict(pairs)
        ranked = sorted(zip(documents, scores), key=lambda pair: pair[1], reverse=True)
        return [doc for doc, _ in ranked[: self.top_n]]


def get_base_retriever(vector_db, k=TOP_K):
    """纯向量召回，返回 top-k 文档（评测基线用）。"""
    return vector_db.as_retriever(search_kwargs={"k": k})


def get_rerank_retriever(vector_db, k=TOP_K, top_n=TOP_N, model_name=RERANKER_MODEL):
    """粗召回 k 条，精排后保留 top_n 条，解决底层术语误召回。"""
    rerank = CrossEncoderReranker(model_name=model_name, top_n=top_n)
    return ContextualCompressionRetriever(
        base_retriever=get_base_retriever(vector_db, k=k),
        base_compressor=rerank,
    )


def get_retriever(vector_db):
    """问答用检索器：默认向量召回 + 重排；RAG_RERANK=0 时只用向量召回。"""
    if os.getenv("RAG_RERANK", "1").lower() in {"0", "false", "no"}:
        return get_base_retriever(vector_db)
    return get_rerank_retriever(vector_db)


# ===================== 6. LLM初始化（严谨模式，杜绝原理幻觉） =====================
def get_strict_llm():
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "未设置 DEEPSEEK_API_KEY 环境变量。\n"
            "Git Bash:  export DEEPSEEK_API_KEY=sk-xxx\n"
            "PowerShell: $env:DEEPSEEK_API_KEY=\"sk-xxx\""
        )
    return ChatDeepSeek(
        model="deepseek-chat",
        api_key=DEEPSEEK_API_KEY,
        temperature=0.01,  # 极致严谨，底层原理不允许发散
        max_tokens=2048,
    )


# ===================== 7. 【核心】通用C/C++底层工程专属Prompt =====================
def build_cpp_base_qa_chain(retriever, llm):
    # 纯通用、无业务、无框架，只针对C/C++全底层工程流程
    prompt_rule = """
你是通用C/C++底层工程专家，仅基于参考知识库内容回答，严禁编造底层原理、编译规则、调试命令、内存机制。
无匹配内容直接回复：【未收录该C/C++底层工程知识点】

回答范围严格限定：
1. 源码层：语法依赖、头文件、宏预处理、变量作用域、跨文件符号引用
2. 工具链层：GCC/G++/LD编译、汇编、链接全流程原理与报错
3. 构建系统：Makefile、CMake通用构建逻辑、编译优化、交叉编译
4. 运行机制：ELF文件、进程加载、虚拟内存、段空间分布
5. 资源管理：堆/栈内存、文件句柄、线程资源、内存泄漏、指针异常
6. 调试体系：GDB调试、CoreDump崩溃分析、addr2line、Valgrind、内存检测

回答规范：
- 原理类：分层讲解底层机制、触发条件、核心特性
- 报错类：输出报错根因、通用排查流程、修复方案、完整命令
- 内存问题：标注问题成因、内存布局风险、规避方案
- 所有命令/代码/配置必须使用标准代码块

参考知识库内容：
{context}

用户问题：{question}
"""
    prompt = PromptTemplate.from_template(prompt_rule)
    return RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt},
    )


# ===================== 主程序入口 =====================
if __name__ == "__main__":
    question = " ".join(sys.argv[1:]).strip() or "C++多重定义链接报错的底层成因与通用解决方案"
    force_rebuild = os.getenv("RAG_REBUILD", "").lower() in {"1", "true", "yes"}

    print("===== 初始化通用C/C++底层工程RAG =====")
    docs = load_base_cpp_docs()
    print(f"加载底层工程文档总数：{len(docs)}")

    split_docs = split_base_cpp_text(docs)
    print(f"文本切片完成，总切片数：{len(split_docs)}")

    embed = get_local_embedding()
    db = init_vector_database(split_docs, embed, force_rebuild=force_rebuild)
    retriever = get_retriever(db)
    llm = get_strict_llm()
    qa_chain = build_cpp_base_qa_chain(retriever, llm)

    res = qa_chain.invoke({"query": question})

    # 输出结果
    print("\n===== RAG 精准回答 =====")
    print(res["result"])
    print("\n===== 引用底层知识库来源 =====")
    for idx, doc in enumerate(res["source_documents"], 1):
        print(f"{idx}. {doc.metadata.get('source', '未知来源')}")
