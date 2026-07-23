import time
import json
import datetime
from statusline import iso_to_nanos

def run_bench():
    # create fake steps
    steps = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for i in range(100000):
        steps.append({
            "type": "OTHER",
            "source": "OTHER",
            "step_index": i,
            "created_at": now.isoformat(),
            "content": "test"
        })

    start = time.time()
    for i, step in enumerate(steps):
        stype = step.get("type")
        ssource = step.get("source")
        sindex = step.get("step_index")
        scontent = step.get("content", "")
        stime = iso_to_nanos(step.get("created_at"))
    end = time.time()
    print(f"Unoptimized time: {end - start:.4f} seconds")

    start = time.time()
    for i, step in enumerate(steps):
        stype = step.get("type")
        ssource = step.get("source")
        sindex = step.get("step_index")
        scontent = step.get("content", "")
        # stime is calculated only when needed
    end = time.time()
    print(f"Optimized time: {end - start:.4f} seconds")

if __name__ == "__main__":
    run_bench()
