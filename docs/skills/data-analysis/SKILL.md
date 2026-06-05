---
name: data-analysis
description: Analyze CSV/JSON data, compute statistics, and generate insights using pandas and the db_query/db_execute SQLite tools
version: "1.0"
trigger_keywords:
  - pandas
  - dataframe
  - csv
  - data analysis
  - statistics
  - aggregate
  - pivot
  - group by
  - analysis
  - dataset
tools_required:
  - run_python
  - db_query
  - db_execute
  - db_list_tables
  - install_package
  - json_query
---

# Data Analysis Skills

Two main approaches: **pandas** for in-memory analysis, and the **SQLite tools** (db_query, db_execute) for persistent structured data.

## Quick Start: Load and Explore Data

```python
# install_package("pandas")
import pandas as pd

# Load data
df = pd.read_csv("data.csv")
# or from JSON:
df = pd.read_json("data.json")
# or from Excel:
df = pd.read_excel("data.xlsx")

# Explore
print(df.shape)          # (rows, cols)
print(df.dtypes)         # Column types
print(df.describe())     # Stats: mean, std, min, max, quartiles
print(df.head(10))       # First 10 rows
print(df.isnull().sum()) # Missing values per column
```

## Filtering and Selecting

```python
# Filter rows
active = df[df["status"] == "active"]
high_value = df[df["revenue"] > 50000]

# Multiple conditions
filtered = df[(df["status"] == "active") & (df["score"] >= 80)]

# Select columns
subset = df[["name", "score", "department"]]

# Sort
sorted_df = df.sort_values("score", ascending=False)
```

## Aggregation and Group By

```python
# Group by and aggregate
summary = df.groupby("department").agg({
    "score": ["mean", "max", "min", "count"],
    "revenue": "sum",
})

# Pivot table
pivot = df.pivot_table(
    values="revenue",
    index="month",
    columns="product",
    aggfunc="sum",
    fill_value=0,
)

# Value counts
df["status"].value_counts()
```

## SQLite for Persistent Analysis

Use the agent's built-in SQLite tools to store and query structured data persistently:

```
# Store analysis results
db_execute(
    "CREATE TABLE IF NOT EXISTS analysis_results (run_date TEXT, metric TEXT, value REAL)",
    db_name="analytics"
)
db_execute(
    "INSERT INTO analysis_results VALUES (date('now'), 'avg_score', ?)",
    params=[float(df["score"].mean())],
    db_name="analytics"
)

# Query later
db_query("SELECT * FROM analysis_results ORDER BY run_date DESC LIMIT 10", db_name="analytics")
```

## Load CSV into SQLite (for large files)

```python
import pandas as pd
import sqlite3

df = pd.read_csv("large_dataset.csv")
conn = sqlite3.connect("analysis.db")
df.to_sql("raw_data", conn, if_exists="replace", index=False)
# Now query with SQL
result = pd.read_sql("SELECT dept, AVG(score) as avg FROM raw_data GROUP BY dept", conn)
```

## Statistical Analysis

```python
import pandas as pd
import numpy as np

# Correlation matrix
corr = df[["revenue", "score", "customers"]].corr()

# Percentiles
p95 = df["response_time"].quantile(0.95)

# Rolling average
df["rolling_7d"] = df["sales"].rolling(window=7).mean()

# Z-score normalization
df["score_normalized"] = (df["score"] - df["score"].mean()) / df["score"].std()
```

## Output Options

```python
# To CSV
df.to_csv("results.csv", index=False)

# To Excel (formatted)
with pd.ExcelWriter("analysis.xlsx", engine="openpyxl") as writer:
    df.to_excel(writer, sheet_name="Raw Data", index=False)
    summary.to_excel(writer, sheet_name="Summary")

# To markdown
print(df.head().to_markdown())

# To dict (for JSON output)
print(df.head().to_dict(orient="records"))
```

## JMESPath for JSON Data

```
# Use the json_query tool for quick JSON data extraction
json_query("data.json", "users[?active].{name: name, score: score}")
json_query("response.json", "results[0].items | [*].id")
```
