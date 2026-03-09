def check_brackets(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            paren = line.count('(') - line.count(')')
            brace = line.count('{') - line.count('}')
            bracket = line.count('[') - line.count(']')
            if paren != 0 or brace != 0 or bracket != 0:
                print(f"Line {i}: p={paren}, b={brace}, s={bracket} | {line.strip()}")

check_brackets('app.py')
