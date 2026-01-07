import re

file_path = r".venv\Lib\site-packages\havsfunc.py"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix get_core
content = content.replace("vs.get_core()", "vs.core")

# 2. Fix _global arguments in Analyse calls
# Look for _global=... and remove it
# Regex to match ", _global=True" or ", _global=False" or ", _global=whatever"
# We handle optional whitespace around comma and equals
content = re.sub(r',\s*_global\s*=\s*[a-zA-Z0-9_]+', '', content)

# 3. Fix _lambda arguments (just in case, saw it in earlier error log)
content = re.sub(r',\s*_lambda\s*=\s*[a-zA-Z0-9_]+', '', content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patched havsfunc.py")
