import re


async def main(input, nodes, **params):
    file_list = nodes.get("read_env", {}).get("file_list", [])
    leaks = []

    for file_path in file_list:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line_clean = line.strip()
                    if line_clean.startswith("#"):
                        continue

                    # Якщо знайдено пароль/токен
                    if re.search(r"(?i)(password|secret|token|api_key)\s*=", line_clean):
                        # Розбиваємо по знаку "=" і замінюємо праву частину на "***"
                        parts = line_clean.split("=", 1)
                        masked_line = f'{parts[0]}= "***"'

                        leaks.append(f"Файл: `{file_path}`\nРядок: {line_num}\nВміст: `{masked_line}`")
        except Exception:
            pass

    return {"output": {"is_safe": len(leaks) == 0, "details": leaks}}