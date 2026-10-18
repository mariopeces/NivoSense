import numpy as np

PARAMETER_RANGES = {
    "lapse_k_per_km": (4.5, 8.0),
    "precipitation_gradient_per_100m": (0.0, 0.10),
    "precipitation_scale": (0.7, 1.6),
    "rain_snow_threshold": (0.0, 2.5),
    "melt_factor": (1.0, 3.5),
    "radiation_factor": (0.0, 0.012),
}


def sample_members(count: int, seed: int) -> list[dict]:
    """Latin hypercube sample of the parameter ranges."""
    generator = np.random.default_rng(seed)
    columns = {}
    for name, (low, high) in PARAMETER_RANGES.items():
        strata = (generator.permutation(count) + generator.random(count)) / count
        columns[name] = low + strata * (high - low)
    return [{name: float(values[index]) for name, values in columns.items()} for index in range(count)]


def effective_size(weights: np.ndarray) -> float:
    return float(1.0 / np.sum(weights**2))


def tempered_weights(cost: np.ndarray, target_size: float) -> np.ndarray:
    """Weights proportional to exp(-lambda * cost), with lambda set to reach the target effective size."""
    shifted = cost - cost.min()
    target = min(target_size, len(cost))

    def weights(strength: float) -> np.ndarray:
        raw = np.exp(-strength * shifted)
        return raw / raw.sum()

    if effective_size(weights(0.0)) <= target:
        return weights(0.0)
    low, high = 0.0, 1.0
    while effective_size(weights(high)) > target and high < 1e9:
        low, high = high, high * 2
    for _ in range(60):
        middle = (low + high) / 2
        if effective_size(weights(middle)) > target:
            low = middle
        else:
            high = middle
    return weights(high)


def weighted_quantiles(values: np.ndarray, weights: np.ndarray, quantiles) -> np.ndarray:
    """Weighted quantiles along the first axis of `values`; weights must sum to one."""
    order = np.argsort(values, axis=0)
    sorted_values = np.take_along_axis(values, order, axis=0)
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights, axis=0) - 0.5 * sorted_weights
    result = np.empty((len(quantiles),) + values.shape[1:], dtype="float32")
    flat_values = sorted_values.reshape(values.shape[0], -1)
    flat_cumulative = cumulative.reshape(values.shape[0], -1)
    flat_result = result.reshape(len(quantiles), -1)
    for column in range(flat_values.shape[1]):
        flat_result[:, column] = np.interp(quantiles, flat_cumulative[:, column], flat_values[:, column])
    return result
