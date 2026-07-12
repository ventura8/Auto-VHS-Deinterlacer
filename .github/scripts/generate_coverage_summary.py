"""Generate a markdown coverage summary from a Cobertura XML report."""

import sys
import xml.etree.ElementTree as ET
from datetime import datetime


def generate_summary(xml_path):
    """Print a markdown summary for the given Cobertura XML file."""

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Global Stats
        line_rate = float(root.get("line-rate", 0)) * 100
        branch_rate = float(root.get("branch-rate", 0)) * 100
    except (ET.ParseError, OSError, ValueError) as error:
        print(f"Error parsing {xml_path}: {error}")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    markdown = "## 📊 Code Coverage Report\n\n"
    markdown += f"**Total Coverage:** {line_rate:.2f}%\n"
    markdown += f"**Branch Coverage:** {branch_rate:.2f}%\n"
    markdown += f"**Generated:** {timestamp}\n\n"

    markdown += "| File | Coverage | Branches | Complexity |\n"
    markdown += "| :--- | :---: | :---: | :---: |\n"

    # File Stats
    # Cobertura format: packages -> classes -> class
    for package in root.findall(".//package"):
        for cls in package.findall(".//class"):
            try:
                filename = cls.get("filename")
                line_rate_raw = cls.get("line-rate")
                branch_rate_raw = cls.get("branch-rate")

                if not filename or line_rate_raw is None or branch_rate_raw is None:
                    raise ValueError("missing required class attributes")

                # simplify path to just basename or relative
                filename = filename.replace("\\", "/")
                if "/" in filename:
                    filename = filename.split("/")[-1]

                c_line_rate = float(line_rate_raw) * 100
                c_branch_rate = float(branch_rate_raw) * 100
                complexity = cls.get("complexity", "N/A")
            except (AttributeError, TypeError, ValueError) as error:
                print(f"Skipping malformed class entry: {error}")
                continue

            markdown += f"| {filename} | {c_line_rate:.1f}% | {c_branch_rate:.1f}% | {complexity} |\n"

    print(markdown)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate_summary(sys.argv[1])
    else:
        print("Usage: python generate_coverage_summary.py coverage.xml")
