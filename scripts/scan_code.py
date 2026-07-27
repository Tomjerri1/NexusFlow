import re

async def main(input, nodes, **params):
    file_list = nodes.get("read_code", {}).get("file_list", [])
    leaks = []

    for file_path in file_list:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line_clean = line.strip()


                    if re.search(r"sk-[a-zA-Z0-9]{20,}", line_clean):
                        masked_line = re.sub(r"sk-[a-zA-Z0-9]{20,}", "sk-***", line_clean)
                        leaks.append(f"Файл: `{file_path}`\nРядок: {line_num}\nВміст: `{masked_line}`")


                    elif re.search(r"(?i)(passwd|api_key|token)\s*=\s*['\"].+['\"]", line_clean):
                        parts = line_clean.split("=", 1)
                        masked_line = f'{parts[0]}= "***"'
                        leaks.append(f"Файл: `{file_path}`\nРядок: {line_num}\nВміст: `{masked_line}`")
        except Exception:
            pass

    return {"output": {"is_safe": len(leaks) == 0, "details": leaks}}