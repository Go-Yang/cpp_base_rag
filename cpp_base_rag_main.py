import os
import torch
from langchain.document_loaders import DirectoryLoader, TextLoader, PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import Chroma
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.llms import DeepSeek
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

# ===================== 【全局配置 - 纯通用C/C++工程RAG】 =====================
DEEPSEEK_API_KEY = "你的DeepSeek-Key"
DOC_DIR = "./cpp_base_knowledge"   # 纯底层C/C++通用知识库目录
VECTOR_DB_PATH = "./chroma_cpp_base_db"

# ===================== 1. 加载通用底层知识库文档 =====================
def load_base_cpp_docs():
    """只加载通用C/C++底层md/txt/pdf原理、工具链、调试文档"""
    loader = DirectoryLoader(
        DOC_DIR,
        glob="**/*.{md,txt,pdf}",
        loader_cls=lambda path: PyPDFLoader(path) if path.endswith(".pdf") else TextLoader(path),
        show_progress=True
    )
    return loader.load()

# ===================== 2. C/C++底层工程专属切分策略（核心） =====================
def split_base_cpp_text(docs):
    """
    适配：源码片段、Make/CMake脚本、汇编代码、报错日志、底层原理段落
    避免切碎函数、编译命令、堆栈日志、链接规则
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=120,
        separators=[
            "\n## ", "\n### ",
            "\n```cpp", "\n```c", "\n```asm", "\n```make", "\n```bash", "\n```log", "\n```",
            "\n\n", "\n", "。"
        ]
    )
    return splitter.split_documents(docs)

# ===================== 3. 本地通用Embedding（GPU自动加速） =====================
def get_local_embedding():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return HuggingFaceEmbeddings(
        model_name="BAAI/bge-small-zh-v1.5",
        model_kwargs={"device": device}
    )

# ===================== 4. 向量库持久化（增量兼容） =====================
def init_vector_database(split_docs, embedding):
    if os.path.exists(VECTOR_DB_PATH) and os.listdir(VECTOR_DB_PATH):
        # 已有向量库直接加载，无需全量重建
        db = Chroma(persist_directory=VECTOR_DB_PATH, embedding_function=embedding)
    else:
        db = Chroma.from_documents(
            documents=split_docs,
            embedding=embedding,
            persist_directory=VECTOR_DB_PATH
        )
        db.persist()
    return db

# ===================== 5. 检索+重排（解决底层术语误召回） =====================
def get_rerank_retriever(vector_db):
    # 粗召回5条，精筛3条高质量片段
    base_retriever = vector_db.as_retriever(search_kwargs={"k": 5})
    rerank = CrossEncoderReranker(
        model_name="BAAI/bge-reranker-v2-m3",
        top_n=3
    )
    return ContextualCompressionRetriever(base_retriever=base_retriever, base_compressor=rerank)

# ===================== 6. LLM初始化（严谨模式，杜绝原理幻觉） =====================
def get_strict_llm():
    return DeepSeek(
        model="deepseek-chat",
        api_key=DEEPSEEK_API_KEY,
        temperature=0.01,  # 极致严谨，底层原理不允许发散
        max_tokens=2048
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
    prompt = PromptTemplate(input_variables=["context", "question"], template=prompt_rule)
    return RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt}
    )

# ===================== 主程序入口 =====================
if __name__ == "__main__":
    print("===== 初始化通用C/C++底层工程RAG =====")
    docs = load_base_cpp_docs()
    print(f"加载底层工程文档总数：{len(docs)}")

    split_docs = split_base_cpp_text(docs)
    print(f"文本切片完成，总切片数：{len(split_docs)}")

    embed = get_local_embedding()
    db = init_vector_database(split_docs, embed)
    retriever = get_rerank_retriever(db)
    llm = get_strict_llm()
    qa_chain = build_cpp_base_qa_chain(retriever, llm)

    # 通用测试问题（纯底层无业务）
    test_query = "C++多重定义链接报错的底层成因与通用解决方案"
    res = qa_chain.invoke({"query": test_query})

    # 输出结果
    print("\n===== RAG 精准回答 =====")
    print(res["result"])
    print("\n===== 引用底层知识库来源 =====")
    for idx, doc in enumerate(res["source_documents"]):
        print(f"{idx+1}. {doc.metadata['source']}")
