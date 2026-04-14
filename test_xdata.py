import codecs
import re
text = codecs.open('original_index.html', 'r', 'utf16').read()
matches = re.findall(r'x-data=[\'\"].*?[\'\"]', text)
print("x-data matches:")
for m in matches:
    print(m)
