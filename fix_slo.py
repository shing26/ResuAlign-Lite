with open("benchmarks/latency_benchmark.py") as f:
    content = f.read()

content = content.replace(
    '"current cold (3 calls)": 5.5,',
    '"current cold (4 calls)": 7.0,'
)
content = content.replace(
    '"current cached (2 calls)": 4.0,',
    '"current cached (3 calls)": 5.5,'
)
content = content.replace(
    '"schema retry (4 calls)": 7.0,',
    '"schema retry (5 calls)": 8.5,'
)
content = content.replace(
    '"eval on (4 calls)": 7.0,',
    '"eval on (5 calls)": 8.5,'
)

with open("benchmarks/latency_benchmark.py", "w") as f:
    f.write(content)
print("Updated SLO seconds")
