#test_static.py
import config
from index_manager import RAGSystem
from llama_index.core.prompts import PromptTemplate

custom_prompt = PromptTemplate(
      "你是校园通知助手，请严格根据下面的通知片段回答用户问题。\n\n"
      "要求：\n"
      "1. 用中文回答，简洁清晰\n"
      "2. 若涉及多个条目（如多个活动、多项通知），请用序号排列\n"
      "3. 若通知片段中没有相关信息，请明确说\"未在通知中找到相关信息\"，不要编造\n"
      "4. 不要调用其他工具\n"
      "5. 理解后回答,语句通顺\n"
      "通知片段：\n{context_str}\n\n"
      "用户问题：{query_str}\n\n"
      "你的回答："
)

rag = RAGSystem()
index = rag.get_or_create_public_index("./data")
query_engine = index.as_query_engine(similarity_top_k=20, text_qa_template=custom_prompt)

response = query_engine.query("今年暑假有什么活动？")
print(response)

for node in response.source_nodes:
    print(f"[来源：{node.metadata['source']}] {node.text[:100]}...")