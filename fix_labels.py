with open("benchmarks/latency_benchmark.py") as f:
    content = f.read()

content = content.replace(
    '"current cold (3 calls)"',
    '"current cold (4 calls)"'
)
content = content.replace(
    '"current cached (2 calls)"',
    '"current cached (3 calls)"'
)
content = content.replace(
    '"schema retry (4 calls)"',
    '"schema retry (5 calls)"'
)
content = content.replace(
    '"eval on (4 calls)"',
    '"eval on (5 calls)"'
)

with open("benchmarks/latency_benchmark.py", "w") as f:
    f.write(content)
print("Updated labels")
