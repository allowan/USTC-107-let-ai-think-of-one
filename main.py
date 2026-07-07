from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from tools.file_tool import FILE_TOOLS
from tools.search import fetch_text_from_url
from campus_rag import search_notices, search_user_data
import model.config as config

SYSTEM_PROMPT = """你是中国科学技术大学的校园信息助手。

## 工具使用
- 校园活动、比赛、课程、讲座、报名 → search_campus_notices
- 用户个人课表、成绩、教务信息 → search_my_data
- 文件读写、目录操作 → file_tool / list_dir / search_file 等
- 所有文件操作限于工作区目录，删除目录前确保为空

## 回答规范
1. 先在心里梳理检索到的信息要点，再用自己的话组织成自然的回答
2. 严禁输出任何来源标记，包括但不限于：文件名（xxx.txt）、编号（[1]）、URL、分隔符
3. 严禁使用"根据搜索结果""根据上下文""检索结果显示"等措辞
4. 如果多条信息相关，直接综合叙述，不要逐条罗列
5. 如果检索结果为空或完全无关，直接说"未找到相关信息"
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
