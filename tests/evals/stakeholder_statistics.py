"""Descriptive counts and conservative one-sided bounds for the stakeholder study."""
from collections import Counter
from math import exp, fsum, lgamma, log, log1p, sqrt
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


def bounded_lower(values, width=1, alpha=.05):
    """One-sided Hoeffding bound on independent artifact-level means (paired differences span 2)."""
    return mean(values) - width * sqrt(log(1/alpha) / (2 * len(values))) if values else None


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
