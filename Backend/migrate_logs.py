import re
from pathlib import Path

files_to_process = [
    "WeaviateGeminiInterface/pdf_processor.py",
    "WeaviateGeminiInterface/weaviate_handler.py",
    "WeaviateGeminiInterface/gemini_handler.py",
]

for filepath in files_to_process:
    p = Path(filepath)
    content = p.read_text()
    
    # Add logger setup if not already present
    if "logger = logging.getLogger(__name__)" not in content:
        lines = content.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("import ") or line.startswith("from "):
                insert_idx = i + 1
        
        lines.insert(insert_idx, "import logging")
        lines.insert(insert_idx+1, "logger = logging.getLogger(__name__)")
        content = "\n".join(lines)
    
    # Replace prints
    content = re.sub(r"print\(\s*(f?[\"'])❌([^\"']*)[\"']\s*\)", r"logger.error(\1❌\2\1)", content)
    content = re.sub(r"print\(\s*(f?[\"'])⚠️([^\"']*)[\"']\s*\)", r"logger.warning(\1⚠️\2\1)", content)
    content = re.sub(r"print\(\s*(f?[\"'])Warning:([^\"']*)[\"']\s*\)", r"logger.warning(\1Warning:\2\1)", content)
    
    # Standard prints (handles basic quotes without nesting)
    content = re.sub(r"print\(\s*(f?[\"'][^\"']*[\"'])\s*\)", r"logger.info(\1)", content)
    
    p.write_text(content)
    print(f"Updated {filepath}")
