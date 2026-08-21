# 配置说明

该目录用于存放指数与数据源的映射配置。`indices.yaml` 会在后续步骤中被 Python 脚本读取，用于决定不同市场指数的估值与行情拉取方式。

- `name`：指数中文名。
- `code`：官方指数代码。
- `class`：市场分类（如 `CN_CSI`、`HK_HSI`、`US_INDEX`）。
- `price_symbol`：行情接口使用的符号。
- `pe_source` / `dp_source` / `pb_source`：估值数据来源标识。
- `etf_proxies`：可选，列出可替代的 ETF 标的，用于补充行情或股息率。

后续步骤会由自动化脚本解析这些配置并生成 `docs/assets.csv`。
