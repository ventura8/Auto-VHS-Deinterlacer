import re
import os

file_path = r".venv\Lib\site-packages\havsfunc.py"

if not os.path.exists(file_path):
    print(f"File {file_path} not found. Skipping patch.")
    exit(0)

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix get_core
content = content.replace("vs.get_core()", "vs.core")

# 2. Fix _global arguments in Analyse calls
content = re.sub(r',\s*_global\s*=\s*[a-zA-Z0-9_]+', '', content)

# 3. Fix _lambda arguments
content = re.sub(r',\s*_lambda\s*=\s*[a-zA-Z0-9_]+', '', content)

# 4. Add device support to QTGMC
if "device=0" not in content:
    # Add device parameter to QTGMC, QTGMC_Interpolate, and QTGMC_ApplySourceMatch signatures
    content = content.replace("opencl=False):", "opencl=False, device=0):")
    content = content.replace(", opencl):", ", opencl, device=0):")

    # Pass device parameter to internal calls
    content = content.replace("TFF, opencl)", "TFF, opencl, device)")
    content = content.replace("TFF=TFF, opencl=opencl)", "TFF=TFF, opencl=opencl, device=device)")
    content = content.replace("MatchEnhance, TFF, opencl)", "MatchEnhance, TFF, opencl, device)")

    # Robust Plugin Wrapping for OpenCL
    # We replace the assignments in QTGMC_Interpolate with safer logic
    # Original:
    # myNNEDI3 = core.nnedi3cl.NNEDI3CL
    # myEEDI3 = core.eedi3m.EEDI3CL
    
    q_interp_pattern = r"(def QTGMC_Interpolate\(.*?\):.*?)(myNNEDI3 = core\.nnedi3cl\.NNEDI3CL)(.*?\n\s+)(myEEDI3 = core\.eedi3m\.EEDI3CL)"
    
    def repl_plugins(match):
        header = match.group(1)
        # We use a helper lambda or just safe inline code.
        # Let's use a safe inline code.
        new_nn = "myNNEDI3 = functools.partial(core.nnedi3cl.NNEDI3CL, device=device) if hasattr(core, 'nnedi3cl') and hasattr(core.nnedi3cl, 'NNEDI3CL') else None"
        spacing = match.group(3)
        new_ee = "myEEDI3 = functools.partial(core.eedi3m.EEDI3CL, device=device) if hasattr(core, 'eedi3m') and hasattr(core.eedi3m, 'EEDI3CL') else None"
        return header + new_nn + spacing + new_ee

    content = re.sub(q_interp_pattern, repl_plugins, content, flags=re.DOTALL)

    # Also fix santiag which uses similar opencl logic if present
    content = content.replace("myNNEDI3 = core.nnedi3cl.NNEDI3CL", "myNNEDI3 = functools.partial(core.nnedi3cl.NNEDI3CL, device=device) if hasattr(core, 'nnedi3cl') and hasattr(core.nnedi3cl, 'NNEDI3CL') else None")
    content = content.replace("myEEDI3 = core.eedi3m.EEDI3CL", "myEEDI3 = functools.partial(core.eedi3m.EEDI3CL, device=device) if hasattr(core, 'eedi3m') and hasattr(core.eedi3m, 'EEDI3CL') else None")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patched havsfunc.py with robust device support")
