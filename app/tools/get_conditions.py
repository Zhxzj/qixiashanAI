"""工具：get_conditions —— 天气与红叶指数。"""

SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_conditions",
        "description": "查询当前天气、未来趋势与栖霞山红叶指数，用于行程与路线建议。游客问天气、红叶红了多少、要不要带伞时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "未来天数（1-3），默认 1",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


async def run(args, ctx):
    days = int(args.get("days", 1) or 1)
    days = max(1, min(3, days))
    return await ctx["services"]["weather"].get(days=days)

