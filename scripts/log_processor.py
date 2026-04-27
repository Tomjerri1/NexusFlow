# scripts/log_processor.py
async def count_errors(input, nodes, **params):
    # Беремо текст із порту 'input'
    log_content = input.get("input", "")
    error_count = len([line for line in log_content.split('\n') if "ERROR" in line.upper()])

    # ПОВЕРТАЄМО В КЛЮЧ 'output'
    return {"output": {"count": error_count}}