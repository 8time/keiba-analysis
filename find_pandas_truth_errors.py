import ast
import glob
import os

from collections import namedtuple

# Target variable names
TARGET_NAMES = {'odds', 'res_odds', 'popularity', 'rank', 'odds_rank', 'trainer', 'jockey', 'horse_name', 'field_size', 'horse_number', 'df', 'data', 'result', 'series'}

Issue = namedtuple('Issue', ['file', 'line', 'code', 'desc'])

def is_target_node(node):
    if isinstance(node, ast.Name):
        return any(t in node.id.lower() for t in TARGET_NAMES)
    elif isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Name):
            return any(t in node.value.id.lower() for t in TARGET_NAMES)
    return False

def check_file(filepath):
    issues = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.splitlines()
        
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return issues
        
    for node in ast.walk(tree):
        if isinstance(node, ast.If) or isinstance(node, ast.While):
            # Check the test condition
            # If it's a direct variable `if res_odds:`
            if is_target_node(node.test):
                issues.append(Issue(filepath, node.lineno, lines[node.lineno-1].strip(), f"直接判定 (if/while) -> {ast.unparse(node.test)}"))
            # If it's a unary not `if not x:`
            elif isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not):
                if is_target_node(node.test.operand):
                    issues.append(Issue(filepath, node.lineno, lines[node.lineno-1].strip(), f"否定判定 (not) -> {ast.unparse(node.test.operand)}"))
            # If it's a boolean operation `if x and y:`
            elif isinstance(node.test, ast.BoolOp):
                for val in node.test.values:
                    if is_target_node(val):
                        issues.append(Issue(filepath, node.lineno, lines[node.lineno-1].strip(), f"論理演算判定 (and/or) -> {ast.unparse(val)}"))
                        
        elif isinstance(node, ast.IfExp): # Ternary operator `a if x else b`
            if is_target_node(node.test):
                issues.append(Issue(filepath, node.lineno, lines[node.lineno-1].strip(), f"三項演算判定 -> {ast.unparse(node.test)}"))
                
    return issues

def main():
    all_issues = []
    for d in ['core', 'scripts', '.']:
        for filepath in glob.glob(os.path.join(d, '**', '*.py'), recursive=True):
            all_issues.extend(check_file(filepath))
            
    with open('dangerous_patterns.md', 'w', encoding='utf-8') as out:
        out.write("# 危険箇所 (Pandas 直接真偽値評価の疑い)\n\n")
        out.write("| File | Line | Content | Description |\n")
        out.write("| --- | --- | --- | --- |\n")
        for i in all_issues:
            out.write(f"| {os.path.basename(i.file)} | {i.line} | `{i.code}` | {i.desc} |\n")

if __name__ == '__main__':
    main()
