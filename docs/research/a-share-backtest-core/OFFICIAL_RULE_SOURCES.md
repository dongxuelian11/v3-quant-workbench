# Track J A-share Backtest Core — Official Rule Sources

Source cut-off: 2026-08-11. The engine performs no online lookup. Each run receives pinned, content-addressed timing/rule/cost profiles and exact data/calendar/corporate-action references.

## Session-open timing

The bundled timing profile is effective from 2026-07-06 and covers SSE, SZSE and BSE daily raw-open research execution.

| Market | Official rule | Opening call auction | V0 eligibility cutoff | Raw-open execution timestamp |
|---|---|---:|---:|---:|
| SSE main/STAR | [SSE Trading Rules (2026 revision), 上证发〔2026〕41号](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml) | 09:15–09:25 | strict `< 09:15` | 09:25 |
| SZSE main/ChiNext | [SZSE Trading Rules (2026 revision), 深证上〔2026〕551号](https://www.szse.cn/lawrules/rule/trade/current/t20260424_620190.html) and [official PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf) | 09:15–09:25 | strict `< 09:15` | 09:25 |
| BSE | [BSE Trading Rules (2026 revision), 北证公告〔2026〕17号](https://www.bse.cn/jygl_list/200028217.html) | 09:15–09:25 | strict `< 09:15` | 09:25 |

The cutoff deliberately precedes opening-price formation. An input at exactly 09:15 or later cannot be assigned the same day's already-forming raw open. A closed calendar session does not consume the input.

## Market-scoped statutory and exchange costs

The bundled cost fixture uses the following rules for ordinary A-share auction transactions from 2023-08-28. Decimal rates are fractions of consideration; fees are charged on both buy and sell unless stated otherwise.

| Board scope | Transfer fee | Exchange handling fee | Effective period | Official evidence |
|---|---:|---:|---|---|
| `SSE_MAIN`, `SSE_STAR` | `0.00001` (0.01‰) | `0.0000341` (0.00341%) | 2023-08-28 onward | [ChinaClear Shanghai fee table](https://www.chinaclear.cn/zdjs/fbzyls/202506/9d22b74d9f2e40edb67b44d1f6596f18/files/%E4%B8%8A%E6%B5%B7%E5%B8%82%E5%9C%BA%E8%AF%81%E5%88%B8%E7%99%BB%E8%AE%B0%E7%BB%93%E7%AE%97%E4%B8%9A%E5%8A%A1%E6%94%B6%E8%B4%B9%E5%8F%8A%E4%BB%A3%E6%94%B6%E7%A8%8E%E8%B4%B9%E4%B8%80%E8%A7%88%E8%A1%A8.pdf); [SSE fee guide, 上证发〔2023〕137号](https://www.sse.com.cn/lawandrules/sselawsrules2025/charge/c/c_20250610_10781461.shtml) |
| `SZSE_MAIN`, `SZSE_CHINEXT` | `0.00001` (0.01‰) | `0.0000341` (0.0341‰) | 2023-08-28 onward | [ChinaClear Shenzhen fee table](https://www.chinaclear.cn/zdjs/fbzyls/202506/ab6384ba25514554a7eceaee3e521032/files/%E6%B7%B1%E5%9C%B3%E5%B8%82%E5%9C%BA%E8%AF%81%E5%88%B8%E7%99%BB%E8%AE%B0%E7%BB%93%E7%AE%97%E4%B8%9A%E5%8A%A1%E6%94%B6%E8%B4%B9%E5%8F%8A%E4%BB%A3%E6%94%B6%E7%A8%8E%E8%B4%B9%E4%B8%80%E8%A7%88%E8%A1%A8.pdf); [SZSE notice, 深证上〔2023〕768号](https://www.szse.cn/disclosure/notice/t20230818_602805.html) |
| `BSE` | `0.00001` (0.01‰) | `0.000125` (0.0125%) | 2023-08-28 onward | [ChinaClear Beijing fee table](https://www.chinaclear.cn/zdjs/fbzyls/202506/69144099e23c436ab678b9d778260402/files/%E5%8C%97%E4%BA%AC%E5%B8%82%E5%9C%BA%E8%AF%81%E5%88%B8%E7%99%BB%E8%AE%B0%E7%BB%93%E7%AE%97%E4%B8%9A%E5%8A%A1%E6%94%B6%E8%B4%B9%E5%8F%8A%E4%BB%A3%E6%94%B6%E7%A8%8E%E8%B4%B9%E4%B8%80%E8%A7%88%E8%A1%A8.pdf); [CSRC notice for the SSE/SZSE/BSE reductions](https://www.csrc.gov.cn/csrc/c100028/c7426794/content.shtml), corresponding to 北证公告〔2023〕54号 |

- [State Tax Administration / Ministry of Finance Announcement 2023 No. 39](https://fgk.chinatax.gov.cn/zcfgk/c102416/c5211343/content.html) halves securities transaction stamp duty from 2023-08-28. Together with the [Ministry of Finance seller-only regime from 2008-09-19](https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/200809/t20080919_76432.htm), V0 models `0.0005` on sells and zero on buys for this effective period.
- Broker commission and minimum commission are caller-supplied contractual values, not claimed as a universal official rate.
- Historical execution outside these effective periods requires another explicit official rule. Missing or overlapping `(board, session_date)` coverage fails closed; the engine never substitutes a neighboring market's rate.

## Encoding policy and boundary

These sources do not justify hidden ticker inference or a timeless global default. V0 therefore requires:

- an explicit board classification per instrument;
- explicit daily tradability, suspension, restriction/ST and limit-state data;
- execution-timing, board-rule and market-cost effective dates with content hashes;
- broker commission and minimum commission as caller-supplied contractual values, separate from statutory tax/transfer/exchange fees;
- raw, unadjusted matching and valuation prices, with corporate actions supplied separately;
- typed fail-closed evidence for expired W0 vectors, missing/overlapping cost coverage, unsupported corporate actions or missing valuation prices.

The bundled profiles are reproducible research fixtures, not timeless defaults and not authority for live or broker execution.
