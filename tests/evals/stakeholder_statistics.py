"""Descriptive counts and conservative one-sided bounds for the stakeholder study."""
from collections import Counter
from math import exp, fsum, lgamma, log, log1p
from statistics import mean


def canonical_findings(findings):
    """Blind judges assign meaning IDs after checking speaker, span, certainty, time and scope."""
    return Counter((finding["meaning"], finding["disposition"]) for finding in findings)


def agreement(left, right):
    left, right = canonical_findings(left), canonical_findings(right)
    denominator = sum(left.values()) + sum(right.values())
    if not denominator:
        return None  # Paired abstentions are graded against source truth separately.
    # Additional copies never earn credit, even when both outputs repeat the claim.
    return 2 * len(left.keys() & right.keys()) / denominator


def counts(findings, key):
    meanings = {finding["meaning"] for finding in findings if finding["supported"]}
    required = {item["id"] for item in key["required"]}
    permissible = {item["id"] for item in key["permissible"]}
    correct = len(meanings & (required | permissible))
    return Counter(proposed=len(findings), correct=correct,
                   required=len(required), recovered=len(meanings & required),
                   negative_proposals=sum(row["durable"] for row in findings) if key["negative"] else 0,
                   negative_false_positives=len(findings) - correct if key["negative"] else 0)


def rates(count):
    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None
    precision = ratio(count["correct"], count["proposed"])
    recall = ratio(count["recovered"], count["required"])
    f1 = 0.0 if count["required"] and not count["proposed"] else None
    if precision is not None and recall is not None:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return dict(counts=dict(count), precision=precision, recall=recall, f1=f1)


def binomial_masses(n, p):
    if p == 0 or p == 1:
        return [float(k == n*p) for k in range(n+1)]
    return [exp(lgamma(n+1) - lgamma(k+1) - lgamma(n-k+1) +
                k * log(p) + (n-k) * log1p(-p)) for k in range(n+1)]


def exact_lower(successes, n, alpha=.05):
    """Clopper-Pearson lower bound; trials are independent original artifacts."""
    if not n or not successes:
        return 0.0
    if n == successes:
        return alpha ** (1/n)
    lo, hi = 0.0, 1.0
    for _ in range(48):
        mid = (lo + hi) / 2
        if fsum(binomial_masses(n, mid)[successes:]) > alpha:
            hi = mid
        else:
            lo = mid
    return lo


def lower_mean(sample_mean, n, alpha=.05):
    """Invert the one-sided Chernoff bound for n independent [0, 1] observations."""
    if not 0 <= sample_mean <= 1 or n < 1 or not 0 < alpha < 1:
        raise ValueError("Invalid bounded sample")
    if sample_mean == 0:
        return 0.0
    if sample_mean == 1:
        return alpha ** (1 / n)
    limit = -log(alpha) / n
    low, high = 0.0, sample_mean
    for _ in range(55):
        p = (low + high) / 2
        divergence = (sample_mean * log(sample_mean / p)
                      + (1 - sample_mean) * (log1p(-sample_mean) - log1p(-p)))
        if divergence > limit:
            low = p
        else:
            high = p
    return low


def bounded_lower(values):
    return lower_mean(mean(values), len(values)) if values else None


def deficit_lower(differences):
    """E[difference] >= -E[max(0, -difference)]. Each original contributes one value."""
    if not differences:
        return None
    nonloss = [1 - max(0, -value) for value in differences]
    return bounded_lower(nonloss) - 1


def ratio_lower(numerator, denominator, n, cap):
    """Bonferroni upper error and lower denominator bounds for a pooled source-truth ratio."""
    if not denominator or not n:
        return None
    total_cap = n * cap
    error_rate = (denominator - numerator) / total_cap
    upper_errors = 1 - lower_mean(1 - error_rate, n, .025)
    lower_denominator = lower_mean(denominator / total_cap, n, .025)
    return max(0, 1 - upper_errors / lower_denominator) if lower_denominator else 0.0


def order_bounds(values, quantile, alpha=.025):
    """Lower and upper order-statistic bounds, each at 1-alpha, including ties."""
    values = sorted(values)
    if not values:
        return None, None
    masses = binomial_masses(len(values), quantile)
    lower = upper = None
    cumulative = 0.0
    for i, value in enumerate(values):
        cumulative += masses[i]
        if cumulative <= alpha:
            lower = value
        if upper is None and cumulative >= 1 - alpha:
            upper = value
    return lower, upper
