import os
import glob
import ast
from collections import defaultdict

root_dir = os.path.abspath(".")
py_files = [
    os.path.relpath(p, root_dir).replace('\\', '/')
    for p in glob.glob("**/*.py", recursive=True)
    if not '.agents' in p and not 'venv' in p and not '__pycache__' in p
]

imports_by_root = defaultdict(list)
legacy_vs_modern = defaultdict(list)

for py_file in sorted(py_files):
    with open(py_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
        content = f.read()
    try:
        tree = ast.parse(content, filename=py_file)
    except Exception as e:
        continue

    for node in ast.walk(tree):
        mod = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                top_pkg = mod.split('.')[0]
                imports_by_root[top_pkg].append((py_file, node.lineno, f"import {mod}"))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module
                top_pkg = mod.split('.')[0]
                symbols = ", ".join(alias.name for alias in node.names)
                imports_by_root[top_pkg].append((py_file, node.lineno, f"from {mod} import {symbols}"))

print("=== TOP-LEVEL PACKAGES IMPORT SUMMARY ===")
for pkg in sorted(imports_by_root.keys()):
    print(f"Package '{pkg}': {len(imports_by_root[pkg])} import statements")

print("\n=== BREAKDOWN OF LEGACY PACKAGES IMPORTS (core, audio, stt, translation, tts, vad) ===")
legacy_pkgs = {'core', 'audio', 'stt', 'translation', 'tts', 'vad'}
for pkg in sorted(legacy_pkgs):
    print(f"\n--- Imports from legacy package '{pkg}' ({len(imports_by_root[pkg])} total) ---")
    for file_path, line, stmt in imports_by_root[pkg]:
        print(f"  {file_path}:{line} -> {stmt}")

print("\n=== BREAKDOWN OF MODERN PACKAGES IMPORTS (app, services, ui, config, utils) ===")
modern_pkgs = {'app', 'services', 'ui', 'config', 'utils'}
for pkg in sorted(modern_pkgs):
    print(f"\n--- Imports from modern package '{pkg}' ({len(imports_by_root[pkg])} total) ---")
    for file_path, line, stmt in imports_by_root[pkg]:
        print(f"  {file_path}:{line} -> {stmt}")
