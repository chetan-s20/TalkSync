import os
import glob
import ast
import importlib

root_dir = os.path.abspath(".")
py_files = [
    os.path.relpath(p, root_dir).replace('\\', '/')
    for p in glob.glob("**/*.py", recursive=True)
    if not '.agents' in p and not 'venv' in p and not '__pycache__' in p
]

print("=== CLASSES AND FUNCTIONS PER MODULE ===")

module_exports = {}

for py_file in sorted(py_files):
    if py_file.endswith('__init__.py'):
        mod_name = py_file[:-12].replace('/', '.')
    else:
        mod_name = py_file[:-3].replace('/', '.')
    if not mod_name:
        continue
    
    with open(py_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
        content = f.read()
    try:
        tree = ast.parse(content, filename=py_file)
    except Exception as e:
        print(f"AST Error in {py_file}: {e}")
        continue
        
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    
    module_exports[mod_name] = {'classes': classes, 'functions': functions, 'file': py_file}
    print(f"Module: {mod_name:<35} Classes: {classes}  Functions: {functions}")

