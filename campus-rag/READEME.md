zfm:

**环境安装**

python环境依赖：requirements.txt

测试用的模型：

到 [ollama.com](https://ollama.com) 下载对应系统版本并安装ollama。

对话模型：ollama pull llama3.1:8b

嵌入模型：ollama pull nomic-embed-text

以上模型大概5G

控制台运行

``` bash
 python -c "from FlagEmbedding import FlagReranker; FlagReranker('BAAI/bge-reranker-base', use_fp16=True)"
```

下载重排序模型（1G多）

对话模型和嵌入模型可换成openai格式的模型

**代码部分**

.env：选用模型信息

`llm_facroty.py`：根据`.env`创建对话模型和嵌入模型的实例

`config.py`：我使用的是 **LlamaIndex**，这个文件用于配置参数

`data_loader.py`：从data读取数据

`index_manager.py`：建立一个ChromaDB(一个开源的向量库)，实现建立索引和读取索引

`test_static.py`：简单写了一个提示词，测试了一个问题

以上我们实现了一个最简单的RAG，它非常傻，还不如普通的检索装置，但不必为此感到大惊小怪，我们要尝试去改进它



​                                           