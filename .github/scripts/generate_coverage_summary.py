import sys
import xml.etree.ElementTree as ET
from datetime import datetime


def generate_summary(xml_path):
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"Error parsing {xml_path}: {e}")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Global Stats
    line_rate = float(root.get('line-rate', 0)) * 100
    branch_rate = float(root.get('branch-rate', 0)) * 100

    markdown = "## 📊 Code Coverage Report\n\n"
    markdown += f"**Total Coverage:** {line_rate:.2f}%\n"
    markdown += f"**Branch Coverage:** {branch_rate:.2f}%\n"
    markdown += f"**Generated:** {timestamp}\n\n"

    markdown += "| File | Coverage | Branches | Complexity |\n"
    markdown += "| :--- | :---: | :---: | :---: |\n"

    # File Stats
    # Cobertura format: packages -> classes -> class
    for package in root.findall('.//package'):
        for cls in package.findall('.//class'):
            filename = cls.get('filename')
            # simplify path to just basename or relative
            filename = filename.replace('\\', '/')
            if '/' in filename:
                filename = filename.split('/')[-1]

            c_line_rate = float(cls.get('line-rate', 0)) * 100
            c_branch_rate = float(cls.get('branch-rate', 0)) * 100
            complexity = cls.get('complexity', 'N/A')

            markdown += f"| {filename} | {c_line_rate:.1f}% | {c_branch_rate:.1f}% | {complexity} |\n"

    print(markdown)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate_summary(sys.argv[1])
    else:
        print("Usage: python generate_coverage_summary.py coverage.xml")
