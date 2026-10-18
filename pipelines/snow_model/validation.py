import numpy as np

MIN_VALID_FRACTION = 0.5
SNOW_FRACTION_THRESHOLD = 0.5


def observed_snow(snow_fraction: np.ndarray, valid_fraction: np.ndarray):
    """Binary snow state and usability of each model cell from the 10 m observation."""
    usable = valid_fraction >= MIN_VALID_FRACTION
    return snow_fraction >= SNOW_FRACTION_THRESHOLD, usable


def misclassification(simulated: np.ndarray, observed: np.ndarray, usable: np.ndarray) -> float:
    count = int(usable.sum())
    if count == 0:
        return 0.0
    return float(((simulated != observed) & usable).sum() / count)


def confusion_metrics(probability: np.ndarray, observed: np.ndarray, usable: np.ndarray) -> dict:
    """Pooled skill of a snow probability field against observed snow on usable cells."""
    predicted = probability >= 0.5
    truth = observed[usable]
    guess = predicted[usable]
    tp = float(np.sum(guess & truth))
    fp = float(np.sum(guess & ~truth))
    fn = float(np.sum(~guess & truth))
    tn = float(np.sum(~guess & ~truth))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    denominator = np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = (tp * tn - fp * fn) / denominator if denominator else 0.0
    brier = float(np.mean((probability[usable] - truth.astype("float32")) ** 2)) if truth.size else 0.0
    return {
        "cells": int(truth.size),
        "snow_cells": int(truth.sum()),
        "f1": round(f1, 4),
        "mcc": round(float(mcc), 4),
        "brier": round(brier, 4),
        "accuracy": round((tp + tn) / max(tp + fp + fn + tn, 1.0), 4),
    }


def split_fit_test(count: int) -> tuple[list[int], list[int]]:
    """Every third observation date is held out for testing."""
    test = [index for index in range(count) if index % 3 == 2]
    fit = [index for index in range(count) if index % 3 != 2]
    return fit, test


def gate(test_metrics: dict, prior_metrics: dict, snow_dates: int, settings: dict) -> dict:
    reasons = []
    if snow_dates < settings["min_test_dates_with_snow"]:
        reasons.append(
            f"only {snow_dates} held-out dates show snow, {settings['min_test_dates_with_snow']} required"
        )
    if test_metrics["f1"] < settings["min_f1"]:
        reasons.append(f"held-out F1 {test_metrics['f1']} is below {settings['min_f1']}")
    if test_metrics["f1"] < prior_metrics["f1"]:
        reasons.append("the weighted ensemble is not better than the unweighted one on held-out dates")
    return {"passed": not reasons, "reasons": reasons}
