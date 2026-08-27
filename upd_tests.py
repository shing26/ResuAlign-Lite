import sys
sys.stdout.reconfigure(encoding="utf-8")
with open("tests/frontend/format.test.mjs", encoding="utf-8") as f:
    c = f.read()
c = c.replace("来自对齐评估", "来自 AI 评估")
c = c.replace("来自差距分析", "来自能力分析")
with open("tests/frontend/format.test.mjs", "w", encoding="utf-8") as f:
    f.write(c)
print("format.test.mjs done")
with open("tests/frontend/split-canvas.test.mjs", encoding="utf-8") as f:
    c = f.read()
c = c.replace("来源已验证", "🛡️ 高可信")
c = c.replace("匹配度 · 来自对齐评估", "匹配度 · 来自 AI 评估")
with open("tests/frontend/split-canvas.test.mjs", "w", encoding="utf-8") as f:
    f.write(c)
print("split-canvas.test.mjs done")
