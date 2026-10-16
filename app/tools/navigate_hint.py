"""工具：navigate_hint —— 快通道导航提示（模板拼装，不经 LLM 生成文本）。"""

from app.services.location import bearing_text, dist_m

SCHEMA = {
    "type": "function",
    "function": {
        "name": "navigate_hint",
        "description": "获取下一段导航提示（模板文本 + 音频占位）。游客问怎么走、下一步往哪走时调用；播报时照文本念，不要自己发挥方向。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["next", "repeat", "skip"],
                    "description": "next 下一条 / repeat 再说一遍 / skip 跳过，默认 next",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}



async def run(args, ctx):
    state=ctx["state"]
    route=state.get("route")
    if not route or route.get("status")!="ready":
        return {"error":{"code":"no_route","message":"请先规划一条有效路线"}}
    index=route["current_step"]
    if args.get("action")=="skip":
        index=min(index+1,len(route["steps"]))
        route["current_step"]=index
    if route["remaining_m"]<=2:
        return {"text":"已到达路线终点。","remaining_m":0,"next_poi_id":None,"audio_url":None}
    if index>=len(route["steps"]):
        return {"text":"已跳过全部提示，路线终点尚未到达。","remaining_m":route["remaining_m"],"next_poi_id":None,"audio_url":None}
    step=route["steps"][index]
    remaining=max(0,round(step["at_m"]-route["progress_m"]))
    text=f"{step['instruction']}，沿路线约 {remaining} 米。"
    if args.get("action")=="repeat":
        text="再说一遍，"+text
    return {"text":text,"audio_url":None,"next_poi_id":step["poi_id"],"remaining_m":remaining}
