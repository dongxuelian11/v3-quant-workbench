# Track J A-share Backtest Core — Official Rule Sources

Source cut-off: 2026-08-11. The engine performs no online lookup. Each run receives a pinned rule profile and exact data/calendar/corporate-action references.

## Trading rules

- [Shanghai Stock Exchange Trading Rules (2026 revision), 上证发〔2026〕41号](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml), published 2026-04-24 and effective 2026-07-06. The rules establish the default no-resale-before-settlement constraint and the current trading framework. The 2026 revision changed main-board risk-warning share price limits from 5% to 10%.
- [Shenzhen Stock Exchange Trading Rules (2026 revision), 深证上〔2026〕551号](https://www.szse.cn/lawrules/rule/trade/current/t20260424_620190.html) and its [official PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf), effective 2026-07-06. Clause 3.3.8 specifies 100-share buy lots and one-time disposal of an odd-lot remainder. Clauses 3.3.13–3.3.14 specify main-board 10%, ChiNext 20%, the previous-close limit formula, tick rounding, and enumerated no-limit sessions.
- [Shenzhen risk-warning implementation guide (2026 revision)](https://www.szse.cn/lawrules/rule/stock/supervision/delist/t20260424_620191.html), effective 2026-07-06.
- [Beijing Stock Exchange Trading Rules (2026 revision), 北证公告〔2026〕17号](https://www.bse.cn/jygl_list/200028217.html), effective 2026-07-06. BSE shares use a 30% daily limit under the ordinary regime, a 100-share minimum buy with one-share increments, and enumerated no-limit sessions such as the first listing day.

## Settlement and statutory charges

- [China Securities Depository and Clearing Corporation Shanghai market fee table](https://www.chinaclear.cn/zdjs/editor_file/20250516162952358.pdf), current table inspected 2026-08-11: A-share transfer fee 0.01 per mille of consideration on both sides.
- [China Securities Depository and Clearing Corporation Beijing market fee table](https://www.chinaclear.cn/zdjs/editor_file/20250630165507248.pdf), current table inspected 2026-08-11: A-share transfer fee 0.01 per mille on both sides.
- [ChinaClear Shenzhen settlement guide](https://www.chinaclear.cn/zdjs/editor_file/20240920171102334.pdf): A-share securities/funds settlement uses T+1.
- [State Tax Administration / Ministry of Finance announcement 2023 No. 39](https://fgk.chinatax.gov.cn/zcfgk/c102416/c5211343/content.html), effective 2023-08-28: securities transaction stamp duty was halved. Combined with the seller-only regime, the current modeled statutory rate is 0.5 per mille on sells.
- [SSE transaction fee notice, 上证发〔2023〕137号](https://www.sse.com.cn/lawandrules/sselawsrules/charge/c/c_20230818_5725598.shtml), effective 2023-08-28: A-share transaction handling fee 0.0341 per mille on both sides. BSE publishes a distinct rate; profiles must therefore remain market/version specific.

## Encoding policy

These sources do not justify hidden ticker inference or a timeless global default. V0 therefore requires:

- an explicit board classification per instrument;
- explicit daily tradability, suspension, restriction/ST and limit-state data;
- profile effective dates and a content hash;
- broker commission and minimum commission as caller-supplied contractual values, separate from statutory tax/transfer/exchange fees;
- raw, unadjusted matching and valuation prices, with corporate actions supplied separately;
- typed fail-closed evidence for unsupported corporate actions or missing valuation prices.

The bundled `CN_A_SHARE_2026_07_06_V1` reference profile is a reproducible research fixture, not a claim that one immutable rule applies to every security and every historical date.
