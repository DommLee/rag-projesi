from app.utils.text import repair_mojibake, normalize_visible_text
samples = [
    'itibarÄ±yla',
    'iÃ§in',
    'gÃ¶rÃ¼nÃ¼m',
    'KanÄ±t',
]
for s in samples:
    print(s, '=>', repair_mojibake(s), '=>', normalize_visible_text(s))
