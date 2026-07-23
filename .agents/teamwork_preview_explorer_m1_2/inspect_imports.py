import sys
import os
import glob
import ast
import importlib
import traceback

# Ensure current working directory (project root) is on sys.path
root_dir = os.path.abspath(".")
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

def inspect_all():
    print("=== DEEP IMPORT & SYMBOL INSPECTION ===")
    
    py_files = [
        os.path.relpath(p, root_dir).replace('\\', '/')
        for p in glob.glob("**/*.py", recursive=True)
        if not '.agents' in p and not 'venv' in p and not '__pycache__' in p
    ]

    print(f"Total Python files found: {len(py_files)}")

    # 1. Test __init__.py files
    print("\n--- 1. Inspecting __init__.py files ---")
    init_files = [f for f in py_files if f.endswith('__init__.py')]
    init_info = []

    for init_f in sorted(init_files):
        mod_path = init_f[:-12].replace('/', '.').strip('.') if init_f != '__init__.py' else ''
        if not mod_path:
            continue
        try:
            mod = importlib.import_module(mod_path)
            all_attr = getattr(mod, '__all__', None)
            dir_attrs = [a for a in dir(mod) if not a.startswith('__')]
            print(f"Module: {mod_path:<30} __all__: {str(all_attr):<20} Re-exported symbols: {dir_attrs}")
            if all_attr is not None:
                for item in all_attr:
                    if not hasattr(mod, item):
                        print(f"  [ERROR] __all__ exports '{item}' but '{item}' missing in {mod_path}")
        except Exception as e:
            print(f"  [IMPORT FAIL] {init_f}: {type(e).__name__}: {e}")

    # 2. Check all python files AST imports using utf-8-sig
    print("\n--- 2. Checking all AST import statements in repository ---")
    import_errors = []
    missing_symbols = []
    ast_failures = []

    for py_file in sorted(py_files):
        with open(py_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
            content = f.read()
        try:
            tree = ast.parse(content, filename=py_file)
        except Exception as e:
            err = f"[AST PARSE FAIL] {py_file}: {e}"
            print(err)
            ast_failures.append(err)
            continue

        if py_file.endswith('__init__.py'):
            file_mod_parts = py_file[:-12].split('/')
        else:
            file_mod_parts = py_file[:-3].split('/')
        file_mod_parts = [p for p in file_mod_parts if p]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    try:
                        importlib.import_module(name)
                    except ModuleNotFoundError as e:
                        err = f"[BROKEN MODULE IMPORT] {py_file}:{node.lineno} -> import {name} ({e})"
                        print(err)
                        import_errors.append(err)
                    except Exception as e:
                        err = f"[IMPORT EXECUTION ERROR] {py_file}:{node.lineno} -> import {name} ({type(e).__name__}: {e})"
                        print(err)
                        import_errors.append(err)
                        
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                level = node.level
                
                # Resolve relative imports
                if level > 0:
                    base_parts = file_mod_parts[:-level] if not py_file.endswith('__init__.py') else file_mod_parts[:-(level-1)] if level > 1 else file_mod_parts
                    if mod_name:
                        target_mod = '.'.join(base_parts + mod_name.split('.'))
                    else:
                        target_mod = '.'.join(base_parts)
                else:
                    target_mod = mod_name

                if target_mod:
                    try:
                        mod = importlib.import_module(target_mod)
                        for alias in node.names:
                            item = alias.name
                            if item == '*':
                                continue
                            if not hasattr(mod, item):
                                submod_name = f"{target_mod}.{item}"
                                try:
                                    importlib.import_module(submod_name)
                                except Exception:
                                    err = f"[MISSING SYMBOL] {py_file}:{node.lineno} -> from {target_mod} import {item} ('{item}' not in module '{target_mod}')"
                                    print(err)
                                    missing_symbols.append(err)
                    except ModuleNotFoundError as e:
                        err = f"[BROKEN MODULE IN FROM-IMPORT] {py_file}:{node.lineno} -> from {target_mod} import ... ({e})"
                        print(err)
                        import_errors.append(err)
                    except Exception as e:
                        err = f"[FROM-IMPORT ERROR] {py_file}:{node.lineno} -> from {target_mod} import ... ({type(e).__name__}: {e})"
                        print(err)
                        import_errors.append(err)

    print("\n--- SUMMARY ---")
    print(f"AST Parse Failures: {len(ast_failures)}")
    print(f"Import Errors: {len(import_errors)}")
    print(f"Missing Symbols: {len(missing_symbols)}")

if __name__ == '__main__':
    inspect_all()
