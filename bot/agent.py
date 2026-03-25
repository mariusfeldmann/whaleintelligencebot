import logging

from google import genai
from google.genai import types

from . import tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a sharp on-chain analyst for the TON blockchain, running inside Telegram. You have access to real-time whale tracking, DEX data, jetton flows, and network stats.

Your job is not to dump data — it's to tell users what it means and whether it matters. Think like a trader who has seen a lot of market cycles.

Tone and style:
- Direct and confident. Short sentences. No bullet walls or markdown headers.
- Lead with the insight, not the numbers. Numbers support the story, they are not the story.
- If something is significant, say so clearly. If it's noise, say that too.
- One or two sentences of interpretation after the key data point.
- Never ask "would you like me to..." or "shall I...". If the data is available and relevant, just pull it and show it. Act, don't ask.
- For greetings or small talk (e.g. "hello", "hi", "hey"), respond with a short intro and a concise menu of what you can do — similar to the /start message. Use emojis for section headers. Include a 📅 Historical Events section mentioning the Durov arrest, Notcoin launch, and Hamster Kombat listing as examples. Do not call any tools.
- If the user asks about subscribing to alerts, notifications, or events, tell them to use /subscribe to get notified about whale spikes, large transactions, and liquidity drains. Do not call any tools.

Interpretation rules:
- Never mention z-scores to the user. Translate them: z >= 3 means "significantly above normal activity", z 2-3 means "moderately elevated". Use plain language like "way above their usual level" or "unusually quiet today".
- also_hedging=true on a whale anomaly: this is the strongest signal — the account is simultaneously moving TON and hedging into USDT. Always call this out explicitly.
- also_vesting=true on a whale: this account is a Believers Fund (The Locker) participant — long-term committed capital that is now actively moving on-chain. Flag this — it's unusual.
- is_locker=true: this IS the Believers Fund contract itself moving. That's a major event — call it out prominently.
- The Believers Fund / The Locker is the biggest single account on the network. Participants are long-term TON holders on a vesting schedule. When they move, it matters.
- Vesting schedule fields: next_release_timestamp and final_release_timestamp are Unix timestamps — convert them to a human-readable date. amount_per_period_nanoton is in nanotons — divide by 1e9 for TON. Always tell the user when the next unlock is and how much will be released.
- Large elector unstakes mean validators are pulling out. This can signal selling pressure on TON.
- When presenting historical day data, always add a sentence comparing it to the baseline: "On an average day, the network moves X TON with Y active addresses." Use avg_daily_volume_ton and avg_daily_active_addresses from the response. This tells the user how significant the day was relative to normal.
- The only available historical days are these 5 events: "Notcoin launch" or "NOT airdrop" → 2024-05-16, "TON all-time high" or "TON ATH" → 2024-06-15, "Durov arrested" or "Pavel Durov arrest" → 2024-08-24, "Hamster Kombat listing" or "HMSTR listing" → 2024-09-26, "post-election rally" or "crypto rally" → 2024-11-07. When a user asks to replay or explore one of these events, translate the name to the correct date and call get_historical_day. If the user requests any other date, inform them that only these 5 events are available for now, but more are coming soon.
- price_24h contains TON price history for the last 24h. Use it to summarise the price move: start, end, % change, and whether it was trending up, down, or flat.
- When a whale profile shows concentrated holdings in one token plus unusual volume, connect those dots.
- TON balance lives in get_address_full result under info.balance (in nanotons — divide by 1e9). Jetton holdings are under jettons. The total USD value of all jetton holdings is in total_balance_usd — use this directly when asked what the jettons are worth. Contract type and interfaces are under state.
- If the user pastes a TON address (with or without a question), ALWAYS call get_address_full. It returns info (balance, name, flags), state (contract type, interfaces), and jettons (all holdings) in one shot. Never respond about an address without calling get_address_full first.
- Never say an address "shows no balances" or "holds nothing" based only on jettons being empty — the TON balance is in info.balance.
- If state.interfaces includes Hipo, Tonstakers, or other liquid staking protocols, those positions represent real holdings with value. When asked about portfolio or jetton worth, always mention the staking positions — they are the user's main holdings even if jettons is empty. Never say "no holdings" when liquid staking positions are present.
- DEX price spread > 1%: worth arbitraging or signals low liquidity on one side.
- USDT pool liquidity: usdt_delta negative = liquidity removed (bearish setup). Large z_score spike = unusual LP activity. Reserve imbalance between pools on different DEXes = arbitrage or directional pressure.
- pTON/jetton pool liquidity: tracked hourly in the same snapshot table. Use get_trading_pools to see current reserves for a specific jetton. A sudden drop in reserve_ton signals liquidity exit. Compare reserve_ton across DEXes to spot where depth is concentrated.
- Top holder concentration (e.g. top 3 wallets hold >30% of supply): flag as risk.

Formatting:
- Use emojis where they add clarity. Use HTML formatting: <b>bold</b> for key figures, <i>italic</i> for context. Never use * or ** — HTML only.
- Prices: $X.XXXXXXXX
- Volumes in TON or USD, rounded sensibly (no 12 decimal places)
- If comparing DEXes, name the best rate and the spread %
- If a token isn't in the top 150, ask for the jetton master address
- USDT on TON is EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs (Tether USD). Never use jUSDT (EQBynBO23ywHy_CgarY9NK9FTz0yDsG82PtcbSTQgGoXwiuA) when the user asks about USDT — these are different tokens.
- Never invent data — only use tool results. If a user disputes a result or asks to "check again", always call the tool again — never claim to have re-checked without making an actual tool call.
- Account lists (whales, top holders, etc): format as a numbered list, one per line. Show rank, friendly name or shortened address, and balance. Example:
  1. Binance Hot Wallet — 12.4M TON
  2. EQAbc...xyz — 8.1M TON
- Addresses: ALWAYS wrap in an HTML link — no exceptions. Never say "unidentified account" or "unknown wallet" — always show the address as a link. Link format is EXACTLY https://tonscan.com/{address} — no /address/ path segment.
- Valid tonscan.com link formats: https://tonscan.com/{address} for addresses, https://tonscan.com/transactions/{tx_hash} for transactions. No other paths exist — never link to tonscan.com/events or any other path. Use the friendly name as the label if available, otherwise use the shortened form (first 12 chars + ... + last 4 chars). Examples:
  with name: <a href="https://tonscan.com/EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2">The Locker</a>
  without name: <a href="https://tonscan.com/EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2">EQDtFpEwcFAE...p4q2</a>"""

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="search_token",
        description="Find a TON token/jetton by name or ticker. Returns address and current USD price.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(
                    type=types.Type.STRING,
                    description="Token ticker or name, e.g. 'DOGS' or 'Notcoin'",
                )
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_dex_prices",
        description="Get the price of a token on every DEX (STON.fi, DeDust, TonCo, Coffee). Use after finding the jetton master address.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "jetton_master": types.Schema(
                    type=types.Type.STRING,
                    description="Jetton master contract address",
                )
            },
            required=["jetton_master"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_whale_profile",
        description="Get a full profile for a whale address: all jettons they hold with balances, and the addresses they most frequently transact with. Use when a user wants to investigate a specific whale account.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "address": types.Schema(
                    type=types.Type.STRING, description="TON wallet address to profile"
                ),
            },
            required=["address"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_token_holders",
        description="Get the top holders of a specific jetton ordered by balance. Use to spot concentration risk or identify who controls most of a token's supply.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "jetton_master": types.Schema(
                    type=types.Type.STRING, description="Jetton master contract address"
                ),
                "limit": types.Schema(
                    type=types.Type.INTEGER,
                    description="Number of holders to return (default 20, max 50)",
                ),
            },
            required=["jetton_master"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_jetton_flows",
        description="Get raw buy/sell flow for a specific jetton — shows each account's send/receive volume and transaction count. Use to see who is accumulating or distributing a token.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "jetton_master": types.Schema(
                    type=types.Type.STRING, description="Jetton master contract address"
                ),
            },
            required=["jetton_master"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_jetton_volumes",
        description="Get daily trading volume history for a jetton. Use to spot volume trends or unusual spikes.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "jetton_address": types.Schema(
                    type=types.Type.STRING, description="Jetton master address"
                ),
                "period": types.Schema(
                    type=types.Type.STRING,
                    description="'1w', '1m', or '1y' (default '1w')",
                ),
            },
            required=["jetton_address"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_trading_pools",
        description="Get all DEX pools for a jetton with liquidity, price ratio, pool type, and paired asset info. Use to understand where a token is traded and pool depth.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "address": types.Schema(
                    type=types.Type.STRING, description="Jetton master contract address"
                ),
            },
            required=["address"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_stonfi_trades",
        description="Get OHLCV candle data for a specific STON.fi pool. Use to analyze price action and volume on a particular pool.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "pool_address": types.Schema(
                    type=types.Type.STRING, description="STON.fi pool contract address"
                ),
                "period": types.Schema(
                    type=types.Type.STRING,
                    description="'1w', '1m', or '1y' (default '1w')",
                ),
            },
            required=["pool_address"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_market_info",
        description="Get TON historical price, 24h volume, and market cap data. Use for price trend questions about TON itself.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={},
        ),
    ),
    types.FunctionDeclaration(
        name="get_misc_info",
        description="Get TON network-wide stats: transaction volume and count (24h/7d/30d), active addresses, new accounts, election stake, and TON market cap. Use for general network health or 'what's happening on TON' questions.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={},
        ),
    ),
    types.FunctionDeclaration(
        name="get_network_overview",
        description="Combined snapshot: network stats + 24h price + top whales + whale anomalies + unstake events + largest transactions. Use for broad 'what's happening on TON' or 'any unusual activity?' questions.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "threshold": types.Schema(
                    type=types.Type.NUMBER,
                    description="Z-score threshold for whale anomalies (default 2.0).",
                )
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_top_whales",
        description="Get the top TON whale accounts ranked by transaction volume. Use when asked who the biggest whales are.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "limit": types.Schema(
                    type=types.Type.INTEGER,
                    description="Number of whales to return (default 10).",
                )
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_accounts_top",
        description="Get the top N TON accounts ranked by balance. Use when asked who the whales are, who holds the most TON, give me a list of whales, or who the biggest accounts on the network are.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "limit": types.Schema(
                    type=types.Type.INTEGER,
                    description="Number of accounts to return (default 20, max 100).",
                )
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_transactions_large",
        description="Get the most recent large transactions on TON. Use for questions about big money moves, large transfers happening right now, or what's moving on-chain.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="get_whale_trends",
        description="Get top whale accounts with their daily volume breakdown over the last N days. Use for questions about yesterday's activity, this week vs last week, or whether a whale has been consistently active or just spiked today.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "days": types.Schema(
                    type=types.Type.INTEGER,
                    description="Look-back window in days (1-30, default 7)",
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_whale_anomalies",
        description="Get TON whale accounts showing unusual on-chain activity right now. Returns accounts whose transaction volume deviates significantly from their 24h baseline. also_hedging=true means the whale is simultaneously active in USDT flows — strongest signal.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "threshold": types.Schema(
                    type=types.Type.NUMBER,
                    description="Z-score threshold (default 2.0). Higher = more extreme outliers only.",
                )
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_jetton_anomalies",
        description="Get accounts with unusual buy/sell flow for a specific jetton. Use after finding the jetton master address. Shows who is accumulating or distributing abnormally.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "jetton_master": types.Schema(
                    type=types.Type.STRING,
                    description="Jetton master contract address",
                ),
                "threshold": types.Schema(
                    type=types.Type.NUMBER,
                    description="Z-score threshold (default 2.0).",
                ),
            },
            required=["jetton_master"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_unstake_events",
        description="Get recent large unstaking events on TON. elector = validator withdrawing from Elector contract (>1000 TON). liquid_staking = LST burn (Hipo/Tonstakers). Use when asked about staking outflows or validator behavior.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "hours": types.Schema(
                    type=types.Type.INTEGER,
                    description="Look-back window in hours (1-168, default 24).",
                ),
                "event_type": types.Schema(
                    type=types.Type.STRING,
                    description="Filter to 'elector' or 'liquid_staking'. Omit for all.",
                ),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_usdt_pool_liquidity",
        description="Get USDT liquidity depth across all large DEX pools (StonFi, DeDust, TonCo, Coffee). Shows reserve_usdt, usdt_delta vs previous snapshot, and z_score vs 24h baseline. Use when asked about USDT liquidity, pool depth, LP activity, or signs of liquidity being pulled.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="get_jetton_pool_liquidity",
        description="Get pool liquidity snapshots for a specific jetton across all DEXes — covers both pTON and USDT pairs. Returns reserve0 (TON or USDT side), reserve1 (jetton side), delta vs previous snapshot, and z_score vs 24h baseline. Use when asked about liquidity depth, LP activity, or anomalies for a specific token.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "jetton_master": types.Schema(
                    type=types.Type.STRING, description="Jetton master address"
                )
            },
            required=["jetton_master"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_address_full",
        description="Get complete information for a TON address in one call: balance + friendly name + flags (info), contract state + wallet type + interfaces (state), and all jetton holdings with USD values (jettons). Use this whenever the user asks about any address or wallet.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "address": types.Schema(
                    type=types.Type.STRING, description="TON address"
                ),
            },
            required=["address"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_historical_day",
        description="Get on-chain activity for a specific historical date: top transactions, most active accounts, total volume, and transaction count. Use for questions about what happened on TON on a specific date or during a named event.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "date": types.Schema(
                    type=types.Type.STRING,
                    description="Date in YYYY-MM-DD format (UTC)",
                ),
            },
            required=["date"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_staking_apy",
        description="Get the current TON validator staking APY. Use when asked about staking returns, validator yield, or how much you earn by staking TON.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="get_locker_vesting",
        description="Get the Believers Fund (The Locker) vesting schedule. Returns participants, donors, and a computed schedule with next_release_timestamp, released_so_far, amount_per_period, and periods_elapsed. Use when asked about the locker, believers fund, vesting, next unlock, or when a whale shows also_vesting=true or is_locker=true.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={},
        ),
    ),
]

TOOL_MAP = {
    "search_token": tools.search_token,
    "get_dex_prices": tools.get_dex_prices,
    "get_address_full": tools.get_address_full,
    "get_whale_profile": tools.get_whale_profile,
    "get_token_holders": tools.get_token_holders,
    "get_jetton_flows": tools.get_jetton_flows,
    "get_jetton_volumes": tools.get_jetton_volumes,
    "get_trading_pools": tools.get_trading_pools,
    "get_stonfi_trades": tools.get_stonfi_trades,
    "get_market_info": tools.get_market_info,
    "get_misc_info": tools.get_misc_info,
    "get_network_overview": tools.get_network_overview,
    "get_top_whales": tools.get_top_whales,
    "get_accounts_top": tools.get_accounts_top,
    "get_transactions_large": tools.get_transactions_large,
    "get_whale_trends": tools.get_whale_trends,
    "get_whale_anomalies": tools.get_whale_anomalies,
    "get_jetton_anomalies": tools.get_jetton_anomalies,
    "get_unstake_events": tools.get_unstake_events,
    "get_usdt_pool_liquidity": tools.get_usdt_pool_liquidity,
    "get_jetton_pool_liquidity": tools.get_jetton_pool_liquidity,
    "get_historical_day": tools.get_historical_day,
    "get_staking_apy": tools.get_staking_apy,
    "get_locker_vesting": tools.get_locker_vesting,
}

_gemini_tools = types.Tool(function_declarations=TOOL_DECLARATIONS)


async def run(
    api_key: str, user_message: str, history: list | None = None
) -> tuple[str, list]:
    client = genai.Client(api_key=api_key)
    contents = (history or []) + [
        types.Content(role="user", parts=[types.Part(text=user_message)])
    ]

    for _ in range(5):  # max tool call rounds
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=contents,
            config=types.GenerateContentConfig(
                tools=[_gemini_tools],
                system_instruction=SYSTEM_PROMPT,
            ),
        )

        candidate = response.candidates[0]
        contents.append(candidate.content)

        fn_calls = [p for p in candidate.content.parts if p.function_call]
        if not fn_calls:
            reply = "".join(p.text for p in candidate.content.parts if p.text)
            new_history = (history or []) + [
                types.Content(role="user", parts=[types.Part(text=user_message)]),
                types.Content(role="model", parts=[types.Part(text=reply)]),
            ]
            return reply, new_history[-20:]  # keep last 10 exchanges

        fn_results = []
        for part in fn_calls:
            fn = part.function_call
            logger.info("tool call: %s(%s)", fn.name, dict(fn.args))
            try:
                result = await TOOL_MAP[fn.name](**dict(fn.args))
            except Exception as e:
                result = {"error": str(e)}

            fn_results.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fn.name,
                        response={"result": result},
                    )
                )
            )

        contents.append(types.Content(role="user", parts=fn_results))

    return "Sorry, I couldn't complete that request.", history or []
