#data_loader.py
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
import os

def load_documents_from_files(directory:str)->list:
    """读取data文件,输入为文件夹路径,输出为Document列表"""
    documents = []
    for filename in os.listdir(directory):
        if filename.endswith(".txt"):
            file_path = os.path.join(directory, filename)
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
                if content:
                    documents.append(Document(text=content, metadata={"source": filename}))
    return documents

                  
