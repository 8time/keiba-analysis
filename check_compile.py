import py_compile
import sys
import traceback

try:
    py_compile.compile('app.py', doraise=True)
    print("Compilation successful")
except py_compile.PyCompileError as e:
    print(f"Compilation failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred: {e}")
    traceback.print_exc()
    sys.exit(1)
