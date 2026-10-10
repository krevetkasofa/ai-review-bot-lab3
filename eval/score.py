#!/usr/bin/env python3
"""Считает precision / recall / false positives для ревью бота.

Использование:
    python eval/score.py bot-comment.txt
    python eval/score.py bot-comment.txt --real 5,7 --invented 3 --match 9=P6

bot-comment.txt: текст комментария бота (или просто его JSON). Скрипт сам
находит в нём блок ```json с ключом "comments".

Как считается:
  * замечание бота сопоставляется с заложенной проблемой, если оно относится к тому
    же файлу и в тексте (message + reason) есть имя функции/константы из эталона
    или характерное слово; одна проблема засчитывается один раз, повторы — «дубли»;
  * замечание про «приманку» (корректный код) — ложное срабатывание;
  * замечание, которое не удалось сопоставить, надо проверить вручную: если это
    настоящая проблема, передайте его номер в --real, если выдумка — оставьте как есть
    или передайте в --invented; автосопоставление можно отменить тем же --invented;
    если замечание на самом деле про заложенную проблему, но скрипт его не узнал,
    укажите --match НОМЕР=ID (например 9=P6); замечание про приманку, которое по сути
    является настоящей находкой, можно перевести в «настоящие» через --real.
"""
import argparse
import json
import re
import sys


def load_comments(path):
    text = open(path, encoding="utf-8").read()
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidates.append(text)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("comments"), list):
            return data["comments"]
    sys.exit("Не нашла JSON с ключом comments в файле " + path)


def mentions(comment, item):
    text = (str(comment.get("message", "")) + " " + str(comment.get("reason", ""))).lower()
    has_symbol = any(s.lower() in text for s in item.get("symbols", []))
    has_keyword = any(k.lower() in text for k in item.get("keywords", []))
    return has_symbol, has_keyword


def classify(comment, truth):
    """Возвращает ('planted', id) / ('bait', id) / ('unmatched', None).

    Заложенная проблема засчитывается, если замечание относится к тому же файлу и в нём
    есть И имя функции из эталона, И характерное слово (для проблем без функции, например
    неиспользуемого импорта, достаточно слова). Замечание про функцию-приманку — ложное
    срабатывание. Всё остальное идёт на ручную проверку.
    """
    file_name = str(comment.get("file", ""))
    for item in truth["planted"]:
        if not file_name.endswith(item["file"]):
            continue
        has_symbol, has_keyword = mentions(comment, item)
        if (has_symbol and has_keyword) or (not item.get("symbols") and has_keyword):
            return "planted", item["id"]
    for item in truth["baits"]:
        if file_name.endswith(item["file"]) and mentions(comment, item)[0]:
            return "bait", item["id"]
    return "unmatched", None


def parse_numbers(value):
    return {int(x) for x in value.split(",") if x.strip()} if value else set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("comment_file")
    parser.add_argument("--truth", default="eval/ground-truth.json")
    parser.add_argument("--real", default="", help="номера замечаний (с 1), вручную признанные настоящими")
    parser.add_argument("--invented", default="", help="номера замечаний, вручную признанные выдуманными")
    parser.add_argument("--match", default="",
                        help="ручное сопоставление, например 9=P6,12=P8 (замечание 9 — это заложенная проблема P6)")
    args = parser.parse_args()

    truth = json.load(open(args.truth, encoding="utf-8"))
    comments = load_comments(args.comment_file)
    real, invented = parse_numbers(args.real), parse_numbers(args.invented)
    manual = {}
    for pair in filter(None, args.match.split(",")):
        number, _, item_id = pair.partition("=")
        manual[int(number)] = item_id.strip().upper()

    found, rows = {}, []
    for number, comment in enumerate(comments, 1):
        kind, item_id = classify(comment, truth)
        if number in manual:
            kind, item_id = "planted", manual[number]
        elif number in invented:
            kind, item_id = "invented", None
        elif number in real and kind in ("unmatched", "bait"):
            kind, item_id = "real_extra", None
        label = kind
        if kind == "planted":
            if item_id in found:
                label = "duplicate"
            else:
                found[item_id] = number
        rows.append((number, comment, label, item_id))

    planted_total = len(truth["planted"])
    tp = len(found)
    bait_hits = [r for r in rows if r[2] == "bait"]
    invented_rows = [r for r in rows if r[2] == "invented"]
    unmatched = [r for r in rows if r[2] == "unmatched"]
    extras = [r for r in rows if r[2] == "real_extra"]
    duplicates = [r for r in rows if r[2] == "duplicate"]

    print("№  | вердикт        | эталон | файл | severity | замечание")
    print("---|----------------|--------|------|----------|----------")
    for number, comment, label, item_id in rows:
        message = str(comment.get("message", "")).replace("\n", " ")[:70]
        print(f"{number:<2} | {label:<14} | {item_id or '-':<6} | {comment.get('file', '')} | "
              f"{comment.get('severity', '')} | {message}")

    total = len(rows)
    fp = len(bait_hits) + len(invented_rows) + len(unmatched)
    real_found = tp + len(extras)
    distinct = total - len(duplicates)
    print()
    print(f"Заложено проблем:                {planted_total}")
    print(f"Найдено заложенных (TP):         {tp}")
    print(f"Пропущено (FN):                  {planted_total - tp}")
    print(f"Замечаний бота всего:            {total} (из них дублей: {len(duplicates)})")
    print(f"Ложных срабатываний (FP):        {fp} "
          f"(на приманках: {len(bait_hits)}, выдумки: {len(invented_rows)}, "
          f"не сопоставлено и не подтверждено: {len(unmatched)})")
    print(f"Настоящие, но не заложенные:     {len(extras)}")
    if planted_total:
        print(f"Recall:                          {tp / planted_total:.2f}  ({tp}/{planted_total})")
    if distinct:
        print(f"Precision (строгая):             {tp / distinct:.2f}  ({tp}/{distinct})")
        print(f"Precision (с подтверждёнными):   {real_found / distinct:.2f}  ({real_found}/{distinct})")
    missed = [p for p in truth["planted"] if p["id"] not in found]
    if missed:
        print("\nПропущены:")
        for item in missed:
            print(f"  {item['id']} [{item['category']}] {item['description']}")
    if unmatched:
        print("\nНужна ручная проверка (номера из таблицы), потом перезапустите с --real / --invented:")
        for number, comment, _, _ in unmatched:
            print(f"  {number}: {comment.get('file')} — {str(comment.get('message', ''))[:90]}")


if __name__ == "__main__":
    main()
