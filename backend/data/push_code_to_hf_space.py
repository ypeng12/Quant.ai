# backend/data/push_code_to_hf_space.py
"""
Uploads the complete local codebase directly to Hugging Face Space (Ypeng12/quant-ai)
ensuring that all Python scripts, configs, and frontend files are 100% up-to-date on Hugging Face.
"""

import os
import sys

def push_code_to_hf_space():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    space_id = "Ypeng12/quant-ai"
    
    print(f"🚀 开始将本地最新代码上传至 Hugging Face Space ({space_id})...")

    try:
        from huggingface_hub import HfApi
        token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_HUB_TOKEN")
        api = HfApi(token=token) if token else HfApi()

        api.upload_folder(
            folder_path=repo_root,
            repo_id=space_id,
            repo_type="space",
            ignore_patterns=[
                ".git/*",
                "node_modules/*",
                "__pycache__/*",
                "*.pyc",
                "venv/*",
                ".venv/*",
                "dist/*",
                "build/*"
            ],
            commit_message="feat(ai): sync complete codebase and DP max profit models to HF Space"
        )
        print(f"✅ 成功将最新全量代码与配置文件同步上传至 Hugging Face Space ({space_id})！")
    except Exception as e:
        print(f"❌ 上传至 Hugging Face Space 提示/失败: {e}")

if __name__ == "__main__":
    push_code_to_hf_space()
