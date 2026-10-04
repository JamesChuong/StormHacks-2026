"""Judge a submission: examples give feedback, hidden tests give the score."""
from . import sandbox


def evaluate(code, challenge):
    examples = sandbox.run_tests(code, challenge["examples"], challenge)
    hidden = sandbox.run_tests(code, challenge["hidden_tests"], challenge)
    passed = sum(t["passed"] for t in hidden)
    total = len(hidden)

    feedback = ""
    for ex, res in zip(challenge["examples"], examples):
        if not res["passed"]:
            feedback = (f"Example input:\n{ex['input']}\nExpected output:\n{ex['output']}\n"
                        f"Your output:\n{res['stdout'][:500]}\n"
                        + (f"Error:\n{res['stderr']}\n" if res["stderr"] else ""))
            break
    else:
        if passed < total:
            feedback = (f"Your solution passes the examples but fails {total - passed} of {total} "
                        "hidden tests (wrong answer, runtime error, or timeout). "
                        "Consider edge cases and efficiency.")

    return {
        "passed": passed,
        "total": total,
        "pass_rate": passed / total if total else 0.0,
        "examples_passed": sum(t["passed"] for t in examples),
        "examples_total": len(examples),
        "timeouts": sum(t["timed_out"] for t in hidden),
        "feedback": feedback,
    }
