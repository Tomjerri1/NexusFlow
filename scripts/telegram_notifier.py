import requests

async def main(input, nodes, **params):
    BOT_TOKEN = "8638672730:AAHMMuFLneh8yhl1o_E9vQO1hrqOlxUpkqQ"
    CHAT_ID = "7953482451"

    if "log_safe" in nodes:
        message = params.get("msg_safe", "Безпечно.")
        all_leaks = []
    else:
        message = params.get("msg_danger", "Тривога.")
        env_leaks = nodes.get("scan_env", {}).get("output", {}).get("details", []) or []
        code_leaks = nodes.get("scan_code", {}).get("output", {}).get("details", []) or []
        all_leaks = env_leaks + code_leaks

    telegram_text = f"*NexusFlow Security Notification*\n\n{message}"

    if all_leaks:
        telegram_text += "\n\n*Деталі знайдених вразливостей:*\n"
        for leak in all_leaks:
            telegram_text += f"\n{leak}\n" + "—" * 15

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": telegram_text,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("TELEGRAM SENT SUCCESSFULLY")
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "details": str(e)}