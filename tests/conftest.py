import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("PROMPTS_DIR", os.path.join(ROOT, "prompts"))
os.environ.setdefault("CORPUS_DIR", os.path.join(ROOT, "corpus"))
