import re
import os

files = [
    r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage08_volatility.py",
    r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage10_support_resistance.py",
    r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage12_confidence.py",
    r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage13_signal_output.py",
]

pattern = re.compile(r'f["\'].*?\{([a-zA-Z0-9_\[\]\'\"]+)\s*:[^}]+\}.*?["\']')
# Actually, just finding lines with f"..." that contain a format specifier :.[0-9]f
pattern2 = re.compile(r'f["\'].*?\{.*?:.*?\}.*?["\']')

for file in files:
    print(f"\n--- {os.path.basename(file)} ---")
    with open(file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            if pattern2.search(line):
                # only print lines with :. or :+ etc for floats
                if 'f' in line and (':.' in line or ':+' in line or ':,' in line):
                    print(f"Line {i+1}: {line.strip()}")
