import os
import pandas as pd
from docx import Document


async def main(**kwargs):
    # Тепер ми отримуємо ідеально запакований словник від вузла-адаптера
    merged_input = kwargs.get("input", {})

    file_list = merged_input.get("files", [])
    search_term = merged_input.get("term", "Олександр Петренко")

    if not file_list:
        return {"output": "Файлів для аналізу не знайдено."}

    results = []

    for file_path in file_list:
        if not os.path.exists(file_path):
            continue

        file_name = os.path.basename(file_path)
        ext = file_name.lower().split('.')[-1]

        try:
            if ext in ['csv', 'xlsx']:
                if ext == 'csv':
                    # ОНОВЛЕНО: sep=None та engine='python' дозволяють Pandas
                    # автоматично розуміти табуляції, коми або крапки з комою!
                    df = pd.read_csv(file_path, sep=None, engine='python', dtype=str)
                else:
                    df = pd.read_excel(file_path, dtype=str)

                df = df.fillna("")

                for index, row in df.iterrows():
                    row_text = " | ".join([str(val) for val in row.values])

                    if search_term.lower() in row_text.lower():
                        results.append({
                            "Файл": file_name,
                            "Рядок/Абзац": f"Рядок {index + 2}",
                            "Знайдений Вміст": row_text
                        })

            elif ext == 'docx':
                doc = Document(file_path)
                for i, para in enumerate(doc.paragraphs):
                    if search_term.lower() in para.text.lower():
                        results.append({
                            "Файл": file_name,
                            "Рядок/Абзац": f"Абзац {i + 1}",
                            "Знайдений Вміст": para.text.strip()
                        })

        except Exception as e:
            results.append({
                "Файл": file_name,
                "Рядок/Абзац": "ПОМИЛКА ЧИТАННЯ",
                "Знайдений Вміст": str(e)
            })

    if results:
        result_df = pd.DataFrame(results)
        output_path = "data/result.xlsx"
        result_df.to_excel(output_path, index=False)
        return {"output": f"Успіх! Знайдено {len(results)} збігів. Звіт збережено у '{output_path}'"}
    else:
        return {"output": f"Замовлень для '{search_term}' не знайдено."}