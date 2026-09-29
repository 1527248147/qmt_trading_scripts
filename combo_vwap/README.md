# combo_vwap — 独立 VWAP 调仓执行

从 `../combo_twap` 的当前版本复制。保留原有下单、涨跌停、持仓/成交/挂单对账、断线重启恢复、备选顺延、撤单和收盘集合竞价处理，主要替换每只股票的累计执行进度。

**代码已完成离线验证；没有启动 QMT 交易，也未证明当前账号的原生 VWAP 权限或真实执行效果。两个脚本默认 `VWAP_ENABLE_TRADING = False`。**

## 文件与使用

| 文件 | 用途 |
|---|---|
| `combo_buy_dual_model.py` | 独立、可整份粘贴进 QMT 的买入脚本 |
| `combo_sell_dual_model.py` | 独立、可整份粘贴进 QMT 的卖出脚本 |
| `vwap_schedule.py` | 成交量曲线与 QMT 数据适配的可审计源代码 |
| `probes/vwap_data_probe.py` | QMT 模型内运行的只读历史数据检查，无需绑定账号 |
| `tools/sync_vwap_engine.py` | 将上述调度代码同步内嵌到三个独立脚本；默认只检查，`--write` 才更新 |
| `tools/update_probe_targets.py` | 从买卖脚本读取目标并同步探针股票清单；默认只检查，`--write` 才更新 |
| `tests/run_all.py` | 运行原六套回归及新增 VWAP 单元/集成测试，不连接柜台 |
| `docs/IMPLEMENTATION_AND_RESEARCH.md` | 原生 QMT 调查、公式、研究来源和实现边界 |
| `docs/TWAP_SOURCE_SHA256.json` | 复制时 TWAP 源文件指纹，验证原版没有被改动 |
| `docs/INHERITED_TWAP_NOTES.md` | 原执行框架说明的副本；VWAP 差异以本 README 和实现说明为准 |

买卖脚本内已嵌入完整调度器，**不用给 QMT 配置 Python 模块搜索路径，也不用另装 pandas/xtquant 或启动 miniQMT**。文件名保留 `dual_model`，便于复用原测试；订单标识已改成 `combo_buy_vwap` / `combo_sell_vwap`。

1. 检查买入股票清单、`SLOTS`、`BUY_BUDGET`、`OPEN_DATE`、`ALLOWED_ACCOUNTS`，以及卖出清单、`CLOSE_DATE/CLOSE_UNTIL`。当前值是从 TWAP 复制的模拟配置，**不代表已更新为风格中性模型的最新交易计划**。
2. **分钟线数据**:程序需要各股票最近约 20 个有效交易日的 **1 分钟数据**(至少 10 日)。交易脚本默认 `VWAP_AUTO_DOWNLOAD = True`:某只股票第一次加载成交量曲线失败时,会在模型内调用客户端自带的 `download_history_data` 补下载一次再重试,**不需要 miniQMT**(2026-09-29 已在实盘客户端验证:0/62 → 62/62)。每只每次运行只下载一次;客户端没有该函数或下载后仍不足,则该股票 `VWAP BLOCK`,不发单。
3. (推荐,换篮子或久未运行时)先把只读探针 `probes/vwap_data_probe.py` 粘贴到 QMT 模型,周期 1 分钟,无需绑定账号。它会对缺数据的股票下载并复查,输出 `AFTER DOWNLOAD: X ready / N total`,结果同时写入 `logs/probe_vwap_data_<日期>_<时间>.txt`。注意:模拟盘安装目录有两套数据(miniQMT 用 `userdata_mini\datadir`,模型交易用 `datadir`),**只有在模型内下载才会落到交易脚本读取的那一套**。
4. 把相应买卖脚本完整粘贴到 QMT。核对日期/账号/目标和探针结果后，将该脚本的 `VWAP_ENABLE_TRADING` 改成 `True`，再在模拟账户验证。相同账号、相同母单不要同时启动 TWAP 与 VWAP；二者独立记录，并不互相分配目标额度。
5. `price_mode.txt` 使用新目录自己的文件，默认 `QUEUE`。日志、成交、基线及价格模式回退路径均与 TWAP 分开；不从 TWAP 导入盘中成交恢复状态。**不支持一张已开始执行的母单在日内直接从 TWAP 切到此版本。**

## 算法实际行为

- 默认窗口仍是 **09:30–14:00**；这是“窗口 VWAP”。14:00 后沿用原收尾，卖出 14:54 撤单、14:57 起竞价。没有把原完成时限悄悄改成全天。
- 每只股票分别计算历史曲线。逐日先除以该日窗口总量，再对最近 20 日等权平均，因此异常巨量日不会仅凭成交量大就主导曲线。
- 盘中每 5 个交易分钟，用当天已完成分钟量修正剩余量预测；取 K 线时间与北京时间较早者，且动态数据至少滞后一整分钟，不使用尚未完成的 bar 或事后全天总量。
- 动态修正加入历史先验、成交量倍率边界和偏离静态曲线的上限。目标进度单调，重启可由当日已知数据前缀重建；已成交/挂单仍由原对账逻辑扣除。
- 历史不足、过旧或严重缺失：该股票输出 `VWAP BLOCK`，**包括 RUSH、补零头和竞价都不发新单**。每 5 分钟允许重试，补齐历史后可恢复。正常撤单和其他股票不受此数据门槛替代。
- 历史曲线有效但当日数据不完整：输出 `STATIC_NO_INTRADAY`，继续静态 VWAP；不是 TWAP。遇到当日数据错误也会给出静态状态。
- 原成交量上限保留：常规单不超过参考分钟量的 10%，卖出 RUSH 为 30%。这是上一根参考分钟的切片上限，**并不保证最终成交恰占当前分钟市场量的 10%**。
- QUEUE/COMPETE 仍单独决定挂单方式。VWAP 调度不保证排队立即成交，也不保证最终成交均价等于市场 VWAP。

窗口可以通过 `BUY_START/BUY_END` 或 `SELL_START/SELL_END` 调整。调度器支持 09:30–14:54 内的连续交易窗口，并正确跳过午休；原收尾约束意味着应为撤单与补单保留时间。若延长到 14:45，应同步改探针窗口、验证原收尾行为，并以同窗口 benchmark 比较。

## 手续费与切片

用户确认佣金 **万 0.8，无最低 5 元**。本算法不新增最低佣金、固定单笔手续费或手续费阈值。

买入 `MIN_ORDER_AMT = 2000`、卖出 `MIN_SELL_SHARES = 200` 是保留的原切片粒度，**不是佣金要求**。这一版为了单独比较调度方法而保留；若单股预算很小，整手与切片门槛会让 VWAP 实际只能分成几笔，可在单独实验中调整。

## 验证

```powershell
& 'C:\Users\15272\.conda\envs\AI_stock_environment\python.exe' -X utf8 'C:\AI_STOCK\qmt_trading_scripts\combo_vwap\tests\run_all.py'
```

结果保存在 `logs/offline_tests/summary.json` 和逐套日志中。检查包含原六套生命周期回归、非均匀成交量驱动的买卖数量、重启/重复调用、防前视、缺数据、午休、窗口延长、成交量上限、竞价拦截、标识与路径隔离，以及独立脚本 ASCII/Python 3.6 语法兼容性。

原六套测试使用显式的均匀曲线替身来保留原生命周期断言；新增测试使用真实调度器和非均匀行情，不以旧测试通过冒充 VWAP 生效。当前测试是离线模拟，未验证客户端数据授权、实际排队成交或执行成本优于 TWAP。
