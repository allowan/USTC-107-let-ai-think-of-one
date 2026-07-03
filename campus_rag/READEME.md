zfm:

**环境安装**

python环境依赖：requirements.txt

测试用的模型：

到 [ollama.com](https://ollama.com) 下载对应系统版本并安装ollama。

对话模型：ollama pull llama3.1:8b

嵌入模型：ollama pull nomic-embed-text

以上模型大概5G

对话模型和嵌入模型可换成openai格式的模型

**代码部分**

`.env`：配置模型提供商（ollama / openai）及具体模型名称

`llm_factory.py`：根据 `.env` 创建对话模型和嵌入模型的实例，支持 ollama 和 openai 两种 provider

`config.py`：使用 **LlamaIndex**，配置全局参数（模型、chunk_size、chunk_overlap 等）

`data_loader.py`：从 `data/` 目录读取 `.txt` 文件，返回 Document 列表

`index_manager.py`：基于 ChromaDB（开源向量库）的 `RAGSystem` 类，实现索引的创建和加载

`query.py`：封装 `search_notices()` 接口，内置校园通知助手的提示词模板

`__init__.py`：包入口，自动加载 `.env` 并导出 `search_notices`

以上我们实现了一个最简单的RAG，它非常傻，还不如普通的检索装置，但不必为此感到大惊小怪，我们要尝试去改进它

现在可以这么测试

```
python -c "from campus_rag import search_notices; print(search_notices('今年暑假有什么活动？'))"
```



​                                           