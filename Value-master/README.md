# 指数百分位估值系统

一个纯前端的可视化网页，用于参考沪深 300 等指数基金的历史估值分位情况。示例页面包含主图区（蓝色阴影 + 分位线）、数值区（当前值、分位、临界值）以及选项区、用户案例和风险提示，帮助投资者直观理解“低估 / 合理 / 高估”区间。

> 所有数据仅供参考；请结合自身风险偏好与专业建议决策。

## 快速开始

1. 直接在浏览器打开 `index.html`。
2. 页面会优先请求本地后端（`/api/indices`、`/api/indices/{id}/history`）获取 Tushare 实时数据（指数 / A 股 / ETF 均支持）；如接口不可用，则自动 fallback 到前端内置的示例数据。
3. 在顶部搜索框输入“沪深300 / NDX / 红利”等关键字选择指数。
4. 切换时间范围（3Y / 5Y / 10Y / 成立以来）和估值指标（PE / PB / PS / PCF / 股息率 / 风险溢价），观察阴影区、分位线与指数走势的联动。

⚠️ 如需真实数据，请务必先启动下文的 Python 后端。

## 功能亮点

- **后端数据接入**：`server.py` 使用 Tushare Pro 的 `index_dailybasic` / `daily_basic` / `daily`（以及 `fina_indicator` 推导 P/CF）拉取估值指标，并暴露成 REST 接口。
- **示例数据兜底**：若后端不可用，`app.js` 会自动加载本地模拟数据，确保 UI 可预览。
- **百分位计算**：前端动态计算 20% / 50% / 80% 分位、中位数、标准差、Z 分数等指标。
- **原生 Canvas 绘图**：无需第三方图表库，自绘估值阴影、分位虚线与指数折线，兼容高分屏。
- **搜索 / 选项联动**：支持模糊搜索指数、切换估值指标和时间范围，主图区与数值区即时刷新。

## Python 后端：Tushare Pro

`server.py` 使用 FastAPI + Tushare Pro（需要有效 token）提供真实数据：指数采用 `index_dailybasic`，股票和 ETF 采用 `daily_basic` + `daily`（并结合 `fina_indicator` 计算市现率）。

1. 准备环境（建议虚拟环境）并安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
2. 启动服务：
   ```bash
   uvicorn server:app --reload --port 8000
   ```
3. 将静态页面通过任意方式（如 `live-server`、`python -m http.server`）提供给浏览器；若静态站与 API 不同源，请配置反向代理或在 `API_BASE_URL` 中写完整地址。

### API 说明

- `GET /api/indices?q=...`  
  返回可搜索的证券清单（指数 / 股票 / ETF）。服务端会聚合 `pro.index_basic`、`pro.stock_basic`、`pro.fund_basic`，并合并内置映射。

- `GET /api/indices/{id}/history?metric=pe&range=10`  
  拉取指定指数的历史估值。`metric` 支持 `pe/pb/ps/pcf/dividend/riskPremium`，`range` 为数字（年）或 `max`。数据会缓存 30 分钟以减少请求。

返回示例：

```json
{
  "meta": { "id": "SH000300", "name": "沪深300", "ticker": "000300.SH" },
  "history": [
    {
      "date": "2023-12-31",
      "indexValue": 3600.5,
      "metrics": {
        "pe": 11.8,
        "pb": 1.35,
        "ps": 1.2,
        "pcf": 8.4,
        "dividend": 2.9,
        "riskPremium": 3.1
      }
    }
  ]
}
```

## 自定义与扩展

- **真实数据替换**：若有内部估值数据，可直接替换 `server.py` 中的 Tushare 调用，保持接口契约不变即可。
- **指数列表扩展**：在 `INDEX_UNIVERSE` 中补充 `id/name/symbol`；或扩展 `/api/indices` 的数据源。
- **样式与文案**：修改 `styles.css` 与 `index.html` 内的文案，即可适配品牌规范或补充更多策略说明。
- **部署**：可将静态页面托管在任意 CDN，将 FastAPI 部署到支持 Python 的服务器，再通过 Nginx/网关统一域名。

## 免责声明

本项目仅展示估值策略与交互方式，不构成任何投资建议。市场有风险，投资需谨慎。
