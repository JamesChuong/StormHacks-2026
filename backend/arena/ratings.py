import trueskill

env = trueskill.TrueSkill(draw_probability=0.0)


def update(agents_in_rank_order):
    """Update mu/sigma in place on Agent rows, best first."""
    groups = [(env.create_rating(a.mu, a.sigma),) for a in agents_in_rank_order]
    rated = env.rate(groups, ranks=list(range(len(groups))))
    for agent, (rating,) in zip(agents_in_rank_order, rated):
        agent.mu, agent.sigma = rating.mu, rating.sigma
        agent.matches_played += 1


def win_probabilities(agents):
    """Rough model win probability per agent from rating means, for display next to odds."""
    import math
    weights = {a.id: math.exp(a.mu / 4) for a in agents}
    total = sum(weights.values()) or 1
    return {aid: round(w / total, 3) for aid, w in weights.items()}
