"""
Train the 1-week NDSI forecast LightGBM model.

Input:  ml/data/pairs_1week.parquet  (from pair_builder.py)
Output: ml/models/lgbm_1week.txt

Temporal split to avoid data leakage:
  Train : all pairs where T < cutoff year
  Val   : all pairs where T == cutoff year
  Test  : all pairs where T > cutoff year

Default split: train 2018-2022 / val 2023 / test 2024
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score

DATA_PATH  = Path(__file__).parent / "data" / "pairs_1week.parquet"
MODEL_PATH = Path(__file__).parent / "models" / "lgbm_1week.txt"

FEATURES = ["ndsi_t", "ndsi_t_prev", "elevation", "slope", "aspect", "month", "doy"]
TARGET   = "ndsi_target"

VAL_YEAR  = 2020   # change to 2023 once all years are extracted
TEST_YEAR = 2020   # change to 2024 once all years are extracted
SINGLE_YEAR_MODE = False  # set True when training on one year only

LGBM_PARAMS = {
    "objective":        "regression",
    "metric":           "mae",
    "learning_rate":    0.05,
    "num_leaves":       63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq":     5,
    "lambda_l1":        0.1,
    "lambda_l2":        0.1,
    "verbose":          -1,
    "n_jobs":           -1,
}


def train() -> lgb.Booster:
    print("Loading dataset...")
    df = pd.read_parquet(DATA_PATH)
    print(f"  {len(df):,} rows, {df['month'].nunique()} months\n")

    # Temporal split — uses year column to prevent data leakage
    if SINGLE_YEAR_MODE or df["year"].nunique() == 1:
        # Single year: 70/15/15 random split (pipeline test only)
        n = len(df)
        train_df = df.iloc[:int(n * 0.70)]
        val_df   = df.iloc[int(n * 0.70):int(n * 0.85)]
        test_df  = df.iloc[int(n * 0.85):]
        print("  ⚠ Single-year mode: random split (not for production use)\n")
    else:
        train_df = df[df["year"] < VAL_YEAR]
        val_df   = df[df["year"] == VAL_YEAR]
        test_df  = df[df["year"] >= TEST_YEAR]

    X_train, y_train = train_df[FEATURES], train_df[TARGET]
    X_val,   y_val   = val_df[FEATURES],   val_df[TARGET]
    X_test,  y_test  = test_df[FEATURES],  test_df[TARGET]

    print(f"Train: {len(train_df):,}  Val: {len(val_df):,}  Test: {len(test_df):,}\n")

    dtrain = lgb.Dataset(X_train, label=y_train)
    dval   = lgb.Dataset(X_val,   label=y_val, reference=dtrain)

    print("Training...")
    model = lgb.train(
        LGBM_PARAMS,
        dtrain,
        num_boost_round=1000,
        valid_sets=[dtrain, dval],
        valid_names=["train", "val"],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=True),
            lgb.log_evaluation(period=50),
        ],
    )

    # Evaluation
    print("\n── Results ──")
    for name, X, y in [("Val", X_val, y_val), ("Test", X_test, y_test)]:
        preds = model.predict(X)
        mae = mean_absolute_error(y, preds)
        r2  = r2_score(y, preds)
        print(f"  {name}: MAE={mae:.4f}  R²={r2:.4f}")

    # Feature importance
    print("\n── Feature importance ──")
    imp = pd.Series(model.feature_importance("gain"), index=FEATURES).sort_values(ascending=False)
    for feat, val in imp.items():
        print(f"  {feat:<15} {val:>10.0f}")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_PATH))
    print(f"\nModel saved to {MODEL_PATH}")

    return model


if __name__ == "__main__":
    train()
