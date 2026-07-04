from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from tools.file_tool import FILE_TOOLS
from tools.search import fetch_text_from_url
from campus_rag import search_notices, search_user_data
import model.config as config

SYSTEM_PROMPT = """你是一个可以访问网络、工作区文件和校园通知的助手。
需要读取、写入、追加或删除文件，以及创建目录时，请调用 file_tool。
需要了解项目结构时调用 list_dir，需要查找代码或文本时调用 search_file。
询问校园活动、比赛、课程、讲座、报名等公共信息时，请调用 search_campus_notices。
询问用户个人课表、成绩、教务信息等私有数据时，请先调用 search_my_data。
只能操作工作区内的路径；删除目录前必须确保目录为空。
"""


@tool
def search_campus_notices(query: str) -> str:
    """搜索校园官方通知，获取活动、比赛、课程、讲座、报名等公共信息。"""
    return search_notices(query)


@tool
def search_my_data(query: str, user_id: str) -> str:
    """搜索用户个人数据（个人上传或爬取的教务、课表等私有信息）。
    必须提供 user_id 来标识用户身份，不同用户之间的数据完全隔离。
    """
    return search_user_data(query, user_id)


def build_agent():
    """创建包含网络访问、工作区文件读写和校园通知检索能力的 Agent。"""
    return create_agent(
        model=config.init_chat(),
        tools=[fetch_text_from_url, *FILE_TOOLS, search_campus_notices, search_my_data],
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
    request = "今年暑假有什么活动？"
    print(run_agent(request, thread_id="campus-query"))
