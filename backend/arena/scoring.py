POINTS = [10, 7, 5, 3, 1]


def score_challenge(results):
    """results: [{agent, pass_rate, solve_time, tokens}] -> {agent: points}.

    Full passers rank by solve time, partial passers below them by pass rate;
    points are multiplied by pass rate so partial never beats full.
    """
    ranked = sorted(results, key=lambda r: (
        -r["pass_rate"],
        r["solve_time"] if r["pass_rate"] == 1 and r["solve_time"] is not None else float("inf"),
        r["tokens"],
    ))
    return {r["agent"]: round((POINTS[i] if i < len(POINTS) else 0) * r["pass_rate"], 2)
            for i, r in enumerate(ranked)}
