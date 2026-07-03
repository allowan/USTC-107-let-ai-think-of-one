from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from tools.file_tool import FILE_TOOLS
from tools.search import fetch_text_from_url
import model.config as config

SYSTEM_PROMPT = """你是一个可以访问网络和工作区文件的助手。
需要读取、写入、追加或删除文件，以及创建目录时，请调用 file_tool。
需要了解项目结构时调用 list_dir，需要查找代码或文本时调用 search_file。
只能操作工作区内的路径；删除目录前必须确保目录为空。
"""


def build_agent():
    """创建包含网络访问和工作区文件读写能力的 Agent。"""
    return create_agent(
        model=config.init_chat(),
        tools=[fetch_text_from_url, *FILE_TOOLS],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )


def run_agent(content: str, thread_id: str = "default") -> str:
    """供其他 Python 模块调用 Agent，并返回最终回复。"""
    agent = build_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": content}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return result["messages"][-1].content


if __name__ == "__main__":
    request = (
        "请使用 file_tool 将‘Hello from file_tool!’写入 output/example.txt，"
        "然后读取该文件并告诉我文件内容。"
    )
    print(run_agent(request, thread_id="file-tool-demo"))
