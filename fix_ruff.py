import re
with open("tests/test_graph_executor.py") as f:
    c = f.read()
c = c.replace('if node.get("role") == "profiler": st.jd_profile = {}', 'if node.get("role") == "profiler":\n                st.jd_profile = {}')
c = c.replace('elif node.get("role") == "gap_analyzer": st.gap_report = {}', 'elif node.get("role") == "gap_analyzer":\n                st.gap_report = {}')
c = c.replace('elif node.get("role") == "editor": st.tailored_draft = {"diffs": [{"proposed": "Python"}]}', 'elif node.get("role") == "editor":\n                st.tailored_draft = {"diffs": [{"proposed": "Python"}]}')
c = c.replace('if node.get("role") == "profiler": raise ValueError("fail")', 'if node.get("role") == "profiler":\n                raise ValueError("fail")')
with open("tests/test_graph_executor.py", "w") as f:
    f.write(c)
print("Fixed")
