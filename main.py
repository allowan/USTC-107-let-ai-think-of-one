import model.config as config
import urllib.error
import urllib.request

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from campus_rag import search_notices

@tool
def fetch_text_from_url(url: str) -> str:
    """Fetch the document from a URL.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; quickstart-research/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except urllib.error.URLError as e:
        return f"Fetch failed: {e}"
    text = raw.decode("utf-8", errors="replace")
    return text

@tool
def search_campus_notices(query: str) -> str:
    """搜索校园通知，获取活动、比赛、课程、讲座、报名等信息。
    当用户询问校园相关问题时使用此工具。
    """
    return search_notices(query)


checkpointer = InMemorySaver()

SYSTEM_PROMPT = """you are a helper which can search from the Internet and campus notices"""
content = "今年暑假有什么活动？"

agent = create_agent(
    model=config.init_chat(),
    tools=[fetch_text_from_url, search_campus_notices],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)

agent_result = agent.invoke(
    {"messages": [{"role": "user", "content": content}]},
    config={"configurable": {"thread_id": "great-gatsby-lc"}},
)

print(agent_result["messages"][-1].content_blocks)